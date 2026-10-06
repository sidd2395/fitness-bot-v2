"""/summary [days]: check-ins as a short list to forward to a trainer. Built in
code from daily_history, the same rows get_history gives the coach. Every line
is at most 30 characters so it reads on a phone without wrapping."""
import textwrap
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.agent.stats import HISTORY_MAX_DAYS, daily_history, weight_change_over
from app.db.models import User

DEFAULT_DAYS = 14
LINE_WIDTH = 30
INDENT = "  "


def parse_days(arg: Optional[str]) -> Optional[int]:
    """None for anything that isn't a number; otherwise clamped to 1..60."""
    if not arg:
        return DEFAULT_DAYS
    if not arg.isdigit():
        return None
    return max(1, min(int(arg), HISTORY_MAX_DAYS))


def _day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"            # Thu 2 Oct


def _wrap(text: str, indent: str = "") -> list[str]:
    return textwrap.wrap(text, width=LINE_WIDTH, initial_indent=indent, subsequent_indent=indent,
                         break_long_words=True, break_on_hyphens=False) or [indent.rstrip()]


def day_lines(row: dict) -> list[str]:
    """ "Thu 2 Oct  95.0kg · 8h sleep", then training, energy and food on indented
    lines. Empty fields are left out."""
    numbers = []
    if row["weight_kg"] is not None:
        numbers.append(f"{row['weight_kg']:.1f}kg")
    if row["sleep_hours"] is not None:
        numbers.append(f"{row['sleep_hours']:g}h sleep")
    first = _day(row["date"])
    if numbers:
        joined = f"{first}  {' · '.join(numbers)}"
        lines = [joined] if len(joined) <= LINE_WIDTH else [first] + _wrap(" · ".join(numbers), INDENT)
    else:
        lines = [first]
    extras = []
    if row["training"]:
        extras.append(row["training"])
    if row["energy"] is not None:
        extras.append(f"energy {row['energy']}/5")
    food = [f"{row['calories']} kcal" if row["calories"] is not None else None,
            f"{row['protein_g']:g}g protein" if row["protein_g"] is not None else None,
            f"{row['water_l']:g}L water" if row["water_l"] is not None else None,
            f"food: {row['food_note']}" if row["food_note"] else None]
    extras += [f for f in food if f]
    for extra in extras:
        lines += _wrap(extra, INDENT)
    return lines


def format_summary(user: User, db: Session, days: int, today: Optional[date] = None) -> list[str]:
    """Plain-text message parts: heading, one block per logged day, then active
    issues and the weight change over the period."""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    rows = daily_history(user.user_id, db, days, today)
    lines = _wrap(f"Check-ins for {user.name or 'me'}")
    lines += _wrap(f"{_day(start)} to {_day(today)}")
    lines += _wrap(f"{len(rows)} of {days} days logged")
    if not rows:
        return ["\n".join(lines)]

    for r in rows:
        lines.append("")
        lines += day_lines(r)

    lines += ["", "Injuries / health issues"]
    issues = [i.what for i in user.issues if i.status == "active"]
    for issue in issues:
        lines += textwrap.wrap(issue, width=LINE_WIDTH, initial_indent="• ", subsequent_indent=INDENT)
    if not issues:
        lines.append("none")

    change = weight_change_over(rows)
    lines.append("")
    if change:
        sign = "+" if change["change_kg"] > 0 else ""
        lines += _wrap(f"Weight {change['from_kg']:.1f}kg to {change['to_kg']:.1f}kg "
                       f"({_day(change['from_date'])} to {_day(change['to_date'])}): "
                       f"{sign}{change['change_kg']:.1f}kg")
    else:
        lines += _wrap("Weight: fewer than 2 weigh-ins, so no change to show")
    return ["\n".join(lines)]
