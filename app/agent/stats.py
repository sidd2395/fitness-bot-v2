"""Shared stats computed by code and handed to the model — never calculated by the AI."""
import re
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.db.models import Checkin, Milestone, Note, Nudge, User


def compute(user_id: int, db: Session, today: date) -> dict:
    checkins = (
        db.query(Checkin)
        .filter(Checkin.user_id == user_id)
        .order_by(Checkin.date.desc())
        .all()
    )
    dates = {c.date for c in checkins}

    # "X of last 14": how often they log. Not a streak.
    last_14 = {today - timedelta(days=i) for i in range(14)}
    days_logged_14 = len(dates & last_14)

    # A streak is consecutive days only, counted back from today (or from
    # yesterday if nothing is logged yet today). Any gap resets it.
    run_end = today if today in dates else today - timedelta(days=1)
    days_in_a_row = 0
    while run_end - timedelta(days=days_in_a_row) in dates:
        days_in_a_row += 1

    # Days since joined
    user = db.get(User, user_id)
    days_since_joined = (today - user.joined_at.date()).days

    # Days since last check-in (excluding today)
    past = sorted((d for d in dates if d < today), reverse=True)
    days_since_last = (today - past[0]).days if past else None


    run = short_sleep_run(checkins, today)
    short_sleep = run["nights_under_6h"] if run else 0

    # What was logged today
    today_types = {c.entry_type for c in checkins if c.date == today}
    if not today_types:
        logged_today = "nothing logged"
    else:
        logged_today = " and ".join(sorted(today_types)) + " logged"

    # User state: heuristic — drives whether to nudge or back off
    last_7 = {today - timedelta(days=i) for i in range(7)}
    days_logged_7 = len(dates & last_7)
    energies = [c.energy for c in checkins if c.energy is not None and c.date in last_7]
    avg_energy = sum(energies) / len(energies) if energies else None
    # Logging rarely only means something once they've had a full week to log;
    # low energy and short sleep count from day one
    struggling = (
        (days_since_joined >= 7 and days_logged_7 <= 2)
        or (avg_energy is not None and avg_energy < 2.5)
        or short_sleep >= 3
    )

    return {
        "days_logged_last_14": days_logged_14,
        "days_in_a_row": days_in_a_row,
        "days_since_joined": days_since_joined,
        "days_since_last_checkin": days_since_last,
        "short_sleep_streak": short_sleep,
        "sleep_run": run,
        "logged_today": logged_today,
        "user_state": "struggling" if struggling else "normal",
    }


def weight_change_since_last(user_id: int, db: Session, on: date) -> Optional[dict]:
    """The weigh-in on this date against the one before it, worked out here so
    the model never does the subtraction. One weight per day, the latest entry.
    None if there's no weigh-in on this date or none before it."""
    rows = (
        db.query(Checkin.date, Checkin.weight_kg)
        .filter(Checkin.user_id == user_id, Checkin.weight_kg.isnot(None), Checkin.date <= on)
        .order_by(Checkin.date, Checkin.checkin_id)
        .all()
    )
    by_day = {d: w for d, w in rows}
    if on not in by_day:
        return None
    earlier = [d for d in by_day if d < on]
    if not earlier:
        return None
    prev = max(earlier)
    change = round(by_day[on] - by_day[prev], 1)
    return {
        "weight_kg": by_day[on],
        "previous_weight_kg": by_day[prev],
        "change_since_last_kg": change,
        "direction": "up" if change > 0 else "down" if change < 0 else "same",
        "days_between": (on - prev).days,
        "in_words": weight_change_words(change, by_day[prev], (on - prev).days),
    }


def weight_change_words(change: float, previous: float, days: int) -> str:
    """The change as a phrase the coach uses as given, so the direction is never
    its own: "up 0.5kg since yesterday's 62.6kg", "down 0.9kg since 95.0kg 4 days ago"."""
    since = f"yesterday's {previous:.1f}kg" if days == 1 else f"{previous:.1f}kg {days} days ago"
    if change == 0:
        return f"the same as {since}"
    return f"{'up' if change > 0 else 'down'} {abs(change):.1f}kg since {since}"


def short_sleep_run(checkins, on: date) -> Optional[dict]:
    """Consecutive nights under 6h and under 5h, ending on the latest night
    logged on or before this date, with the actual hours. Worked out here so the
    model never counts nights itself. One sleep value per day (the latest entry);
    a day with no sleep logged ends the run. None if no sleep is logged."""
    by_day = {}
    for c in sorted(checkins, key=lambda x: (x.date, x.checkin_id or 0)):
        if c.sleep_hours is not None and c.date <= on:
            by_day[c.date] = c.sleep_hours
    if not by_day:
        return None
    day = max(by_day)
    hours = []
    while day in by_day and by_day[day] < 6:
        hours.append(by_day[day])
        day -= timedelta(days=1)
    under_5 = 0
    for h in hours:
        if h >= 5:
            break
        under_5 += 1
    return {
        "last_night_hours": by_day[max(by_day)],
        "last_night_date": max(by_day),
        "nights_under_6h": len(hours),
        "nights_under_5h": under_5,
        "hours_oldest_first": list(reversed(hours)),
    }


def describe_sleep_run(run: Optional[dict]) -> Optional[str]:
    """The one wording of the short-sleep run, shared by the log_checkin result
    and the context block. None when there's no short sleep to report."""
    if not run or run["nights_under_6h"] == 0:
        return None
    hours = ", ".join(f"{h:g}h" for h in run["hours_oldest_first"])
    n6, n5 = run["nights_under_6h"], run["nights_under_5h"]
    if n6 == 1:
        text = f"1 night under 6h ({hours})"
    else:
        text = f"{n6} nights in a row under 6h ({hours}, oldest first)"
    if n5 == 0:
        text += ", none under 5h"
    elif n5 == n6:
        text += ", under 5h" if n6 == 1 else f", all {n5} under 5h"
    else:
        text += f", only the last {n5} under 5h" if n5 > 1 else ", only the last one under 5h"
    return text + "."


# --------------------------------------------------------------------------- #
# Milestones                                                                    #
# Worked out here, never by the model. A check-in milestone only counts if     #
# today's check-in is the one that reached it, so a user who passed it before  #
# milestones existed isn't congratulated late. Each is stored once it's been   #
# handed to the model, so it never fires twice.                               #
# --------------------------------------------------------------------------- #

# In the order they're preferred when several land on the same day
MILESTONES = {
    "first_checkin": "their first check-in",
    "first_kg":      "first 1kg moved toward their goal (3 weigh-in average vs start weight)",
    "streak_7":      "7 days in a row logged",
    "checkin_7":     "their 7th check-in",
    "day_30":        "30 days since joining",
}
# Which way the weight has to move for the first_kg milestone. Other goals have none.
_KG_DIRECTION = {"lose_fat": -1, "build_muscle": 1}
_DAY_30_WINDOW = 7   # day_30 is still mentioned on the first visit up to a week late


def reached_milestones(user_id: int, db: Session, today: date) -> list[str]:
    """Milestones reached today and not yet stored, most preferred first."""
    user = db.get(User, user_id)
    stored = {m.kind for m in user.milestones}
    checkins = (
        db.query(Checkin)
        .filter(Checkin.user_id == user_id, Checkin.date <= today)
        .order_by(Checkin.date, Checkin.checkin_id)
        .all()
    )
    dates = sorted({c.date for c in checkins})
    logged_today = today in dates
    reached = set()

    if logged_today and len(dates) == 1:
        reached.add("first_checkin")
    if logged_today and len(dates) == 7:
        reached.add("checkin_7")
    run = 0
    while today - timedelta(days=run) in dates:
        run += 1
    if run == 7:
        reached.add("streak_7")
    if 30 <= (today - user.joined_at.date()).days < 30 + _DAY_30_WINDOW:
        reached.add("day_30")

    # One weight per day (the latest), averaged over the last 3 weigh-ins so a
    # single water-weight swing can't trigger it. Reached today means today's
    # weigh-in took the average over 1kg when the average before it wasn't.
    direction = _KG_DIRECTION.get(user.profile.goal if user.profile else None)
    start = user.profile.start_weight if user.profile else None
    by_day = {c.date: c.weight_kg for c in checkins if c.weight_kg is not None}
    weights = [by_day[d] for d in sorted(by_day)]
    if direction and start and today in by_day and len(weights) >= 3:
        def moved(ws: list[float]) -> float:
            return direction * (sum(ws[-3:]) / 3 - start)
        before = weights[:-1]
        if moved(weights) >= 1.0 and (len(before) < 3 or moved(before) < 1.0):
            reached.add("first_kg")

    return [k for k in MILESTONES if k in reached and k not in stored]


def claim_milestone(user_id: int, db: Session, today: date) -> Optional[str]:
    """Store every milestone reached today and return the one to mention, if any."""
    kinds = reached_milestones(user_id, db, today)
    if not kinds:
        return None
    for kind in kinds:
        db.add(Milestone(user_id=user_id, kind=kind, reached_on=today))
    db.commit()
    return MILESTONES[kinds[0]]


TRIP_DEFAULT_DAYS = 7
_TRIP_WORDS = re.compile(r"\b(trip|travel\w*|holiday|vacation|flight|flying|abroad|away|tour|getaway|"
                         r"retreat|camp)\b", re.I)


def note_end(starts_on: Optional[date], ends_on: Optional[date], text: str = "",
             kind: Optional[str] = None) -> Optional[date]:
    """The last day of a dated note, the one place this is worked out. ends_on if
    given. With only a start: a trip lasts 7 days, anything else is a one-day
    event. A trip is kind == "trip" once notes have a kind; until then, a note
    whose text reads like one."""
    if ends_on:
        return ends_on
    if not starts_on:
        return None
    is_trip = kind == "trip" if kind else bool(_TRIP_WORDS.search(text or ""))
    return starts_on + timedelta(days=TRIP_DEFAULT_DAYS - 1) if is_trip else starts_on


def note_end_of(note) -> Optional[date]:
    return note_end(note.starts_on, note.ends_on, note.text, getattr(note, "kind", None))


def note_timing(starts_on: Optional[date], ends_on: Optional[date], today: date) -> Optional[str]:
    """Where a dated note stands today, so the model never works it out from the
    text: upcoming in N days, happening now, or ended N days ago. None if undated."""
    if starts_on is None and ends_on is None:
        return None
    start = starts_on or ends_on
    end = ends_on or starts_on

    def days(n: int) -> str:
        return f"{n} day{'s' if n != 1 else ''}"

    if today < start:
        n = (start - today).days
        return "upcoming, starts tomorrow" if n == 1 else f"upcoming, starts in {days(n)}"
    if today <= end:
        if start == end:
            return "today"
        left = (end - today).days
        return "happening now, last day today" if left == 0 else f"happening now, ends in {days(left)}"
    n = (today - end).days
    return "ended yesterday" if n == 1 else f"ended {days(n)} ago"


# --------------------------------------------------------------------------- #
# History: the check-ins in a date range, one row per day. Shared by the        #
# get_history tool and /summary, so both always show the same numbers.          #
# --------------------------------------------------------------------------- #

HISTORY_MAX_DAYS = 60
_DAY_FIELDS = ("weight_kg", "sleep_hours", "energy", "calories", "protein_g", "water_l")


def daily_history(user_id: int, db: Session, days: int, today: date) -> list[dict]:
    """One dict per day with a check-in, oldest first, over the last `days` days
    including today. A day's morning and evening entries are merged: the later
    entry's value wins for each number, training and food notes from both are kept."""
    start = today - timedelta(days=days - 1)
    rows = (db.query(Checkin)
            .filter(Checkin.user_id == user_id, Checkin.date >= start, Checkin.date <= today)
            .order_by(Checkin.date, Checkin.created_at, Checkin.checkin_id)
            .all())
    by_day: dict = {}
    for c in rows:
        day = by_day.setdefault(c.date, {"date": c.date, "training": [], "food_note": [],
                                         **{f: None for f in _DAY_FIELDS}})
        for f in _DAY_FIELDS:
            if getattr(c, f) is not None:
                day[f] = getattr(c, f)
        for text_field in ("training", "food_note"):
            value = getattr(c, text_field)
            if value and value not in day[text_field]:
                day[text_field].append(value)
    out = []
    for d in by_day.values():
        d["training"] = "; ".join(d["training"]) or None
        d["food_note"] = "; ".join(d["food_note"]) or None
        out.append(d)
    return out


def weight_change_over(history: list[dict]) -> Optional[dict]:
    """First and last weigh-in in the rows, and the change between them."""
    weighed = [d for d in history if d["weight_kg"] is not None]
    if len(weighed) < 2:
        return None
    first, last = weighed[0], weighed[-1]
    return {"from_kg": first["weight_kg"], "from_date": first["date"],
            "to_kg": last["weight_kg"], "to_date": last["date"],
            "change_kg": round(last["weight_kg"] - first["weight_kg"], 1)}


# --------------------------------------------------------------------------- #
# 7-day trend and steady weight. A day's weight is its latest weigh-in; a      #
# 7-day average needs at least 3 of them.                                       #
# --------------------------------------------------------------------------- #

TREND_MIN_WEIGH_INS = 3
STEADY_KG = 0.3
_GOAL_DIRECTION = {"lose_fat": -1, "build_muscle": 1}


def seven_day_average(user_id: int, db: Session, end: date) -> Optional[float]:
    """Average of the daily weights in the 7 days ending on `end`, or None with
    fewer than 3 weigh-ins."""
    rows = (db.query(Checkin.date, Checkin.weight_kg)
            .filter(Checkin.user_id == user_id, Checkin.weight_kg.isnot(None),
                    Checkin.date >= end - timedelta(days=6), Checkin.date <= end)
            .order_by(Checkin.date, Checkin.created_at, Checkin.checkin_id)
            .all())
    by_day = {d: w for d, w in rows}
    if len(by_day) < TREND_MIN_WEIGH_INS:
        return None
    return round(sum(by_day.values()) / len(by_day), 1)


def weight_trend(user_id: int, db: Session, today: date, goal: Optional[str]) -> Optional[dict]:
    """This week's 7-day average against the week before, as a phrase to use as
    given, and whether it's moving the way their goal wants."""
    now = seven_day_average(user_id, db, today)
    if now is None:
        return None
    before = seven_day_average(user_id, db, today - timedelta(days=7))
    trend = {"average_kg": now, "previous_average_kg": before, "change_kg": None, "right_way": None}
    if before is None:
        trend["in_words"] = (f"7-day average {now:.1f}kg (too few weigh-ins the week before "
                             "to compare)")
        return trend
    change = round(now - before, 1)
    trend["change_kg"] = change
    if change == 0:
        trend["in_words"] = f"7-day average {now:.1f}kg, the same as the week before"
    else:
        trend["in_words"] = (f"7-day average {now:.1f}kg, {'up' if change > 0 else 'down'} "
                             f"{abs(change):.1f}kg on the week before")
    direction = _GOAL_DIRECTION.get(goal)
    if direction and change:
        trend["right_way"] = (change > 0) == (direction > 0)
    return trend


def steady_weight(user_id: int, db: Session, today: date, goal: Optional[str]) -> Optional[str]:
    """For lose_fat or build_muscle: the 7-day average has stayed within 0.3kg
    over 3 consecutive weeks, each with enough weigh-ins. The averages, oldest
    first, as a phrase; None otherwise."""
    if goal not in _GOAL_DIRECTION:
        return None
    averages = [seven_day_average(user_id, db, today - timedelta(days=7 * k)) for k in (2, 1, 0)]
    if any(a is None for a in averages) or max(averages) - min(averages) >= STEADY_KG:
        return None
    return ("Weight steady for 3 weeks: 7-day averages "
            + ", ".join(f"{a:.1f}kg" for a in averages) + " (oldest first)")


# --------------------------------------------------------------------------- #
# Tips: at most one feature tip every 3 days, each kind once, only when it's    #
# relevant. Recorded when handed to the model, like milestones, so a tip the    #
# model doesn't use still counts and can never nag.                            #
# --------------------------------------------------------------------------- #

TIP_GAP_DAYS = 3
SUMMARY_TIP_CHECKINS = 7
EVENT_TIP_WINDOW_DAYS = 14


def claim_tip(user_id: int, db: Session, today: date) -> Optional[str]:
    user = db.get(User, user_id)
    tips = [n for n in user.nudges if n.kind.startswith("tip:")]
    if any((today - n.shown_on).days < TIP_GAP_DAYS for n in tips):
        return None
    shown = {n.kind for n in tips}

    candidates = []
    upcoming = (db.query(Note)
                .filter(Note.user_id == user_id, Note.resolved.is_(False), Note.starts_on.isnot(None),
                        Note.starts_on > today,
                        Note.starts_on <= today + timedelta(days=EVENT_TIP_WINDOW_DAYS))
                .order_by(Note.starts_on)
                .all())
    for note in upcoming:
        timing = note_timing(note.starts_on, note_end_of(note), today)
        candidates.append((f"tip:event:{note.note_id}",
                           f'"{note.text}" is {timing}. If it fits this reply, offer a short '
                           "before-and-after plan for it."))
    checkins = db.query(Checkin.checkin_id).filter(Checkin.user_id == user_id).count()
    if checkins >= SUMMARY_TIP_CHECKINS and user.summary_used_at is None:
        candidates.append(("tip:summary",
                           f"They've logged {checkins} check-ins and never used /summary. If it "
                           "fits, mention that /summary gives a list they can forward to a trainer."))

    for kind, text in candidates:
        if kind not in shown:
            db.add(Nudge(user_id=user_id, kind=kind, shown_on=today))
            db.commit()
            return text
    return None


def claim_steady_weight(user_id: int, db: Session, today: date, goal: Optional[str]) -> Optional[str]:
    """The steady-weight flag, handed over at most once every 3 weeks."""
    flag = steady_weight(user_id, db, today, goal)
    if flag is None:
        return None
    user = db.get(User, user_id)
    if any(n.kind == "stuck_weight" and (today - n.shown_on).days < 21 for n in user.nudges):
        return None
    db.add(Nudge(user_id=user_id, kind="stuck_weight", shown_on=today))
    db.commit()
    return flag


def lead_with_trend(daily: Optional[dict], trend: Optional[dict], goal: Optional[str]) -> Optional[str]:
    """When today's weight moved against their goal but the 7-day trend is going
    the right way, the instruction to lead with the trend."""
    direction = _GOAL_DIRECTION.get(goal)
    if not (daily and trend and direction and trend.get("right_way")):
        return None
    against = daily["direction"] == ("up" if direction < 0 else "down")
    if not against:
        return None
    return (f"Today's weight is {daily['direction']} but the 7-day trend is going the right way: "
            "lead with the trend, then today's number.")
