"""Daily Book scheduled jobs. Runs after Signal Sourcing (5:00) and Signal Scout (6:00), before Rep Brief (7:30)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def daily_books(ctx, now: datetime | None = None) -> dict:
    """Weekdays 6:45: a full book per AE, cold first touches drafted for approval, shortfalls reported."""
    from gtm_core.executors import register_core_executors
    register_core_executors(ctx)
    eng = load_module(ctx.manifest, "engine")
    stats = {"books": 0, "rows": 0, "shortfall": 0, "drafted": 0}
    for o in eng.owners(ctx):
        b = eng.build(ctx, o["name"], now)
        d = eng.predraft(ctx, b, now)
        stats["books"] += 1
        stats["rows"] += b["filled"]
        stats["shortfall"] += b["shortfall"]
        stats["drafted"] += d["queued"]
        ctx.slack.post(eng.format_book(b))
        if b["shortfall"]:
            ctx.audit.log("daily_book.shortfall", owner=o["name"], short=b["shortfall"], pools=b["pools"])
    return stats
