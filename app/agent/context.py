import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from sqlalchemy.orm import Session

from app.db.models import Checkin, Note, RawMessage, User
from app.agent.stats import (claim_milestone, claim_steady_weight, claim_tip, compute as compute_stats,
                             describe_sleep_run, lead_with_trend, note_timing,
                             weight_change_since_last, weight_trend)
from app import capabilities, clock
from app.agent.tools import ONBOARDING_LABELS, ONBOARDING_STEPS

# --------------------------------------------------------------------------- #
# Coach voice — edit prompts/coach.md, not this file. Loaded once at startup.   #
# --------------------------------------------------------------------------- #

COACH_PROMPT = (Path(__file__).parent / "prompts" / "coach.md").read_text().strip()

# --------------------------------------------------------------------------- #
# Tool rules — apply to every turn, onboarding and coaching                     #
# --------------------------------------------------------------------------- #

_TOOL_RULES = """# Tools and memory

- If the message reports any check-in data, call log_checkin before replying. \
If it is only a question or chat, do not call log_checkin.
- Call tools first. Write your reply only after the tool results come back, \
never before or alongside a tool call. The reply is everything the person \
sees, so warnings and advice go there, not in text next to a tool call.
- Never refuse a partial check-in. Save whatever was given.
- Food in plain words ("ate lighter", "big dinner out") goes in log_checkin \
food_note, as they said it. Never turn it into calories or protein, and never \
estimate a number they didn't give.
- Earlier messages in this conversation are real. Use them to make sense of \
short replies like "yes", "no", "so what now" or "thanks".
- If log_checkin returns rejected fields, those were not saved. Ask what \
they meant, one field only.
- Corrections: if they explicitly correct a value they already logged today \
("actually 63.0 not 63.2", "sorry I meant 7h"), call log_checkin with the new \
value and is_correction=true straight away. Don't ask them to confirm.
- A new value that differs from one already logged today, with no sign it's a \
correction (just "62.6" later on), is not a correction. Call log_checkin \
without is_correction; it will come back as needs_confirmation.
- If log_checkin returns needs_confirmation, those values were not changed. \
Ask one short yes/no question naming the new value, like "Update today's \
weight to 63.0?". Only when they say yes, call log_checkin again with the new \
value and is_correction=true. If they say no, leave it as it is.
- If log_checkin returns an error, tell them plainly what it means for them.
- If save_profile returns a refused calorie_target, explain why in plain \
language and carry on without setting a target.
- Never ask for anything already listed under PROFILE: name, age, sex, goal \
or weight.
- After onboarding, only call save_profile to change name, age, sex, goal, \
starting weight or motivation when their message explicitly says to change \
that value ("my starting weight was actually 94"). A check-in weight is not a \
new starting weight. Code refuses any change the message doesn't back up.
- Durable facts about them go somewhere that lasts: a profile field if one \
fits, otherwise remember. Who coaches them or tracks their food or weight: \
save_profile trainer_name, straight away, no need to ask. A sport or kind of \
training they do: save_profile disciplines (only new ones). Never use a fact \
for one reply and drop it.
- Targets: when they state a calorie, protein or water target, their own or \
their coach's, ask one yes/no question naming the targets and whose they are \
("Want me to save 2200 cal and 160g protein as Dan's targets?"). When they \
say yes, call save_profile with the values and targets_set_by ("user" or \
"coach") in that turn. Never say a target is saved unless save_profile \
returned it under saved. Never propose a target yourself.
- Never ask about a field listed under "Fields already reminded about today".
- remember: save things that will matter in later conversations: schedule, \
travel, events, likes and dislikes, work or family context that affects \
training. One fact per note, short and specific. If there's something worth \
asking about later, set follow_up_on, usually the day after it ends, worked \
out from today's date. Never save check-in numbers (log_checkin) or injuries \
and health issues (save_profile issue). Don't save what is already under NOTES.
- When FOLLOW-UPS DUE lists a note, ask about it naturally in this reply and \
call resolve_note with its id in the same turn, so you only ask once. Also \
resolve a note when they tell you it's no longer true.
- get_history: the context block shows only the last 3 days. Call \
get_history before answering about older days, and always before saying \
anything wasn't logged or telling them they're wrong about their own data. \
If it's still not there, say you can't see it, never that they didn't send it.
- When they ask for a summary, their stats, a table, or something to send a \
trainer: tell them to send /summary for the last 14 days, or /summary \
followed by any number of days up to 60 (/summary 10, /summary 30). It \
builds a table they can forward. Don't write the table yourself.
- Injury reminders: each active issue has a line in the context block. \
"reminder already given today": don't mention it again today, not even in \
passing or in a question, unless their message mentions an exercise or pain \
that affects it. "reminder given today: no": \
remind them once if today's training touches it.
- remember: for a trip or event with dates, pass starts_on and ends_on, \
worked out from today's date. Code then shows whether it's upcoming, \
happening now or over.
- Check-in requests: the context block has one line about this, and it \
decides. "No check-in yet": before their first ever check-in, one gentle \
invitation to send it is fine, at most one per reply. "Already asked today": \
do not ask for a check-in again, and don't end with an invitation to log. \
"Check-in requested today: no": you may ask once today if nothing is logged \
yet, never in a reply to thanks, small talk, or a message that isn't about \
their training.\
"""

# --------------------------------------------------------------------------- #
# Onboarding — static rules and the full question list. Which question is next #
# goes in the per-turn block, so this text never changes and stays cached.      #
# --------------------------------------------------------------------------- #

_ONBOARDING_RULES = """# Onboarding

When the context block says ONBOARDING, you are meeting a new person. Use the \
same voice as above: warm, brief, one question per message. The reply shape \
and word counts above don't apply, and there is no coaching yet.

- Every onboarding message comes with a save_profile call. Put in whatever \
answers they gave, several at once if they gave several. Leave out anything \
they didn't answer. If they answered nothing, call it with no fields.
- Pass numbers as they gave them. Age in words is fine. If they gave weight \
in pounds, pass the pounds number with weight_unit "lb". Code converts.
- If save_profile refused a value, say briefly why and ask again.
- Otherwise react briefly if it helps, then ask the next question. The \
context block says which one. Never ask for something already saved.
- If they ask about something else, say briefly it isn't your area and ask \
the current question again.
- One question per message, in one sentence with one question mark. Don't \
open with their name.

Questions, in order:
1. name: Ask for their first name only.
2. age: Ask how old they are.
3. sex: Ask whether they are male or female. Accept M, F, male, female or \
similar.
4. current weight: Ask for their current weight. Kilograms or pounds are \
both fine.
5. main goal: Ask for their main goal, listing the four options in the same \
sentence as the question, with a single question mark at the end: lose fat, \
build muscle, perform better or feel better. Accept natural language and \
map it to lose_fat, build_muscle, perform or feel_better. If they pick \
several or "all of the above", save no goal and ask which one matters most \
to them right now, in one question. Don't pick one for them, and don't say \
how the goals relate or that one covers the others.
6. why they're starting now: Ask what made them want to start now. Any \
answer is fine. Save a short version in their own words as motivation. If \
they aren't sure, call save_profile with motivation="" and move on.
7. injuries or health issues: Ask about any injuries or health issues you \
should know about before giving training advice. If they say none, call \
save_profile with issue="".
8. trainer: Ask if they have a personal trainer or coach. If they say no, \
call save_profile with trainer_name="". If they name or describe anyone who \
coaches them or tracks their training or food, save their name, or a short \
description if there's no name, as trainer_name. If they only say yes, save \
nothing and ask who it is.

When the context block says ONBOARDING COMPLETE, they have just told you \
who helps them. Acknowledge that person in one short sentence, with no \
question. Don't say they're ready, set up or all set: code adds that line \
after yours.\
"""

# Everything above is identical for every user and every turn: cached.
STATIC_PROMPT = f"{COACH_PROMPT}\n\n{capabilities.prompt_text()}\n\n{_TOOL_RULES}\n\n{_ONBOARDING_RULES}"

# --------------------------------------------------------------------------- #
# Public entry point                                                            #
# --------------------------------------------------------------------------- #

def build_system_prompt(user: User, db: Session) -> list[dict]:
    """Static part first with a cache breakpoint, then the part that changes each turn."""
    if user.onboarding_step < ONBOARDING_STEPS:
        dynamic = _onboarding_block(user)
    else:
        dynamic = _context_block(user, db)
    return [
        {"type": "text", "text": STATIC_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic},
    ]


# --------------------------------------------------------------------------- #
# Onboarding mode                                                               #
# --------------------------------------------------------------------------- #

def _onboarding_block(user: User) -> str:
    step = user.onboarding_step
    profile = user.profile
    known = []
    if user.name:
        known.append(f"name {user.name}")
    if user.age:
        known.append(f"age {user.age}")
    if user.sex:
        known.append(f"sex {_SEX_LABEL.get(user.sex, user.sex)}")
    if profile and profile.start_weight:
        known.append(f"weight {profile.start_weight}kg")
    if profile and profile.goal:
        known.append(f"goal {profile.goal.replace('_', ' ')}")
    return (
        f"ONBOARDING\n"
        f"Next question: {step + 1} of {ONBOARDING_STEPS}, {ONBOARDING_LABELS[step]}.\n"
        f"Saved so far: {', '.join(known) if known else 'nothing'}."
    )


def build_trainer_ack_prompt(user: User) -> list[dict]:
    """For the one-line acknowledgement of their trainer when onboarding ends."""
    return [
        {"type": "text", "text": STATIC_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f'ONBOARDING COMPLETE\nWho helps them: "{user.trainer_name}".'},
    ]


# --------------------------------------------------------------------------- #
# Coaching mode                                                                 #
# --------------------------------------------------------------------------- #

_SEX_LABEL = {"M": "male", "F": "female"}
NOTES_SHOWN = 10


def _follow_up(note: Note) -> str:
    return f" (follow up {note.follow_up_on.strftime('%a %d %b')})" if note.follow_up_on else ""


def _note_line(note: Note, today: date) -> str:
    """A note with its dates and where it stands today, worked out here."""
    line = f"- [{note.note_id}] {note.text}"
    timing = note_timing(note.starts_on, note.ends_on, today)
    if timing:
        start = note.starts_on or note.ends_on
        end = note.ends_on or note.starts_on
        span = start.strftime("%a %d %b") + ("" if end == start else f" to {end.strftime('%a %d %b')}")
        line += f" ({span}: {timing})"
    return line + _follow_up(note)


def _context_block(user: User, db: Session) -> str:
    today = date.today()
    profile = user.profile
    active_issues = [i for i in user.issues if i.status == "active"]
    s = compute_stats(user.user_id, db, today)

    # Fetch last 3 days once — reused for both the history display and today's fields
    three_days_ago = today - timedelta(days=3)
    recent = (
        db.query(Checkin)
        .filter(Checkin.user_id == user.user_id, Checkin.date >= three_days_ago)
        .order_by(Checkin.date.desc())
        .all()
    )
    today_checkins = [c for c in recent if c.date == today]

    lines: list[str] = [f"Today: {today.strftime('%A %d %B %Y')} ({today.isoformat()})."]
    now = clock.now_local()
    lines.append(f"Local time: {now:%H:%M} Singapore, {clock.part_of_day(now.hour)}. Anything they "
                 "said they'd do later today hasn't happened unless they've told you it has.")

    # --- Profile ----------------------------------------------------------- #
    lines.append("")
    lines.append("PROFILE")
    goal = (profile.goal or "not set").replace("_", " ") if profile else "not set"
    sex = _SEX_LABEL.get(user.sex, "not set")
    lines.append(f"Name: {user.name}. Age: {user.age}. Sex: {sex}. Goal: {goal}.")
    if profile and profile.start_weight:
        lines.append(f"Starting weight: {profile.start_weight}kg.")
    if profile and profile.disciplines:
        lines.append(f"Trains: {profile.disciplines.replace(',', ', ')}.")
    if profile:
        targets: list[str] = []
        if profile.calorie_target:
            targets.append(f"{profile.calorie_target} cal")
        if profile.protein_target_g:
            targets.append(f"{profile.protein_target_g}g protein")
        if profile.water_target_l:
            targets.append(f"{profile.water_target_l:g}L water")
        if targets:
            lines.append(f"Targets: {', '.join(targets)} (set by {profile.targets_set_by}).")
    if profile and profile.motivation:
        lines.append(f'Why they started, in their words: "{profile.motivation}".')
    if user.trainer_name:
        lines.append(f'Trainer or coach: "{user.trainer_name}".')

    # --- Active issues — loaded every turn so they are never forgotten ------ #
    if active_issues:
        lines.append("")
        lines.append("ACTIVE ISSUES")
        for issue in active_issues:
            lines.append(f"- {issue.what} (since {issue.first_mentioned.strftime('%d %b')})")
        for issue in active_issues:
            lines.append(issue_reminder_line(issue, user.user_id, today, db))

    # --- Computed facts — code does the maths, model reads the numbers ------ #
    lines.append("")
    lines.append("WHERE THEY ARE")
    lines.append(
        f"Logged {s['days_logged_last_14']} of the last 14 days. "
        f"Day {s['days_since_joined']} since joining."
    )
    # The only streak figure the coach may use. After a gap there is none.
    if s["days_in_a_row"] >= 2:
        lines.append(f"Days in a row: {s['days_in_a_row']}.")
    else:
        lines.append("Days in a row: none, so don't call anything a streak.")
    if s["days_since_last_checkin"] and s["days_since_last_checkin"] > 1:
        lines.append(f"Back after a gap: last check-in before today was "
                     f"{s['days_since_last_checkin']} days ago.")
    last = weight_change_since_last(user.user_id, db, today)
    if last:
        lines.append(f"Weight today {last['weight_kg']:.1f}kg: {last['in_words']}. "
                     "Use these words as given.")
    goal = profile.goal if profile else None
    trend = weight_trend(user.user_id, db, today, goal)
    if trend:
        lines.append(f"Trend: {trend['in_words']}. Use these words as given.")
        lead = lead_with_trend(last, trend, goal)
        if lead:
            lines.append(lead)
    steady = claim_steady_weight(user.user_id, db, today, goal)
    if steady:
        who = f"to check with {user.trainer_name}" if user.trainer_name else "to try"
        lines.append(f"{steady}. Mention it once, calmly, with one small change {who}. Never a "
                     "new diet.")
    # The only sleep counts the coach may use
    sleep_text = describe_sleep_run(s["sleep_run"])
    if sleep_text:
        lines.append(f"Short sleep: {sleep_text}")
    lines.append(f"Today: {s['logged_today']}.")
    lines.append(f"State: {s['user_state']}.")
    tip = claim_tip(user.user_id, db, today)
    if tip:
        lines.append(f"Tip you may offer, at most once and only if it fits this reply: {tip}")
    # Stored as it's handed over, so it shows on this turn only
    milestone = claim_milestone(user.user_id, db, today)
    if milestone and active_issues:
        lines.append(f"Milestone today: {milestone}. Mention it once, briefly, at the END of "
                     "the reply, after any safety point.")
    elif milestone:
        lines.append(f"Milestone today: {milestone}. Mention it once, briefly.")

    # Fields the bot has already reminded them about today, recorded by
    # log_checkin in nudged_fields. The model must not ask again.
    _LABELS = {"weight_kg": "weight", "sleep_hours": "sleep"}
    asked = sorted({
        _LABELS.get(field, field)
        for c in today_checkins
        for field in (c.nudged_fields or "").split(",")
        if field
    })
    lines.append(f"Fields already reminded about today: {', '.join(asked) if asked else 'nothing'}.")
    # Whether any reply today (the "all set" reply included) asked for a check-in
    lines.append(checkin_request_line(user.user_id, today, db))

    # --- Notes: long-term memory, written by the remember tool -------------- #
    open_notes = (
        db.query(Note)
        .filter(Note.user_id == user.user_id, Note.resolved.is_(False))
        .order_by(Note.created_at.desc(), Note.note_id.desc())
        .all()
    )
    if open_notes:
        lines.append("")
        lines.append("NOTES (newest first, id in brackets)")
        for n in open_notes[:NOTES_SHOWN]:
            lines.append(_note_line(n, today))
    due = [n for n in open_notes if n.follow_up_on and n.follow_up_on <= today]
    if due:
        lines.append("")
        lines.append("FOLLOW-UPS DUE (ask about one naturally, then resolve_note it)")
        for n in sorted(due, key=lambda n: n.follow_up_on):
            lines.append(_note_line(n, today))

    # --- Last 3 days -------------------------------------------------------- #
    if recent:
        lines.append("")
        lines.append("LAST 3 DAYS (older days: call get_history, never assume they weren't logged)")
        for c in recent:
            row = str(c.date)
            if c.weight_kg:   row += f"  {c.weight_kg}kg"
            if c.sleep_hours: row += f"  {c.sleep_hours}h"
            if c.training:    row += f"  {c.training}"
            if c.energy:      row += f"  energy {c.energy}/5"
            if c.food_note:   row += f"  food: {c.food_note}"
            lines.append(row)

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Has a reply today already asked for a check-in?                              #
# Worked out from the replies themselves, so it holds on days with no check-in #
# row to hang nudged_fields on.                                                #
# --------------------------------------------------------------------------- #

_ASK_VERB = re.compile(
    r"\b(send|share|log|drop|post|tell me|let me know|how did you|how'd you|what's your|what is your)\b",
    re.I,
)
_ASK_WHAT = re.compile(r"\b(check[- ]?ins?|weigh[- ]?ins?|weight|sleep|slept|numbers)\b", re.I)


def checkin_asks(text: str) -> int:
    """How many sentences in the text ask them to send check-in data."""
    return sum(1 for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or "")
               if _ASK_VERB.search(sentence) and _ASK_WHAT.search(sentence))


def asks_for_checkin(text: str) -> bool:
    """True if any sentence in the text asks them to send check-in data."""
    return checkin_asks(text) > 0


def checkin_request_line(user_id: int, today: date, db: Session) -> str:
    """The context block's line about asking for a check-in, with its rule.
    Before the first ever check-in, a gentle invitation in each reply is fine;
    after it, at most one ask a day."""
    if db.query(Checkin.checkin_id).filter(Checkin.user_id == user_id).first() is None:
        return ("No check-in yet: one gentle invitation to send their first is fine, "
                "at most one per reply.")
    if _checkin_requested_today(user_id, today, db):
        return ("Already asked today: do not ask for a check-in again, and don't end "
                "with an invitation to log.")
    return "Check-in requested today: no."


def _checkin_requested_today(user_id: int, today: date, db: Session) -> bool:
    # created_at is UTC; local midnight converted to UTC marks the start of today
    start = datetime.combine(today, time.min).astimezone(timezone.utc).replace(tzinfo=None)
    replies = (
        db.query(RawMessage.reply_text)
        .filter(
            RawMessage.user_id == user_id,
            RawMessage.created_at >= start,
            RawMessage.reply_text.isnot(None),
        )
        .all()
    )
    return any(asks_for_checkin(r.reply_text) for r in replies)



# --------------------------------------------------------------------------- #
# Has a reply today already reminded them about an injury?                      #
# Same idea as check-in requests: worked out from today's replies, so the       #
# reminder is given once a day, not in every reply.                             #
# --------------------------------------------------------------------------- #

# Body parts an issue can name. "back" only counts with a word that makes it the
# body part, since "you're back at it" isn't a back reminder.
_BODY_PARTS = ("knee", "shoulder", "hip", "ankle", "wrist", "neck", "elbow", "hamstring", "calf",
               "achilles", "foot", "groin", "quad", "glute", "spine", "rib", "chest", "hand")
_BACK_RE = re.compile(r"\b((lower|upper|mid|your|the|that|his|her|my)\s+back|back\s+(pain|strain|injury|"
                      r"surgery|issue|problem)|back-loading|loads? (the|your) back)\b", re.I)


def issue_body_part(issue_text: str) -> str:
    """The body part an issue is about, for naming its reminder; "injury" if none."""
    if _BACK_RE.search(issue_text) or re.search(r"\bback\b", issue_text, re.I):
        return "back"
    for part in _BODY_PARTS:
        if re.search(rf"\b{part}s?\b", issue_text, re.I):
            return part
    return "injury"


def mentions_issue(reply: str, issue_text: str) -> bool:
    """True if the reply brings up this issue: its body part, or for an issue with
    no body part, the issue's own wording."""
    part = issue_body_part(issue_text)
    if part == "back":
        return bool(_BACK_RE.search(reply or ""))
    if part != "injury":
        return bool(re.search(rf"\b{part}s?\b", reply or "", re.I))
    words = [w for w in re.findall(r"[a-z]{5,}", issue_text.lower())]
    return any(re.search(rf"\b{w}\b", reply or "", re.I) for w in words[:3])


def issue_reminder_line(issue, user_id: int, today: date, db: Session) -> str:
    part = issue_body_part(issue.what)
    label = part.capitalize() if part != "injury" else f'"{issue.what[:40]}"'
    start = datetime.combine(today, time.min).astimezone(timezone.utc).replace(tzinfo=None)
    replies = (db.query(RawMessage.reply_text)
               .filter(RawMessage.user_id == user_id, RawMessage.created_at >= start,
                       RawMessage.reply_text.isnot(None))
               .all())
    if any(mentions_issue(r.reply_text, issue.what) for r in replies):
        return (f"{label} reminder already given today: don't mention it again today, not even "
                "in passing or in a question, unless their message mentions an exercise or pain "
                "that affects it.")
    return f"{label} reminder given today: no."
