"""Revenue Pulse scheduled job (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def weekly_pulse(ctx, now: datetime | None = None) -> dict:
    """Compute the pulse, write the leadership summary, post it, and store this week's snapshot for next week's deltas."""
    eng = load_module(ctx.manifest, "engine")
    p = eng.pulse(ctx, now=now)
    text, source = eng.summary(ctx, p)
    p["adoption"] = eng.adoption(ctx, now=now)
    ctx.slack.post(eng.format_pulse(p, text))
    ctx.store.set_state(eng.STATE_KEY, eng.snapshot(p))
    return {"as_of": p["as_of"], "open_pipeline": p["open_pipeline"], "weighted_pipeline": p["weighted_pipeline"],
            "coverage": p["quarter"]["coverage"], "slipped": p["slipped"]["count"], "stale": p["stale"]["count"],
            "top_risks": [r["name"] for r in p["top_risks"]], "summary_source": source, "wow": p["wow"],
            "adoption": {k: p["adoption"][k] for k in ("adoption", "retention", "win_rate_lift_pts", "small_sample")}}


def daily_gtm_report(ctx, now: datetime | None = None) -> dict:
    """Weekday morning funnel report to Slack. Read only."""
    eng = load_module(ctx.manifest, "engine")
    r = eng.daily(ctx, now)
    ctx.slack.post(eng.format_daily(r))
    return r
