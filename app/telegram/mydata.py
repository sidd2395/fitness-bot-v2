"""/mydata: everything we hold about a user, readable, built in code."""
from typing import Optional

from sqlalchemy.orm import Session

from app.agent.tools import ONBOARDING_STEPS
from app.db.models import Checkin, RawMessage, User

CHECKINS_SHOWN = 30
_GOALS = {"lose_fat": "lose fat", "build_muscle": "build muscle", "perform": "perform better",
          "feel_better": "feel better"}
_SEX = {"M": "male", "F": "female"}
_MILESTONES = {"first_checkin": "first check-in", "first_kg": "first 1kg toward your goal",
               "streak_7": "7 days in a row", "checkin_7": "7th check-in", "day_30": "30 days in"}


def _val(value, unit: str = "") -> str:
    if value is None or value == "":
        return "not set"
    if isinstance(value, float):
        value = f"{value:g}"
    return f"{value}{unit}"


def _checkin_line(c: Checkin) -> str:
    bits = []
    if c.weight_kg is not None:
        bits.append(f"{c.weight_kg:g}kg")
    if c.sleep_hours is not None:
        bits.append(f"slept {c.sleep_hours:g}h")
    if c.training:
        bits.append(c.training)
    if c.energy is not None:
        bits.append(f"energy {c.energy}")
    if c.calories is not None:
        bits.append(f"{c.calories} kcal")
    if c.protein_g is not None:
        bits.append(f"{c.protein_g:g}g protein")
    if c.water_l is not None:
        bits.append(f"{c.water_l:g}L water")
    return f"- {c.date} {c.entry_type}: {', '.join(bits) or 'no numbers'}"


def _note_dates(n) -> str:
    bits = []
    if n.starts_on or n.ends_on:
        start, end = n.starts_on or n.ends_on, n.ends_on or n.starts_on
        bits.append(str(start) if start == end else f"{start} to {end}")
    if n.follow_up_on:
        bits.append(f"follow up {n.follow_up_on}")
    return f" ({', '.join(bits)})" if bits else ""


def format_mydata(user: Optional[User], db: Session) -> str:
    if user is None:
        return "I don't hold anything about you."
    p = user.profile
    lines = ["Here's everything I hold about you.", "", "Account",
             f"Telegram chat ID: {user.telegram_chat_id}",
             f"Joined: {user.joined_at:%Y-%m-%d}",
             f"Consent given: {user.consent_given_at:%Y-%m-%d %H:%M} UTC" if user.consent_given_at
             else "Consent given: no"]
    if user.blocked:
        lines.append("Blocked: yes (under 18). Nothing else is kept.")
    else:
        step = user.onboarding_step
        lines.append("Setup: complete" if step >= ONBOARDING_STEPS
                     else f"Setup: {step} of {ONBOARDING_STEPS} questions answered")

    lines += ["", "Profile",
              f"Name: {_val(user.name)}",
              f"Age: {_val(user.age)}",
              f"Sex: {_val(_SEX.get(user.sex))}",
              f"Goal: {_val(_GOALS.get(p.goal, p.goal) if p else None)}",
              f"Starting weight: {_val(p.start_weight if p else None, 'kg')}",
              f"Calorie target: {_val(p.calorie_target if p else None, ' kcal')}",
              f"Protein target: {_val(p.protein_target_g if p else None, 'g')}",
              f"Water target: {_val(p.water_target_l if p else None, 'L')}",
              f"Targets set by: {_val({'user': 'you', 'coach': 'your coach'}.get(p.targets_set_by) if p else None)}",
              f"Coach or trainer: {_val(user.trainer_name)}",
              f"Sports: {_val(p.disciplines if p else None)}",
              f"Why you started: {_val(p.motivation if p else None)}"]

    lines += ["", "Injuries and health issues"]
    lines += [f"- {i.what} ({i.status}, since {i.first_mentioned:%Y-%m-%d})" for i in user.issues] or ["none"]

    checkins = (db.query(Checkin).filter(Checkin.user_id == user.user_id)
                .order_by(Checkin.date.desc(), Checkin.checkin_id.desc())
                .limit(CHECKINS_SHOWN).all())
    total = db.query(Checkin).filter(Checkin.user_id == user.user_id).count()
    heading = f"Check-ins (latest {len(checkins)} of {total})" if total > CHECKINS_SHOWN else "Check-ins"
    lines += ["", heading]
    lines += [_checkin_line(c) for c in checkins] or ["none"]

    notes = [n for n in user.notes if not n.resolved]
    lines += ["", "Notes I keep about you"]
    lines += [f"- {n.text}" + _note_dates(n) for n in sorted(notes, key=lambda n: n.created_at)] or ["none"]
    resolved = len(user.notes) - len(notes)
    if resolved:
        lines.append(f"Plus {resolved} older note{'s' if resolved != 1 else ''} already dealt with.")

    lines += ["", "Milestones"]
    lines += [f"- {_MILESTONES.get(m.kind, m.kind.replace('_', ' '))}, {m.reached_on}"
              for m in sorted(user.milestones, key=lambda m: m.reached_on)] or ["none"]

    messages = db.query(RawMessage).filter(RawMessage.user_id == user.user_id).count()
    lines += ["", f"I also keep your messages and my replies ({messages} so far), so I "
                  "remember what we talked about.", "", "/delete erases all of it."]
    return "\n".join(lines)
