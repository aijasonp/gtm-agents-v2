"""Call Coach scheduled jobs (persistent edition). Read only: no CRM writes."""
from __future__ import annotations

from datetime import datetime

from gtm_core import profile
from gtm_core.agents import load_module


def weekly_drills(ctx, now: datetime | None = None) -> dict:
    """Monday: each rep's weakest skills from last month's calls and the roleplay to run this week."""
    eng = load_module(ctx.manifest, "engine")
    days = int(ctx.manifest.config.get("lookback_days", 30))
    lines, plans = ["*Call Coach: drills this week*"], {}
    for rep in profile.rep_names(ctx):
        p = eng.drill_plan(ctx, rep, days, now)
        plans[rep] = p
        if p["drills"]:
            lines.append(f"- {rep} ({p['calls_scored']} calls): " + "; ".join(
                f"{d['skill']} {d['avg_pct']:.0f}% -> run `{d['scenario']}`" for d in p["drills"]))
        elif p["calls_scored"]:
            lines.append(f"- {rep} ({p['calls_scored']} calls): every skill above the bar")
    if len(lines) > 1:
        ctx.slack.post("\n".join(lines))
    return {"reps": len(plans), "with_drills": sum(1 for p in plans.values() if p["drills"]),
            "plans": {k: v["drills"] for k, v in plans.items()}}
