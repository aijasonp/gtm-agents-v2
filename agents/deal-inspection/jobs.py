"""Deal Inspection scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.guardrails import StepCounter
from gtm_core.sync import sync_all


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def sync_deals(ctx) -> dict:
    """Read accounts, contacts and deals from the CRM into the local store (read-only)."""
    return sync_all(ctx)


def apply_evidence(ctx) -> dict:
    """Consume MEDDPICC evidence handed off by Meeting Intelligence."""
    eng = _eng(ctx)
    steps = StepCounter(limit=max(ctx.settings.max_loop_steps, 200))

    def handle(h):
        steps.tick(str(h["id"]))
        return eng.apply_evidence(ctx, h)

    out = ctx.handoffs.process("meddpicc_evidence", handle)
    results = out["results"]
    return {"handoffs": len(results), "failed": out["failed"], "deals_updated": sum(1 for r in results if r.get("changed")),
            "approvals_queued": sum(1 for r in results if r.get("approval")), "results": results}


def weekly_inspection(ctx, now: datetime | None = None) -> dict:
    """Apply pending call evidence, inspect every open deal, store results, post the report."""
    ev = apply_evidence(ctx)
    eng = _eng(ctx)
    res = eng.inspect_all(ctx, now=now)
    ctx.slack.post(eng.format_report(res, int(ctx.manifest.config.get("report_size", 25))))
    recs = {k: sum(1 for i in res if i["recommendation"] == k) for k in ("progress", "fix", "disqualify")}
    return {"deals": len(res), "recommendations": recs, "evidence_applied": ev["deals_updated"],
            "worst": [{"deal": i["name"], "risk": i["risk"], "recommendation": i["recommendation"]} for i in res[:5]]}
