"""Ops Monitor MCP tools. Read-only."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def health_report(ctx) -> dict:
    """Overall runtime health: every check with ok, warn or fail, worst problems first."""
    return _eng(ctx).report(ctx)


def job_status(ctx, agent: str) -> dict:
    """One agent's scheduled jobs: last run, last ok run, consecutive failures and next scheduled run."""
    return _eng(ctx).job_status(ctx, agent)


def stuck_items(ctx) -> dict:
    """Approvals stuck executing or approved but not run, approval backlog, failed or waiting handoffs, stuck runs."""
    return _eng(ctx).stuck(ctx)


def spend_report(ctx, days: int = 7) -> dict:
    """Token use and spend per agent per day for the last N days, against each agent's daily token budget."""
    eng = _eng(ctx)
    rows = eng.spend(ctx, eng.manifests_for(ctx), max(1, int(days)))
    return {"days": int(days), "rows": rows, "total_usd": round(sum(r["usd"] for r in rows), 4),
            "total_tokens": sum(r["tokens"] for r in rows)}


TOOLS = {f.__name__: f for f in [health_report, job_status, stuck_items, spend_report]}
