"""Forecast Prep scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def forecast_prep(ctx, now: datetime | None = None) -> dict:
    """Weekly: AE prep to each rep, the team rollup to the manager channel, snapshot for next week's deltas."""
    eng = _eng(ctx)
    m = eng.manager_prep(ctx, now)
    for r in m["reps"]:
        ctx.slack.post(eng.format_ae(r))
    ctx.slack.post(eng.format_manager(m), channel=ctx.manifest.config.get("manager_channel"))
    eng.snapshot(ctx, m)
    return {"reps": len(m["reps"]), "team_commit": m["team"]["commit"], "suggested_commit": m["suggested_commit"],
            "flags": len(m["flags"]), "top_deals": len(m["top_deals"]), "summary_source": m["summary_source"]}


def forecast_change_alerts(ctx, now: datetime | None = None) -> dict:
    """Daily: deals that entered or left commit, moved amount past the threshold, or slid out of the quarter."""
    eng = _eng(ctx)
    alerts = eng.change_alerts(ctx, now)
    if alerts:
        ctx.slack.post(eng.format_alerts(alerts), channel=ctx.manifest.config.get("manager_channel"))
    return {"alerts": len(alerts)}
