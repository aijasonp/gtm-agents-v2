"""Quality Monitor MCP tools. Read only, except the exemplar rebuild, which writes the drafter's example set."""
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




def ae_feedback(ctx, days: int = 28) -> dict:
    """What AEs did with each agent's drafts: approved, rejected, sent as written, and how much they rewrote
    (average similarity between the draft and what was approved, 1.0 = unchanged)."""
    from gtm_core import telemetry
    by = telemetry.feedback_summary(ctx.store, int(days))
    worst = sorted((k for k, v in by.items() if v["avg_similarity"] is not None), key=lambda k: by[k]["avg_similarity"])
    return {"days": days, "by_agent_kind": by, "most_rewritten": worst[:5]}


def _gate_cfg(ctx) -> dict:
    from gtm_core import copy_gate
    path = ctx.manifest.config.get("banned_file")
    return {"banned": copy_gate.load_banned(ctx.manifest.path(path) if path else None),
            "max_words": int(ctx.manifest.config.get("exemplar_max_words", 150)),
            "pass_mark": int(ctx.manifest.config.get("pass_mark", 32))}


def build_exemplars(ctx, kind: str = "", per_kind: int = 8) -> dict:
    """Rebuild the drafter's few-shot examples from emails AEs approved, per draft kind: gate-checked, varied,
    versioned. The writer shows the closest 3 to the model on every new draft of that kind."""
    from gtm_core import exemplars
    return exemplars.build(ctx.store, [kind] if kind else None, int(per_kind), **_gate_cfg(ctx))


def edit_patterns(ctx, kind: str = "", min_count: int = 3) -> dict:
    """Words and phrases AEs keep cutting from drafts (seen in at least min_count separate edits)."""
    from gtm_core import exemplars
    return {"kind": kind or "all", "patterns": exemplars.edit_patterns(ctx.store, kind or None, int(min_count))}


def optimize_drafter(ctx, kind: str) -> dict:
    """Optional DSPy pass (GTM_DSPY_MODEL, e.g. anthropic/claude-sonnet-4-5): search approved examples for
    better few-shot demos; they replace the current set only if they score higher on a held-out split."""
    import os
    from gtm_core import exemplars
    model = os.environ.get("GTM_DSPY_MODEL")
    if not model:
        return {"skipped": "set GTM_DSPY_MODEL to a LiteLLM model name to run the DSPy pass"}
    return exemplars.optimize_dspy(ctx.store, kind, model, **_gate_cfg(ctx))


TOOLS = {f.__name__: f for f in [sample_drafts, quality_report, regression_check, draft_scorecard, ae_feedback,
                                 build_exemplars, edit_patterns, optimize_drafter]}
