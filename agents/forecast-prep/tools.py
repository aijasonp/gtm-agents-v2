"""Forecast Prep MCP tools. Nothing here writes to the CRM; forecast calls are stored locally."""
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


def submit_forecast_call(ctx, owner: str, commit: float, best_case: float | None = None, notes: str = "",
                         deal_ids: list[str] | None = None) -> dict:
    """Record what a rep called this quarter (commit, optional best case, notes, the deals in it), saved next to
    the system's suggested commit at that moment. Local record; nothing goes to the CRM."""
    try:
        return _eng(ctx).submit_call(ctx, owner, commit, best_case, notes, deal_ids)
    except ValueError as e:
        return {"error": str(e)}


def forecast_call_history(ctx, owner: str = "", period: str = "") -> dict:
    """Every submitted call (optionally one rep or one quarter like Q4 2026), plus call accuracy on closed quarters."""
    eng = _eng(ctx)
    return {"calls": eng.calls(ctx, period, owner), "accuracy": eng.accuracy(ctx, owner)}


def board_forecast(ctx) -> dict:
    """Board view: won to date and a low, call and high range (suggested commit, rep calls scaled by each rep's
    past accuracy, and best case), attainment percents, reps with no call, and next quarter pipeline."""
    b = _eng(ctx).board_forecast(ctx)
    return {**b, "text": _eng(ctx).format_board(b)}


TOOLS = {f.__name__: f for f in [ae_prep, manager_prep, exec_prep, forecast_changes, call_agenda,
                                 submit_forecast_call, forecast_call_history, board_forecast]}
