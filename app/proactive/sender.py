"""Messages Coach Bob sends first. Every few minutes: inside a slot (10am or 9pm,
Singapore time), ask the planner about each user with reminders on, claim the
(user, day, slot) row, have the model write one short message, check it, send.

Code decides whether to send; the model only decides what it says. A message
that fails the checks is dropped and logged, never replaced with a canned line.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.agent.context import build_outbound_prompt
from app.agent.loop import MODEL_COACH, _all_text, _call, clean_style
from app.agent.tools import ONBOARDING_STEPS
from app.db.models import Note, OutboundMessage, User
from app.db.session import SessionLocal
from app.proactive.facts import build_facts, close_old_sick_notes
from app.proactive.planner import plan, slot_at

logger = logging.getLogger(__name__)

INTERVAL_S = 300
STALE_CLAIM = timedelta(minutes=10)
MAX_WORDS = 50
# The Messages API needs a user turn; this one only says it's our move
TRIGGER = "(No new message from them. Write the message you're sending them now.)"


def compose(user: User, reason: str, note: Optional[Note], db: Session) -> str:
    """One model call, no tools: the static prompt, MESSAGING FIRST with the
    reason and the note, then the context block. Usage and cost are logged by
    _call like every reply."""
    system = build_outbound_prompt(user, db, reason, note)
    response = _call(MODEL_COACH, user.user_id, system, [{"role": "user", "content": TRIGGER}],
                     tools=[], max_tokens=300)
    return clean_style(_all_text(response))


def problems(text: str) -> list[str]:
    """Why a message we'd send first can't go out. Empty means it can."""
    out = []
    if not text.strip():
        out.append("empty")
    if len(text.split()) > MAX_WORDS:
        out.append(f"{len(text.split())} words")
    if text.count("?") > 1:
        out.append(f"{text.count('?')} questions")
    return out


def run_once(api, db: Session, now: Optional[datetime] = None,
             composer: Callable = compose) -> int:
    """One pass. Returns how many messages were sent."""
    now = now or clock.now_local()
    _fail_stale_claims(db)
    slot = slot_at(now)
    if slot is None:
        return 0
    users = (db.query(User)
             .filter(User.reminders != "off", User.blocked.is_(False),
                     User.consent_given_at.isnot(None), User.telegram_chat_id.isnot(None),
                     User.onboarding_step >= ONBOARDING_STEPS)
             .all())
    sent = 0
    for user in users:
        try:
            sent += _maybe_send(user, slot, now, api, db, composer)
        except Exception:
            db.rollback()
            logger.error("event=outbound_error", exc_info=True,
                         extra={"event": "outbound_error", "user_id": user.user_id})
    return sent


def _maybe_send(user: User, slot: str, now: datetime, api, db: Session, composer: Callable) -> int:
    close_old_sick_notes(user.user_id, db, now.date())
    decision = plan(build_facts(user, db, now), slot, now)
    if decision is None:
        return 0

    # Claim before the model is called: the unique (user, day, slot) key means a
    # restart or a second instance can't send this slot again
    row = OutboundMessage(user_id=user.user_id, local_date=now.date(), slot=slot,
                          reason=decision.reason, note_id=decision.note_id, status="claimed",
                          claimed_at=datetime.utcnow())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return 0
    _log("outbound_claimed", user.user_id, decision.reason)

    note = db.get(Note, decision.note_id) if decision.note_id else None
    try:
        text = composer(user, decision.reason, note, db)
    except Exception:
        row.status = "failed"
        db.commit()
        logger.error("event=outbound_compose_failed", exc_info=True,
                     extra={"event": "outbound_compose_failed", "user_id": user.user_id})
        return 0

    issues = problems(text)
    if issues:
        row.status, row.text = "dropped", text
        db.commit()
        _log("outbound_dropped", user.user_id, f"{decision.reason}: {', '.join(issues)}")
        return 0

    try:
        api.send_message(user.telegram_chat_id, text)
    except Exception as e:
        row.status = "failed"
        if getattr(e, "code", None) == 403:
            # They blocked the bot: never message first again
            user.reminders = "off"
            _log("outbound_blocked_by_user", user.user_id, decision.reason)
        db.commit()
        return 0
    row.status, row.text, row.sent_at = "sent", text, datetime.utcnow()
    db.commit()
    _log("outbound_sent", user.user_id, decision.reason)
    return 1


def _fail_stale_claims(db: Session) -> None:
    """A claim left more than 10 minutes (the process died mid-send) is marked
    failed, never retried: better a missed check-in than a double one."""
    cutoff = datetime.utcnow() - STALE_CLAIM
    stale = db.query(OutboundMessage).filter(OutboundMessage.status == "claimed",
                                             OutboundMessage.claimed_at < cutoff).all()
    for row in stale:
        row.status = "failed"
        _log("outbound_claim_expired", row.user_id, row.reason)
    if stale:
        db.commit()


def run_safely(api) -> None:
    db = SessionLocal()
    try:
        run_once(api, db)
    except Exception:
        logger.error("event=outbound_pass_failed", exc_info=True, extra={"event": "outbound_pass_failed"})
    finally:
        db.close()


async def loop_forever(api) -> None:
    """The background task in the FastAPI app: a pass every 5 minutes, the
    blocking work in a thread."""
    while True:
        await asyncio.to_thread(run_safely, api)
        await asyncio.sleep(INTERVAL_S)


def _log(event: str, user_id: int, detail: str = "") -> None:
    logger.info("event=%s user_id=%s detail=%s", event, user_id, detail,
                extra={"event": event, "user_id": user_id, "detail": detail})
