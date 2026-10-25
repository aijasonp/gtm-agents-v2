"""Seller Follow-Up scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.guardrails import StepCounter


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def process_recaps(ctx, now: datetime | None = None) -> dict:
    """Consume `meeting_recap` handoffs from Meeting Intelligence: recap, CRM note and tasks, all queued for approval."""
    eng = _eng(ctx)
    steps = StepCounter(limit=max(ctx.settings.max_loop_steps, 100))

    def handle(h):
        steps.tick(h["ref"])
        mid = h["payload"].get("meeting_id") or h["ref"]
        if eng.has_recap(ctx, mid):
            return {"recap": False, "approvals": 0}
        out = eng.build_recap(ctx, mid, dict(h["payload"]), now)
        return {"recap": True, "approvals": len(out.get("approvals", []))}

    res = ctx.handoffs.process("meeting_recap", handle)
    done = sum(1 for r in res["results"] if r["recap"])
    approvals = sum(r["approvals"] for r in res["results"])
    return {"recaps": done, "approvals_queued": approvals, "failed": res["failed"]}


def daily_digest(ctx, now: datetime | None = None) -> dict:
    """One short Slack message per seller with their top follow-up items. Silent when nothing is due."""
    eng = _eng(ctx)
    per_owner = eng.due_now(ctx, now, mark=True)
    for owner, items in per_owner.items():
        for i in items:
            if i["kind"] == "no_recap" and i.get("meeting_id"):
                out = eng.build_recap(ctx, i["meeting_id"], None, now)
                i["draft_id"] = out.get("draft_id")
        if items:
            ctx.slack.post(eng.format_digest(owner, items))
    return {"owners": len(per_owner), "items": sum(len(v) for v in per_owner.values()),
            "by_kind": {k: sum(1 for v in per_owner.values() for i in v if i["kind"] == k)
                        for k in ("lead_sla", "no_recap", "next_step_late", "task_overdue", "no_next_step", "quiet")}}
