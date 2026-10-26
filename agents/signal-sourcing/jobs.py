"""Signal Sourcing scheduled jobs. Runs before Signal Scout's 6:00 sweep so new signals are scored the same day."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def daily_scan(ctx, now: datetime | None = None) -> dict:
    """Scan due accounts, then post the dispatch batch."""
    eng = _eng(ctx)
    res = eng.scan_due(ctx, now)
    batch = eng.dispatch(ctx, now)
    if res["scanned"] or batch["count"]:
        ctx.slack.post(f"*Signal Sourcing*: scanned {res['scanned']} accounts, {res['stored']} new signals.\n"
                       + eng.format_dispatch(batch))
    return {"scanned": res["scanned"], "stored": res["stored"], "with_signals": res["with_signals"],
            "dispatch": batch["count"], "rejected": len(res["rejected"])}


def weekly_discovery(ctx, now: datetime | None = None) -> dict:
    """Find new companies from SEC full-text search and post the candidates for review. Adds nothing."""
    res = _eng(ctx).discover(ctx, now)
    if res.get("candidates"):
        top = res["candidates"][:15]
        ctx.slack.post(f"*Signal Sourcing discovery*: {res['count']} new companies in recent filings\n" + "\n".join(
            f"- {c['name']}" + (f" ({c['ticker']})" if c["ticker"] else "") + f": {', '.join(c['phrases'])}" for c in top)
            + "\n_Add with add_company (needs the domain) or push to Clay._")
    return {"candidates": res.get("count", 0)}
