"""Whether Coach Bob messages someone first, and why. Pure: facts and a clock in,
a reason (or None) out, no database and no model. Code decides whether to send;
the model only decides what it says.

Rules, checked in order; the first that applies decides:
  1. Reminders off, or paused: skip.
  2. They messaged in the last 3 hours: skip.
  3. A sick note open 2+ days with no sick check-in sent yet: "sick" (morning
     only). Any other open sick note: skip. They're ill; numbers can wait.
  4. Today inside a trip: skip. A trip that ended yesterday: "trip_return"
     (morning only). A trip with no end date counts as 7 days (note_end).
  5. Days since their last message: 3 or 7 is "quiet", 14 is "quiet_last",
     both morning only. Any other day after day 2: skip. After day 14: skip
     until they message.
  6. Morning, nothing logged today: "morning".
  7. Evening, reminders both, no message since 17:00, and the last two
     messages we sent first weren't both left unanswered: "evening".
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

MORNING = "morning"
EVENING = "evening"
SLOT_HOURS = {MORNING: 10, EVENING: 21}   # each slot is that hour, Singapore time
RECENT_MESSAGE = timedelta(hours=3)
SICK_WAIT_DAYS = 2
EVENING_QUIET_FROM = time(17, 0)


@dataclass
class NoteFact:
    note_id: int
    kind: str              # trip | sick | event | other
    start: Optional[date]
    end: Optional[date]    # from stats.note_end, so trips with no end last 7 days


@dataclass
class Facts:
    reminders: str                              # both | morning | off
    paused_until: Optional[date]
    last_message_at: Optional[datetime]         # their own last message, Singapore time
    since: datetime                             # when they joined, if they've never messaged
    logged_today: bool
    open_notes: list = field(default_factory=list)          # NoteFact, unresolved only
    sick_checkins_sent: set = field(default_factory=set)    # note ids we've already asked about
    last_two_unanswered: bool = False


@dataclass
class Plan:
    reason: str
    note_id: Optional[int] = None


def slot_at(now: datetime) -> Optional[str]:
    """The slot this minute falls in, or None. Never late: outside the hour, nothing."""
    for slot, hour in SLOT_HOURS.items():
        if now.hour == hour:
            return slot
    return None


def plan(f: Facts, slot: str, now: datetime) -> Optional[Plan]:
    today = now.date()

    # 1. Off or paused
    if f.reminders == "off" or (slot == EVENING and f.reminders != "both"):
        return None
    if f.paused_until and today <= f.paused_until:
        return None

    # 2. They're talking to us already
    if f.last_message_at and now - f.last_message_at < RECENT_MESSAGE:
        return None

    # 3. Ill: one gentle check after two days, otherwise leave them be
    sick = [n for n in f.open_notes if n.kind == "sick" and n.start]
    if sick:
        due = [n for n in sick if (today - n.start).days >= SICK_WAIT_DAYS
               and n.note_id not in f.sick_checkins_sent]
        if due and slot == MORNING:
            return Plan("sick", due[0].note_id)
        return None

    # 4. Away: quiet during the trip, welcome back the morning after
    trips = [n for n in f.open_notes if n.kind == "trip" and n.start and n.end]
    if any(n.start <= today <= n.end for n in trips):
        return None
    back = [n for n in trips if n.end == today - timedelta(days=1)]
    if back and slot == MORNING:
        return Plan("trip_return", back[0].note_id)

    # 5. Quiet for a while
    last = (f.last_message_at or f.since).date()
    days = (today - last).days
    if days > 2:
        if slot == MORNING and days in (3, 7):
            return Plan("quiet")
        if slot == MORNING and days == 14:
            return Plan("quiet_last")
        return None

    # 6. Morning numbers
    if slot == MORNING:
        return Plan("morning") if not f.logged_today else None

    # 7. How the day went
    since_evening = datetime.combine(today, EVENING_QUIET_FROM)
    if f.last_message_at and f.last_message_at >= since_evening:
        return None
    if f.last_two_unanswered:
        return None
    return Plan("evening")


def next_checkin(f: Facts, now: datetime) -> Optional[datetime]:
    """When we'd next message first, assuming they're messaging now: tonight's
    evening slot or tomorrow morning's, or None. For the context block, so the
    coach only promises a check-in that will happen."""
    talking = Facts(**{**f.__dict__, "last_message_at": now})
    tonight = datetime.combine(now.date(), time(SLOT_HOURS[EVENING], 0))
    if now < tonight and plan(talking, EVENING, tonight):
        return tonight
    tomorrow = datetime.combine(now.date() + timedelta(days=1), time(SLOT_HOURS[MORNING], 0))
    if plan(Facts(**{**talking.__dict__, "logged_today": False}), MORNING, tomorrow):
        return tomorrow
    return None
