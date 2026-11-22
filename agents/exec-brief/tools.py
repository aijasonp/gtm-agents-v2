"""Exec Brief tools. Read only; every number is computed in code."""
from __future__ import annotations

from gtm_core.agents import load_module
from gtm_core.connectors.snowflake import get_warehouse


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def exec_brief(ctx, role: str) -> dict:
    """The five metrics for one leader (ceo, cmo, cso, channel or any role in config), each with week-over-week
    change and whether it moved the good or bad way."""
    eng = _eng(ctx)
    b = eng.role_brief(ctx, role.lower(), warehouse=get_warehouse())
    return b if "error" in b else {**b, "text": eng.format_role(b)}


def company_snapshot(ctx) -> dict:
    """One good and one bad number per department (sales, marketing, partners, customer success), picked by
    week-over-week movement."""
    eng = _eng(ctx)
    s = eng.company_snapshot(ctx, warehouse=get_warehouse())
    return {"departments": s, "text": eng.format_snapshot(s)}


def command_center(ctx, weeks: int = 5) -> dict:
    """Heat map of the leadership metrics, same weekday for the last N weeks, each week judged against the one before."""
    eng = _eng(ctx)
    h = eng.heat_map(ctx, weeks=max(2, min(int(weeks), 12)))
    return {**h, "text": eng.format_heat(h)}


def leadership_metric(ctx, names: list) -> dict:
    """Current value, last week and direction for named metrics from config/exec_brief.yaml."""
    return {"metrics": _eng(ctx).compute(ctx, [str(n) for n in names], warehouse=get_warehouse())}


def list_leadership_metrics(ctx) -> dict:
    """Every metric the exec briefs can use, its source and whether it is configured."""
    cfg = _eng(ctx).config(ctx)
    return {"metrics": [{"name": k, "label": v.get("label"), "source": v.get("source"),
                         "configured": v.get("source") == "crm" or bool((v.get("sql") or "").strip())}
                        for k, v in (cfg.get("metrics") or {}).items()],
            "roles": {k: v.get("metrics") for k, v in (cfg.get("roles") or {}).items()}}


TOOLS = {f.__name__: f for f in (exec_brief, company_snapshot, command_center, leadership_metric,
                                 list_leadership_metrics)}
