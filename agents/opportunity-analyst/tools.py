"""Opportunity Analyst tools. Read only: every number comes from the synced CRM data, computed in code."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def find_opportunities(ctx, status: str = "", stage: str = "", owner: str = "", search: str = "", since: str = "",
                       until: str = "", date_field: str = "close_date", min_amount: float = 0, sort: str = "amount",
                       limit: int = 25) -> dict:
    """List opportunities with filters. status: open, won, lost (comma list ok). since/until: ISO date or '90d'.
    date_field: close_date or created_at. sort: amount, close_date, created_at. Returns count, total and up to
    `limit` rows (max 200)."""
    return _eng(ctx).list_opps(ctx, status, stage, owner, search, since, until, date_field, min_amount, sort, limit)


def win_loss(ctx, since: str = "", until: str = "", group_by: str = "") -> dict:
    """Won vs lost deals closed in a window (default last 365 days): counts, amounts, win rate by count and amount,
    average won size, cycle days. group_by: owner, type, lead_source, loss_reason, competitor, industry, segment,
    stage_lost, close_month, close_quarter, or any custom field pulled from the CRM."""
    return _eng(ctx).win_loss(ctx, since, until, group_by)


def loss_analysis(ctx, since: str = "", until: str = "", top: int = 10) -> dict:
    """Lost deals in a window: total, by loss reason, competitor, stage lost at, owner and type, plus the largest
    losses."""
    return _eng(ctx).loss_analysis(ctx, since, until, top)


def open_pipeline(ctx, group_by: str = "stage", owner: str = "") -> dict:
    """Current open pipeline by stage, owner, forecast_category, close_month, type or any field; plus deals whose
    close date has already passed."""
    return _eng(ctx).open_pipeline(ctx, group_by, owner)


def stage_conversion(ctx, since: str = "", until: str = "") -> dict:
    """For deals created in a window: how many reached each stage, moved to the next, won from it, and average days
    spent in each stage (from CRM stage history)."""
    return _eng(ctx).stage_conversion(ctx, since, until)


def pipeline_trend(ctx, periods: int = 6, by: str = "month") -> dict:
    """Created, won and lost counts and amounts, and win rate, per month or quarter for the last N periods."""
    return _eng(ctx).trend(ctx, periods, by)


def opportunity_detail(ctx, deal: str) -> dict:
    """One opportunity by id, Salesforce id or name: every synced field and its stage history."""
    return _eng(ctx).detail(ctx, deal)


def sync_crm(ctx, full: bool = False) -> dict:
    """Pull accounts, contacts, every opportunity and stage history from the CRM now (read only). Incremental
    unless full=true."""
    from gtm_core.sync import sync_all
    return sync_all(ctx, full=full)


TOOLS = {f.__name__: f for f in (find_opportunities, win_loss, loss_analysis, open_pipeline, stage_conversion,
                                 pipeline_trend, opportunity_detail, sync_crm)}
