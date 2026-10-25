"""Stack Audit scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def renewal_watch(ctx, now: datetime | None = None) -> dict:
    """Weekly: alert on tools crossing 120/90/60/30 days before their notice deadline, once per band."""
    eng = _eng(ctx)
    alerts = eng.renewal_alerts(ctx, None, now)
    if alerts:
        ctx.slack.post(eng.format_alerts(alerts))
    return {"alerts": len(alerts), "tools": [a["tool"] for a in alerts]}


def monthly_utilization(ctx, now: datetime | None = None) -> dict:
    """Monthly: utilization and cost per active seat for every tool, plus the current savings total."""
    eng = _eng(ctx)
    s, sc = eng.summary(ctx, None, now), eng.scenarios(ctx, None, now)
    ctx.slack.post(eng.format_utilization(s, sc))
    return {"tools": s["tools"], "spend": s["total_spend"], "low_utilization": len(s["low_utilization"]),
            "possible_savings": sc["total_savings"]}
