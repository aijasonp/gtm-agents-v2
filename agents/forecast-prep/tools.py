"""Forecast Prep MCP tools. Read-only: nothing here writes to the CRM."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def ae_prep(ctx, owner: str) -> dict:
    """One rep's forecast prep: quarter and month totals, changes, commit deals with risk and questions, suggested commit."""
    p = _eng(ctx).ae_prep(ctx, owner)
    return {**p, "text": _eng(ctx).format_ae(p)}


def manager_prep(ctx) -> dict:
    """Team rollup vs quota: per-rep commit vs suggested, variance flags, top deals to inspect, deals slipped twice."""
    p = _eng(ctx).manager_prep(ctx)
    return {**p, "text": _eng(ctx).format_manager(p)}


def exec_prep(ctx) -> dict:
    """Quarter view for leaders: attainment vs linear pace, week-over-week movement, biggest swings, top risks."""
    p = _eng(ctx).exec_prep(ctx)
    return {**p, "text": _eng(ctx).format_exec(p)}


def forecast_changes(ctx, days: int = 7, owner: str = "") -> dict:
    """Deals that changed category, amount, close date or stage (or were created or closed) in the last N days."""
    rows = _eng(ctx).changes(ctx, owner, int(days))
    return {"count": len(rows), "changes": rows}


def call_agenda(ctx, level: str = "manager", owner: str = "") -> dict:
    """Time-boxed agenda for the forecast call. level: ae (needs owner), manager or exec."""
    if level == "ae" and not owner:
        return {"error": "owner is required for an AE agenda"}
    return _eng(ctx).agenda(ctx, level, owner)


TOOLS = {f.__name__: f for f in [ae_prep, manager_prep, exec_prep, forecast_changes, call_agenda]}
