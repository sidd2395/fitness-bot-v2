"""Singapore time, where every user is for now. Fixed +8, no daylight saving."""
from datetime import datetime, timedelta, timezone
from typing import Optional

SINGAPORE = timezone(timedelta(hours=8))


def now_local() -> datetime:
    """Current Singapore time, naive. Tests replace this to set the time of day."""
    return datetime.now(SINGAPORE).replace(tzinfo=None)


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def day_start_utc(now: Optional[datetime] = None) -> datetime:
    """Midnight Singapore time today, as naive UTC like the created_at columns."""
    now = now or datetime.now(timezone.utc)
    midnight = now.astimezone(SINGAPORE).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)
