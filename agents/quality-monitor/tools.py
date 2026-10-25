"""Quality Monitor MCP tools. Read only."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def sample_drafts(ctx, days: int = 7, per_agent: int = 5) -> dict:
    """The repeatable sample of recent prospect-facing drafts per agent (every k-th by id)."""
    s = _eng(ctx).sample(ctx, days, per_agent)
    return {"agents": {a: [{"draft_id": d["id"], "kind": d["kind"], "subject": d.get("subject"),
                            "created_at": d["created_at"]} for d in rs] for a, rs in s.items()}}


def quality_report(ctx, days: int = 7) -> dict:
    """Re-scored sample per agent: mean gate score, pass rate, unsourced claims, top failures, worst draft."""
    r = _eng(ctx).report(ctx, days)
    return {"agents": r["agents"], "sampled": r["sampled"]}


def regression_check(ctx) -> dict:
    """Last 7 days vs the prior 28 days per agent, with alerts when score or pass rate drops past the threshold."""
    rows = _eng(ctx).regression(ctx)
    return {"regressions": [r for r in rows if r["alerts"]], "agents": rows}


def draft_scorecard(ctx, draft_id: int) -> dict:
    """Full re-score of one draft: gate checks, failures and unsourced claims."""
    rows = ctx.store.query("SELECT * FROM drafts WHERE id=?", (int(draft_id),))
    if not rows:
        return {"error": f"draft {draft_id} not found"}
    return _eng(ctx).scorecard(ctx, rows[0])


TOOLS = {f.__name__: f for f in [sample_drafts, quality_report, regression_check, draft_scorecard]}
