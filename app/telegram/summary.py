"""/summary [days]: check-ins as a fixed-width table to forward to a trainer.
Built in code from daily_history, the same rows get_history gives the coach."""
import html
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.agent.stats import HISTORY_MAX_DAYS, daily_history, weight_change_over
from app.db.models import User

DEFAULT_DAYS = 14
TRAINING_WIDTH = 16
_HEADER = ("Date", "Weight", "Sleep", "Training", "Energy")
_WIDTHS = (6, 6, 5, TRAINING_WIDTH, 6)
# Telegram's limit is 4096; the <pre> tags and HTML escapes need room
_CHUNK = 3500


def parse_days(arg: Optional[str]) -> Optional[int]:
    """None for anything that isn't a number; otherwise clamped to 1..60."""
    if not arg:
        return DEFAULT_DAYS
    if not arg.isdigit():
        return None
    return max(1, min(int(arg), HISTORY_MAX_DAYS))


def _cell(value, width: int) -> str:
    text = "-" if value in (None, "") else str(value)
    if len(text) > width:
        text = text[:width - 1] + "…"
    return text.ljust(width)


def table_rows(rows: list[dict]) -> list[str]:
    """Header, rule and one line per day, unescaped."""
    lines = [" ".join(_cell(h, w) for h, w in zip(_HEADER, _WIDTHS)).rstrip(),
             " ".join("-" * w for w in _WIDTHS)]
    for r in rows:
        cells = (r["date"].strftime("%d %b"),
                 f"{r['weight_kg']:.1f}" if r["weight_kg"] is not None else None,
                 f"{r['sleep_hours']:g}h" if r["sleep_hours"] is not None else None,
                 r["training"],
                 f"{r['energy']}/5" if r["energy"] is not None else None)
        lines.append(" ".join(_cell(c, w) for c, w in zip(cells, _WIDTHS)).rstrip())
    return lines


def format_summary(user: User, db: Session, days: int, today: Optional[date] = None) -> list[str]:
    """Telegram HTML messages (usually one): heading, the table in <pre>, then
    active issues and the weight change over the period."""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    rows = daily_history(user.user_id, db, days, today)
    who = html.escape(user.name or "me")
    heading = (f"<b>Check-ins for {who}, {start:%d %b} to {today:%d %b} ({days} days)</b>\n"
               f"{len(rows)} of {days} days logged.")
    if not rows:
        return [heading + "\nNo check-ins in this period."]

    # The table, split across messages by whole rows if it's long
    table = table_rows(rows)
    header, body = table[:2], table[2:]
    blocks, current = [], []
    for line in body:
        if current and len("\n".join(header + current + [line])) > _CHUNK:
            blocks.append(current)
            current = []
        current.append(line)
    blocks.append(current)
    pres = [f"<pre>{html.escape(chr(10).join(header + b))}</pre>" for b in blocks]

    footer = []
    issues = [i.what for i in user.issues if i.status == "active"]
    footer.append("<b>Active injuries or health issues</b>")
    footer += [f"• {html.escape(i)}" for i in issues] or ["none"]
    change = weight_change_over(rows)
    if change:
        sign = "+" if change["change_kg"] > 0 else ""
        footer.append(f"\n<b>Weight</b>: {change['from_kg']:.1f}kg ({change['from_date']:%d %b}) to "
                      f"{change['to_kg']:.1f}kg ({change['to_date']:%d %b}), "
                      f"{sign}{change['change_kg']:.1f}kg")
    else:
        footer.append("\n<b>Weight</b>: fewer than 2 weigh-ins, no change to show")
    if any(r["training"] and len(r["training"]) > TRAINING_WIDTH for r in rows):
        footer.append("Long training notes are cut short in the table.")

    messages = [heading + "\n" + pres[0]] + pres[1:]
    messages[-1] += "\n\n" + "\n".join(footer)
    return messages
