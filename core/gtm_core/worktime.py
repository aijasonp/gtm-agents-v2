"""Business-time arithmetic for SLAs and cadences: hours inside a working window, working days."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def add_business_hours(start: datetime, hours: float, tz: str = "UTC", window: tuple[int, int] = (9, 17)) -> datetime:
    """`hours` of working time after `start`, counting only weekday hours inside `window` (local to tz)."""
    z = ZoneInfo(tz)
    t = _aware(start).astimezone(z)
    left = timedelta(hours=max(0.0, float(hours)))
    open_h, close_h = window
    for _ in range(366):
        if t.weekday() >= 5 or t.hour >= close_h:
            t = (t + timedelta(days=1)).replace(hour=open_h, minute=0, second=0, microsecond=0)
            continue
        if t.hour < open_h:
            t = t.replace(hour=open_h, minute=0, second=0, microsecond=0)
        close = t.replace(hour=close_h, minute=0, second=0, microsecond=0)
        if t + left <= close:
            return (t + left).astimezone(timezone.utc)
        left -= close - t
        t = (t + timedelta(days=1)).replace(hour=open_h, minute=0, second=0, microsecond=0)
    return (_aware(start) + timedelta(hours=hours)).astimezone(timezone.utc)  # pragma: no cover


def add_business_days(start: datetime, days: int, tz: str = "UTC", hour: int = 9) -> datetime:
    """The working day `days` after `start` (weekends skipped), at `hour` local time."""
    z = ZoneInfo(tz)
    t = _aware(start).astimezone(z)
    n = 0
    while n < max(0, int(days)):
        t += timedelta(days=1)
        if t.weekday() < 5:
            n += 1
    while t.weekday() >= 5:
        t += timedelta(days=1)
    return t.replace(hour=hour, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def business_days_between(a: datetime, b: datetime) -> int:
    """Whole weekdays from a to b (0 when b is not after a)."""
    a, b = _aware(a), _aware(b)
    if b <= a:
        return 0
    n, d = 0, a.date()
    while d < b.date():
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n
