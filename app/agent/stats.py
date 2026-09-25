"""Shared stats computed by code and handed to the model — never calculated by the AI."""
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.db.models import Checkin, Milestone, User


def compute(user_id: int, db: Session, today: date) -> dict:
    checkins = (
        db.query(Checkin)
        .filter(Checkin.user_id == user_id)
        .order_by(Checkin.date.desc())
        .all()
    )
    dates = {c.date for c in checkins}

    # "X of last 14" — participation rate, matching spec context-block format
    last_14 = {today - timedelta(days=i) for i in range(14)}
    streak = len(dates & last_14)

    # Days since joined
    user = db.get(User, user_id)
    days_since_joined = (today - user.joined_at.date()).days

    # Days since last check-in (excluding today)
    past = sorted((d for d in dates if d < today), reverse=True)
    days_since_last = (today - past[0]).days if past else None

    # Weight change over 7 days
    weight_change_7d = None
    weights = sorted(
        [(c.date, c.weight_kg) for c in checkins if c.weight_kg is not None],
        key=lambda x: x[0],
    )
    if len(weights) >= 2:
        latest_w = weights[-1][1]
        week_ago = today - timedelta(days=7)
        older = [w for dt, w in weights if dt <= week_ago]
        if older:
            weight_change_7d = round(latest_w - older[-1], 2)

    # Consecutive short-sleep nights (< 6 h), counting from most recent
    short_sleep = 0
    for c in sorted(checkins, key=lambda x: x.date, reverse=True):
        if c.sleep_hours is None:
            continue
        if c.sleep_hours < 6:
            short_sleep += 1
        else:
            break

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
    struggling = (
        days_logged_7 <= 2
        or (avg_energy is not None and avg_energy < 2.5)
        or short_sleep >= 3
    )

    return {
        "streak": streak,
        "days_since_joined": days_since_joined,
        "days_since_last_checkin": days_since_last,
        "weight_change_7d": weight_change_7d,
        "short_sleep_streak": short_sleep,
        "logged_today": logged_today,
        "user_state": "struggling" if struggling else "normal",
    }


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
