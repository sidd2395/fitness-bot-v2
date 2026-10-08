import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import anthropic
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.db.models import RawMessage, User
from app.agent.tools import (ONBOARDING_STEPS, TOOL_SCHEMAS, add_sports_from_message, dispatch,
                             only_from_message)
from app.agent.context import build_system_prompt, build_trainer_ack_prompt
from app.capabilities import all_set_text
from app.pricing import cost_usd, usage_counts

load_dotenv()

# Onboarding is the first impression and sets the voice, so it gets the coaching model too
MODEL_ONBOARDING = os.environ.get("MODEL_ONBOARDING") or "claude-sonnet-5"
MODEL_COACH = os.environ.get("MODEL_COACH") or "claude-sonnet-5"
MAX_TOOL_CALLS = 4
# Onboarding is offered save_profile and nothing else, so a check-in sent
# mid-onboarding can never be logged, whatever the model tries
ONBOARDING_TOOLS = [t for t in TOOL_SCHEMAS if t["name"] == "save_profile"]
HISTORY_EXCHANGES = 3
HISTORY_WINDOW = timedelta(hours=24)

# Fixed replies, sent from code with no model call
WELCOME_REPLY = (
    "Hi, I'm Coach Bob, an AI fitness coach. Send me a quick check-in each day and "
    "I'll help you stay on track. To start, what's your first name?"
)
BLOCKED_REPLY = (
    "Sorry, I can only coach people aged 18 and over. A parent, school coach or "
    "doctor is a good person to talk to about training."
)
ONBOARDED_REPLY = all_set_text()   # built from app/capabilities.py
# When no reply text can be produced at all: one wording if this turn saved
# something, another if it saved nothing
EMPTY_REPLY_SAVED = (
    "Logged. Your coaching didn't come through this time, but your data's saved."
)
EMPTY_REPLY_NOTHING_SAVED = (
    "Sorry, I couldn't put a reply together just now. Try sending that again in a moment."
)
# The reply said something was saved but no tool saved anything this turn.
# Sent back as a tool-result style note for one more step.
NO_SAVE_NOTE = (
    "No tool saved anything this turn. Call the tool now, or reply without saying it was saved."
)
# Still a save claim with nothing saved after that step: an honest line instead
UNBACKED_SAVE_REPLY = "Sorry, that didn't save on my side. Send it once more and I'll try again."
# Sent back with tool results when the model wrote text alongside its tool call.
# That text is a draft and is never sent, so the next reply has to stand alone.
DRAFT_NOT_SENT_NOTE = (
    "The text you wrote alongside those tool calls was not sent to the person. "
    "Your next reply is the only thing they will see, so make it complete, "
    "including any warning."
)

_client = anthropic.Anthropic()
logger = logging.getLogger(__name__)


def run(user_id: int, message: str, db: Session) -> str:
    user = db.get(User, user_id)

    # Under 18: nothing about them is stored, not even this message
    if user.blocked:
        _log("blocked_reply", user_id)
        return BLOCKED_REPLY

    # Guardrail: raw message on disk before the agent touches anything.
    # An exception anywhere below marks it 'failed'; successful turns mark it 'processed'.
    raw_msg = RawMessage(user_id=user_id, body=message, status="received")
    db.add(raw_msg)
    user.last_active_at = datetime.utcnow()
    db.commit()
    db.refresh(raw_msg)

    try:
        reply = clean_style(_respond(user, message, raw_msg, db))
    except Exception:
        raw_msg.status = "failed"
        db.commit()
        raise

    # Blocked during this turn: save_profile has already deleted every raw
    # message, this one included, so there is nothing to write the reply to
    if user.blocked:
        return reply

    # Sports they name go into disciplines in code, whatever the model did
    added = add_sports_from_message(user_id, message, db)
    if added:
        _log("sports_added", user_id, ",".join(added))

    # Save the reply and mark processed in one commit.
    # reply_text is written regardless of status so failed rows still show what the user saw.
    db.refresh(raw_msg)
    raw_msg.reply_text = reply
    if raw_msg.status == "received":
        raw_msg.status = "processed"
    db.commit()

    return reply


def _respond(user: User, message: str, raw_msg: RawMessage, db: Session) -> str:
    # On Telegram the welcome goes out with the consent notice, and the tap on
    # "I agree" asks for their name, so a consented user's first message is the answer
    if (user.onboarding_step == 0 and user.consent_given_at is None
            and _is_first_message(user.user_id, raw_msg.id, db)):
        _log("welcome", user.user_id)
        return WELCOME_REPLY

    messages = _history(user.user_id, raw_msg.id, db) + [{"role": "user", "content": message}]

    if user.onboarding_step < ONBOARDING_STEPS:
        return _onboard(user, messages, raw_msg, db)
    return _coach(user, message, messages, raw_msg, db)


# --------------------------------------------------------------------------- #
# Short-term memory                                                             #
# --------------------------------------------------------------------------- #

def _is_first_message(user_id: int, raw_msg_id: int, db: Session) -> bool:
    earlier = (
        db.query(RawMessage.id)
        .filter(RawMessage.user_id == user_id, RawMessage.id < raw_msg_id)
        .first()
    )
    return earlier is None


def _history(user_id: int, raw_msg_id: int, db: Session) -> list[dict]:
    """The last few exchanges from the past 24 hours, oldest first, so the model
    knows what it just asked. Tool calls from earlier turns are not replayed."""
    rows = (
        db.query(RawMessage)
        .filter(
            RawMessage.user_id == user_id,
            RawMessage.id < raw_msg_id,
            RawMessage.created_at >= datetime.utcnow() - HISTORY_WINDOW,
            RawMessage.reply_text.isnot(None),
            RawMessage.reply_text != "",
        )
        .order_by(RawMessage.id.desc())
        .limit(HISTORY_EXCHANGES)
        .all()
    )
    messages = []
    for row in reversed(rows):
        messages.append({"role": "user", "content": row.body})
        messages.append({"role": "assistant", "content": row.reply_text})
    return messages


# --------------------------------------------------------------------------- #
# Onboarding: every answer goes through save_profile, forced                    #
# --------------------------------------------------------------------------- #

def _onboard(user: User, messages: list, raw_msg: RawMessage, db: Session) -> str:
    response = _call(
        MODEL_ONBOARDING, user.user_id, build_system_prompt(user, db), messages,
        tool_choice={"type": "tool", "name": "save_profile"}, tools=ONBOARDING_TOOLS,
    )
    _log("onboarding_save", user.user_id)
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": _run_tools(response, user.user_id, raw_msg.id, db,
                                                           allowed={"save_profile"})})

    db.refresh(user)
    if user.blocked:
        _log("blocked", user.user_id)
        return BLOCKED_REPLY
    if user.onboarding_step >= ONBOARDING_STEPS:
        _log("onboarding_complete", user.user_id)
        ack = _trainer_ack(user, messages) if user.trainer_name else ""
        return f"{ack}\n\n{ONBOARDED_REPLY}" if ack else ONBOARDED_REPLY

    # Rebuilt so the per-turn block names the question that is now next
    response = _call(
        MODEL_ONBOARDING, user.user_id, build_system_prompt(user, db), messages,
        tool_choice={"type": "none"}, tools=ONBOARDING_TOOLS,
    )
    return _extract_text(response)


def _trainer_ack(user: User, messages: list) -> str:
    """One sentence acknowledging who helps them, ahead of the fixed "all set"
    line. Dropped if it asks a question or the call fails: the fixed line is enough."""
    try:
        response = _call(MODEL_ONBOARDING, user.user_id, build_trainer_ack_prompt(user), messages,
                         tool_choice={"type": "none"}, tools=ONBOARDING_TOOLS, max_tokens=120)
    except Exception:
        _log("trainer_ack_failed", user.user_id)
        return ""
    lines = [line.strip() for line in _all_text(response).splitlines() if line.strip()]
    ack = lines[0] if lines else ""
    if "?" in ack:
        _log("trainer_ack_dropped", user.user_id, "question")
        return ""
    return ack


# --------------------------------------------------------------------------- #
# Coaching                                                                      #
# --------------------------------------------------------------------------- #

def _coach(user: User, message: str, messages: list, raw_msg: RawMessage, db: Session) -> str:
    user_id = user.user_id
    system = build_system_prompt(user, db)
    tool_calls_used = 0
    checkin_logged = False
    safety_net_run = False
    claim_checked = False   # the reply was sent back once for claiming an unmade save
    saved_this_turn = False   # a write tool actually saved or resolved something
    final = ""              # text of the response that ends the turn: the reply
    drafts: list[str] = []  # text written alongside tool calls: never sent unless final is empty

    def run_tools(response, force_checkin: bool = False) -> None:
        nonlocal tool_calls_used, checkin_logged, saved_this_turn
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if tool_calls_used >= MAX_TOOL_CALLS:
                # Cap reached mid-response: return an error result so the
                # model at least sees its tool was refused
                tool_results.append(_tool_result(block.id, {"error": "tool call limit reached"}))
                continue
            # is_correction is honoured only if the message itself says it's a
            # correction or a yes (checked in log_checkin), forced call or not
            inp, dropped = block.input, []
            if force_checkin and block.name == "log_checkin":
                # Forced on this message, so it logs only what this message says
                inp, dropped = only_from_message(block.input, message)
            result = dispatch(block.name, inp, user_id, raw_msg.id, db)
            if dropped:
                result = {**result, "not_in_this_message": dropped}
                _log("forced_fields_dropped", user_id, ",".join(dropped))
            tool_results.append(_tool_result(block.id, result))
            tool_calls_used += 1
            saved_this_turn = saved_this_turn or bool(result.get("saved")) or bool(result.get("resolved"))
            _log("forced_checkin" if force_checkin else "tool_call", user_id,
                 f"{block.name} saved={bool(result.get('saved'))}")
            if block.name == "log_checkin":
                checkin_logged = True
        draft = _all_text(response)
        if draft:
            drafts.append(draft)
            # After the tool results: the API wants tool_result blocks first
            tool_results.append({"type": "text", "text": DRAFT_NOT_SENT_NOTE})
        messages.append({"role": "user", "content": tool_results})

    # ------------------------------------------------------------------ #
    # Main agent loop                                                      #
    # ------------------------------------------------------------------ #
    while True:
        response = _call(MODEL_COACH, user_id, system, messages)
        _log("agent_turn", user_id)

        if response.stop_reason != "tool_use":
            # -------------------------------------------------------------- #
            # Safety net, before the reply is final                           #
            # The model is about to reply without having called log_checkin, #
            # but the message looks like check-in data. Discard that draft,  #
            # force a log_checkin call and hand its result back, so the      #
            # reply is written knowing what was saved or rejected.           #
            # -------------------------------------------------------------- #
            if not checkin_logged and not safety_net_run and _looks_like_checkin(message):
                safety_net_run = True
                _log("forced_checkin_attempt", user_id)
                try:
                    forced = _call(
                        MODEL_COACH, user_id, system, messages,
                        tool_choice={"type": "tool", "name": "log_checkin"},
                        max_tokens=512,
                    )
                    messages.append({"role": "assistant", "content": forced.content})
                    run_tools(forced, force_checkin=True)
                    continue
                except Exception:
                    # Keep the draft: the user still gets a reply
                    _log("forced_checkin_failed", user_id)
                    raw_msg.status = "failed"
                    db.commit()
            final = _all_text(response)
            # Never trust the model's word about what happened: a reply saying
            # something was saved, with no write this turn, gets one more step
            if final and not saved_this_turn and not claim_checked and claims_a_save(final):
                claim_checked = True
                _log("unbacked_save_claim", user_id)
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": [{"type": "text", "text": NO_SAVE_NOTE}]})
                final = ""
                continue
            break

        messages.append({"role": "assistant", "content": response.content})
        run_tools(response)

        # ------------------------------------------------------------------ #
        # Forced text reply                                                    #
        # Cap reached: one more call with tool_choice=none forces a text      #
        # reply without allowing further tool use.                            #
        # ------------------------------------------------------------------ #
        if tool_calls_used >= MAX_TOOL_CALLS:
            response = _call(MODEL_COACH, user_id, system, messages, tool_choice={"type": "none"})
            _log("forced_text", user_id)
            final = _all_text(response)
            break

    # ------------------------------------------------------------------ #
    # Reply: only the final text. Text written alongside a tool call is a #
    # draft: sending it as well duplicated warnings and advice, so the    #
    # model is told it wasn't sent and writes a complete final reply.     #
    # Fallback ladder if the final text is empty: the latest draft, then  #
    # one retry with text forced, then a fixed line so the user never     #
    # gets silence.                                                        #
    # ------------------------------------------------------------------ #
    reply = final
    if not reply and drafts:
        _log("draft_used", user_id)
        reply = drafts[-1]
    if not reply:
        _log("empty_reply_retry", user_id)
        reply = _all_text(_call(MODEL_COACH, user_id, system, messages, tool_choice={"type": "none"}))
    if not reply:
        _log("empty_reply_fallback", user_id, "saved" if saved_this_turn else "nothing_saved")
        reply = EMPTY_REPLY_SAVED if saved_this_turn else EMPTY_REPLY_NOTHING_SAVED
    if not saved_this_turn and claims_a_save(reply):
        _log("unbacked_save_reply_replaced", user_id)
        reply = UNBACKED_SAVE_REPLY
    return reply


# A claim, in the coach's own voice, that something was saved just now. Not "you
# logged 71.2 on the 30th" (a fact about the past), and not bare "set" ("you're all set").
_SAVE_CLAIM = re.compile(
    r"\b(i'?ve|i have|i)\s+(just\s+|now\s+|also\s+)?"
    r"(saved|logged|recorded|updated|stored|locked in|noted( down)?|added|changed|set)\b"
    r"|\bgot (it|that|this|them|those|both|everything)\s+(all\s+)?"
    r"(saved|logged|recorded|down|updated|locked in|noted|set)\b"
    r"|\b(it'?s|that'?s|they'?re|both are|those are|now)\s+(been\s+)?"
    r"(saved|logged|recorded|updated|stored|locked in)\b"
    r"|^\W*(saved|logged|updated|all saved|done,? saved)\b"
    r"|\b(saved|logged|recorded|updated|locked in) (it|that|them|those|both) (for you|as)\b"
    r"|\d(\.\d+)?\s*(kg|kgs|h|hrs|g|cal|kcal|l)?\s+(noted|logged|saved)\b",
    re.I | re.M,
)


def claims_a_save(text: str) -> bool:
    return bool(_SAVE_CLAIM.search(text or ""))


# "Dan wants me on 2200 cal", "set my calories to 900": a target, not a check-in
_TARGET_STATEMENT = re.compile(
    r"\b(targets?|wants? me (on|at|to)|ha(s|ve) me (on|at)|put me on|aim(ing)? for|set my|"
    r"should (eat|have|be on)|supposed to (eat|have))\b", re.I)
_TARGET_UNITS = re.compile(r"\b(cals?|kcal|calories|protein|water|litres?|liters?)\b", re.I)


def _looks_like_checkin(message: str) -> bool:
    # A number and not a question: "weight 820", "82.4 slept 5hrs"
    if _TARGET_STATEMENT.search(message) and _TARGET_UNITS.search(message):
        return False
    return any(c.isdigit() for c in message) and "?" not in message


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _call(model: str, user_id: int, system: list, messages: list,
          tool_choice: Optional[dict] = None, max_tokens: int = 1024,
          tools: Optional[list] = None):
    kwargs = {"tool_choice": tool_choice} if tool_choice else {}
    started = time.monotonic()
    response = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        # Off on every model so Haiku and Sonnet behave alike, and because forced
        # tool_choice can't be combined with thinking (Sonnet 5 thinks by default)
        thinking={"type": "disabled"},
        system=system,
        tools=tools if tools is not None else TOOL_SCHEMAS,
        messages=messages,
        **kwargs,
    )
    # Why a turn ended and what it contained (block types only, never content),
    # so an empty reply can be traced to its cause
    blocks = ",".join(b.type for b in response.content) or "none"
    _log("model_call", user_id, f"model={model} stop={response.stop_reason} blocks={blocks}")
    _record_usage(user_id, model, response.usage, round((time.monotonic() - started) * 1000))
    if any(b.type in ("thinking", "redacted_thinking") for b in response.content):
        # Thinking is disabled on every call, so this shouldn't happen. The
        # request id lets Anthropic look the call up.
        request_id = getattr(response, "_request_id", None)
        logger.warning("event=unexpected_thinking user_id=%d model=%s request_id=%s",
                       user_id, model, request_id,
                       extra={"event": "unexpected_thinking", "user_id": user_id, "model": model,
                              "detail": f"request_id={request_id}"})
    return response


def _record_usage(user_id: int, model: str, usage, latency_ms: Optional[int] = None) -> None:
    """Token counts, cost and latency for one call. Prices live in app/pricing.py."""
    c = usage_counts(usage)
    cost = cost_usd(model, c)
    _log("usage", user_id,
         f"model={model} input={c['input_tokens']} output={c['output_tokens']} "
         f"cache_read={c['cache_read_input_tokens']} cache_write={c['cache_creation_input_tokens']}",
         model=model, input_tokens=c["input_tokens"], output_tokens=c["output_tokens"],
         cache_read_tokens=c["cache_read_input_tokens"],
         cache_write_tokens=c["cache_creation_input_tokens"],
         cost_usd=round(cost, 6) if cost is not None else None, latency_ms=latency_ms)


def _run_tools(response, user_id: int, raw_msg_id: int, db: Session,
               allowed: Optional[set] = None) -> list[dict]:
    results = []
    for block in response.content:
        if block.type == "tool_use" and allowed is not None and block.name not in allowed:
            # Refused, never run: the model still gets a result for its call
            results.append(_tool_result(block.id, {"error": f"{block.name} isn't available during onboarding."}))
            _log("tool_refused", user_id, block.name)
        elif block.type == "tool_use":
            results.append(_tool_result(block.id, dispatch(block.name, block.input, user_id, raw_msg_id, db)))
            _log("tool_call", user_id, block.name)
    return results


def _tool_result(tool_use_id: str, content: dict) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(content, default=str),
    }


def _extract_text(response) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def _all_text(response) -> str:
    """Every text block in a response, joined; empty if there is none."""
    return "\n\n".join(b.text.strip() for b in response.content if b.type == "text" and b.text.strip())


def clean_style(text: str) -> str:
    """House style enforced in code: no em or en dashes (or a spaced hyphen used as
    one), no bold or underline markers."""
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(\d)\s*–\s*(\d)", r"\1 to \2", text)   # 5–6 hours -> 5 to 6 hours
    text = re.sub(r"[ \t]*[—–][ \t]*", ", ", text)
    text = re.sub(r"(?<=[A-Za-z])[ \t]+-[ \t]+(?=[A-Za-z])", ", ", text)  # "word - word"
    text = re.sub(r"([.!?;:])[ \t]*,", r"\1", text)         # ". —" left ".,"
    text = re.sub(r",[ \t]*([,.!?;:])", r"\1", text)        # "— ." left ", ."
    text = re.sub(r"^[ \t]*,[ \t]*", "", text, flags=re.M)  # dash that opened a line
    text = re.sub(r"[ \t]*,[ \t]*$", "", text, flags=re.M)  # dash that ended a line
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _log(event: str, user_id: int, detail: str = "", **fields) -> None:
    # Event type, user id and numbers only, never message content or tool arguments.
    # The fields also go in `extra`, so JSON logs carry them as keys (app/logs.py).
    logger.info("event=%s user_id=%d detail=%s", event, user_id, detail,
                extra={"event": event, "user_id": user_id, "detail": detail, **fields})
