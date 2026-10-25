"""Deal timing and pipeline math shared by Deal Inspection, Seller Follow-Up and Revenue Pulse.

All dates are ISO strings. `now` is injectable so evals are reproducible.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

OPEN = "open"
DEFAULT_STAGE_PROBABILITY = {"discovery": 0.1, "qualification": 0.2, "evaluation": 0.4, "proposal": 0.6,
                             "negotiation": 0.8, "commit": 0.9}


def parse_dt(v) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    if isinstance(v, (int, float)) or str(v).strip().isdigit():  # epoch seconds or milliseconds
        n = float(v)
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, tz=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y"):
            try:
                d = datetime.strptime(s[:12].strip(), fmt) if fmt != "%Y-%m-%d" else datetime.fromisoformat(s[:10])
                break
            except ValueError:
                continue
        if d is None:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def days_since(v, now: datetime | None = None) -> int | None:
    d = parse_dt(v)
    if d is None:
        return None
    return ((now or datetime.now(timezone.utc)) - d).days


def days_until(v, now: datetime | None = None) -> int | None:
    d = parse_dt(v)
    if d is None:
        return None
    return (d - (now or datetime.now(timezone.utc))).days


def is_open(deal: dict) -> bool:
    st = (deal.get("status") or OPEN).lower()
    stage = (deal.get("stage") or "").lower()
    return st == OPEN and "closed" not in stage and stage not in ("won", "lost")


def is_won(deal: dict) -> bool:
    return (deal.get("status") or "").lower() == "won" or "won" in (deal.get("stage") or "").lower()


def is_lost(deal: dict) -> bool:
    return (deal.get("status") or "").lower() == "lost" or "lost" in (deal.get("stage") or "").lower()


def slips(history: list[dict]) -> int:
    """How many times the close date moved later across snapshots."""
    n, prev = 0, None
    for h in history:
        cd = parse_dt(h.get("close_date"))
        if prev and cd and cd > prev:
            n += 1
        if cd:
            prev = cd
    return n


def stage_changes(history: list[dict]) -> list[tuple[str, str, str]]:
    out, prev = [], None
    for h in history:
        if prev is not None and h.get("stage") != prev:
            out.append((prev, h.get("stage"), h.get("snapshot_at")))
        prev = h.get("stage")
    return out


def weighted(deals: list[dict], probabilities: dict[str, float] | None = None, stage_key=None) -> float:
    p = probabilities or DEFAULT_STAGE_PROBABILITY
    total = 0.0
    for d in deals:
        if not is_open(d):
            continue
        key = stage_key(d.get("stage")) if stage_key else (d.get("stage") or "").lower()
        total += float(d.get("amount") or 0) * p.get(key, 0.1)
    return round(total, 2)


def in_period(v, start: datetime, end: datetime) -> bool:
    d = parse_dt(v)
    return bool(d and start <= d < end)
