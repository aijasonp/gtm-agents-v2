"""Quality Monitor scheduled jobs."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def daily_quality(ctx, now: datetime | None = None) -> dict:
    """Daily: score the sample, store one quality insight per agent, alert Slack on regression."""
    eng = load_module(ctx.manifest, "engine")
    rep = eng.report(ctx, None, now)
    reg = {r["agent"]: r for r in eng.regression(ctx, now)}
    for agent, st in rep["agents"].items():
        r = reg.get(agent, {})
        ctx.store.add_insight(ctx.manifest.id, "quality", agent,
                              {**st, "score_change": r.get("score_change"), "pass_rate_change": r.get("pass_rate_change"),
                               "alerts": r.get("alerts", [])},
                              evidence=f"sample {st['n']} drafts; worst draft {st['worst']}")
    alerts = [r for r in reg.values() if r["alerts"]]
    if alerts:
        ctx.slack.post(eng.format_alert(alerts))
    return {"sampled": rep["sampled"], "agents": len(rep["agents"]), "alerts": len(alerts),
            "regressed": [r["agent"] for r in alerts]}


def weekly_exemplars(ctx, now: datetime | None = None) -> dict:
    """Mondays: rebuild the drafter's few-shot examples from last week's AE approvals and edits."""
    from gtm_core import exemplars
    tools = load_module(ctx.manifest, "tools")
    rep = exemplars.build(ctx.store, None, 8, now=now, **tools._gate_cfg(ctx))
    built = {k: v for k, v in rep.items() if v.get("kept")}
    if built:
        ctx.slack.post("*Drafter examples rebuilt*: " + ", ".join(f"{k} {v['kept']} ({v['version']})" for k, v in built.items()))
    return {"kinds": len(rep), "built": len(built)}
