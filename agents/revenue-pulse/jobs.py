"""Revenue Pulse scheduled job (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def weekly_pulse(ctx, now: datetime | None = None) -> dict:
    """Compute the pulse, write the leadership summary, post it, and store this week's snapshot for next week's deltas."""
    eng = load_module(ctx.manifest, "engine")
    p = eng.pulse(ctx, now=now)
    text, source = eng.summary(ctx, p)
    ctx.slack.post(eng.format_pulse(p, text))
    ctx.store.set_state(eng.STATE_KEY, eng.snapshot(p))
    return {"as_of": p["as_of"], "open_pipeline": p["open_pipeline"], "weighted_pipeline": p["weighted_pipeline"],
            "coverage": p["quarter"]["coverage"], "slipped": p["slipped"]["count"], "stale": p["stale"]["count"],
            "top_risks": [r["name"] for r in p["top_risks"]], "summary_source": source, "wow": p["wow"]}
