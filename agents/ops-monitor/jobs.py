"""Ops Monitor scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def health_check(ctx, now: datetime | None = None) -> dict:
    """Every 15 minutes: run all checks; post to Slack only on new problems, status changes or recoveries."""
    eng = _eng(ctx)
    rep = eng.report(ctx, now)
    ch = eng.changes(ctx, rep)
    if ch["new"] or ch["recovered"]:
        ctx.slack.post(eng.format_alert(ch), channel=ctx.manifest.config.get("alert_channel") or None)
    return {"status": rep["status"], "counts": rep["counts"], "new_problems": len(ch["new"]), "recovered": len(ch["recovered"])}


def daily_ops_summary(ctx, now: datetime | None = None) -> dict:
    """Weekdays: one summary of every non-ok check and the run counts for the last 24 hours."""
    eng = _eng(ctx)
    rep = eng.report(ctx, now)
    runs = eng.run_counts(ctx, eng._now(now))
    ctx.slack.post(eng.format_summary(rep, runs), channel=ctx.manifest.config.get("alert_channel") or None)
    return {"status": rep["status"], "counts": rep["counts"], "runs_24h": runs}
