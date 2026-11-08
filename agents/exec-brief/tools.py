"""Exec Brief MCP tools. Every number is computed from warehouse rows; nothing is estimated."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def exec_metrics(ctx, role: str = "") -> dict:
    """Today's metrics. With role (ceo, cso, cmo, channel) only that executive's five; otherwise all of them,
    each with value, target, pace, change since the last run and status (good, watch, bad)."""
    eng = _eng(ctx)
    cfg = eng.config(ctx)
    c = eng.compute(eng.load_rows(ctx, cfg), cfg, ctx.store.get_state(eng.STATE_KEY) or {})
    ms = eng.brief_metrics(c, cfg, role) if role else list(c["metrics"].values())
    return {"as_of": c["as_of"], "metrics": [{k: m[k] for k in ("key", "label", "dept", "display", "value", "target",
                                                                "paced", "delta", "status", "detail", "items")}
                                             for m in ms]}


def exec_brief_preview(ctx, role: str = "ceo") -> dict:
    """The json-render card spec and Slack text for one executive's brief, without sending anything."""
    r = _eng(ctx).run(ctx, roles=(role,), company=False, dry_run=True)
    s = r["sent"][role]
    return {"read": s["read"], "spec": s["spec"], "metrics": s["metrics"]}


def company_snapshot(ctx) -> dict:
    """Best and worst number for each team (Sales, Marketing, Partners, Customer Success), without sending."""
    eng = _eng(ctx)
    cfg = eng.config(ctx)
    c = eng.compute(eng.load_rows(ctx, cfg), cfg, ctx.store.get_state(eng.STATE_KEY) or {})
    return {"as_of": c["as_of"], "teams": [
        {"team": r["name"], "best": r["best"] and f"{r['best']['label']}: {eng.metric_line(r['best'])}",
         "worst": r["worst"] and f"{r['worst']['label']}: {eng.metric_line(r['worst'])}"}
        for r in eng.department_extremes(c, cfg)]}


def command_center(ctx, weeks: int = 8) -> dict:
    """Week-over-week heat map of every metric by team for the last N weeks, as a grid (and the page path once
    the daily job has written it)."""
    eng = _eng(ctx)
    cc = load_module(ctx.manifest, "command_center")
    cfg = eng.config(ctx)
    rows = eng.load_rows(ctx, cfg)
    today = eng.compute(rows, cfg, ctx.store.get_state(eng.STATE_KEY) or {})
    from datetime import datetime
    g = cc.grid(eng, rows, cfg, ctx.store.get_state(cc.HISTORY_KEY) or {}, datetime.fromisoformat(today["as_of"]),
                weeks=weeks, today=today)
    from pathlib import Path
    p = Path(ctx.settings.data_dir) / "exec_brief" / "command-center.html"
    return {"weeks": g["weeks"], "metrics": g["metrics"], "page": str(p) if p.exists() else None}


TOOLS = {f.__name__: f for f in (exec_metrics, exec_brief_preview, company_snapshot, command_center)}
