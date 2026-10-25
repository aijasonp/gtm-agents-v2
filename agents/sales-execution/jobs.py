"""Sales Execution scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.guardrails import StepCounter


def precall_briefs(ctx, now: datetime | None = None) -> dict:
    """Brief every meeting starting in the next 48 hours that has not been briefed yet; post to Slack."""
    eng = load_module(ctx.manifest, "engine")
    done = {i["key"] for i in ctx.store.insights("precall_brief")}
    briefs = []
    with StepCounter(limit=max(ctx.settings.max_loop_steps, 100)) as steps:
        for m in eng.upcoming(ctx, now):
            if m["id"] in done:
                continue
            steps.tick(m["id"])
            b = eng.brief_with_plan(ctx, meeting=m, now=now)
            ctx.store.add_insight(ctx.manifest.id, "precall_brief", m["id"],
                                  {k: v for k, v in b.items() if k != "text"}, b["text"],
                                  account_id=m.get("account_id"), deal_id=m.get("deal_id"), meeting_id=m["id"])
            briefs.append(b)
    for b in briefs:
        ctx.slack.post(b["text"])
    return {"briefed": len(briefs), "meetings": [b["meeting_id"] for b in briefs],
            "gaps_total": sum(len(b["meddpicc_gaps"]) for b in briefs)}
