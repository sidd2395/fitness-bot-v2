"""Shared stats computed by code and handed to the model — never calculated by the AI."""
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.db.models import Checkin, User


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
