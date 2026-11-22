"""Exec Brief engine: leadership metrics, week over week, computed in code.

CRM metrics come from the synced deals; warehouse metrics from named read-only Snowflake queries in
config/exec_brief.yaml. A daily snapshot of every value is stored so stock metrics (open pipeline, past due)
can be compared with the same day last week.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import yaml

from gtm_core import pipeline

SNAP_KEY = "exec_brief:snapshots"
KEEP_DAYS = 60
FLOW = {"new_pipeline_7d", "new_opps_7d", "won_7d", "lost_7d", "win_rate_90d", "avg_cycle_days_90d"}


def config(ctx) -> dict:
    p = ctx.manifest.path(ctx.manifest.config["brief"])
    return yaml.safe_load(p.read_text()) or {}


def _amt(d):
    try:
        return float(d.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _dt(v):
    return pipeline.parse_dt(v)


def _status(d):
    return "won" if pipeline.is_won(d) else "lost" if pipeline.is_lost(d) else "open" if pipeline.is_open(d) else "other"


def _in(v, a, b):
    t = _dt(v)
    return bool(t and a <= t < b)


def _quarter_start(t):
    return datetime(t.year, (t.month - 1) // 3 * 3 + 1, 1, tzinfo=timezone.utc)


def crm_value(name: str, deals: list[dict], at: datetime):
    """One built-in CRM metric as of `at`. Flow metrics use the window ending at `at`."""
    w7 = (at - timedelta(days=7), at)
    if name == "open_pipeline":
        return round(sum(_amt(d) for d in deals if _status(d) == "open"), 2)
    if name == "new_pipeline_7d":
        return round(sum(_amt(d) for d in deals if _in(d.get("created_at"), *w7)), 2)
    if name == "new_opps_7d":
        return sum(1 for d in deals if _in(d.get("created_at"), *w7))
    if name == "won_7d":
        return round(sum(_amt(d) for d in deals if _status(d) == "won" and _in(d.get("close_date"), *w7)), 2)
    if name == "lost_7d":
        return round(sum(_amt(d) for d in deals if _status(d) == "lost" and _in(d.get("close_date"), *w7)), 2)
    if name == "won_qtd":
        return round(sum(_amt(d) for d in deals if _status(d) == "won" and _in(d.get("close_date"), _quarter_start(at), at + timedelta(seconds=1))), 2)
    if name == "win_rate_90d":
        c = [d for d in deals if _status(d) in ("won", "lost") and _in(d.get("close_date"), at - timedelta(days=90), at)]
        won = sum(1 for d in c if _status(d) == "won")
        return round(won / len(c), 3) if c else None
    if name == "avg_cycle_days_90d":
        xs = []
        for d in deals:
            if _status(d) == "won" and _in(d.get("close_date"), at - timedelta(days=90), at):
                a, b = _dt(d.get("created_at")), _dt(d.get("close_date"))
                if a and b and b >= a:
                    xs.append((b - a).days)
        return round(sum(xs) / len(xs), 1) if xs else None
    if name == "past_due_opps":
        return sum(1 for d in deals if _status(d) == "open" and _dt(d.get("close_date")) and _dt(d.get("close_date")) < at)
    if name == "stalled_opps":
        cut = at - timedelta(days=14)
        return sum(1 for d in deals if _status(d) == "open"
                   and (_dt(d.get("last_activity_at") or d.get("created_at")) or at) < cut)
    raise KeyError(f"unknown built-in crm metric {name}")


def _filtered(deals, flt: dict | None):
    if not flt:
        return deals
    out = deals
    for k, vals in flt.items():
        want = {str(v).lower() for v in (vals if isinstance(vals, list) else [vals])}
        out = [d for d in out if str(d.get(k) or "").lower() in want]
    return out


def snapshots(ctx) -> dict:
    return ctx.store.get_state(SNAP_KEY, {}) or {}


def metric(ctx, name: str, cfg: dict, at: datetime, deals: list[dict] | None = None, warehouse=None) -> dict:
    spec = (cfg.get("metrics") or {}).get(name)
    if not spec:
        return {"name": name, "error": "not defined in config/exec_brief.yaml"}
    out = {"name": name, "label": spec.get("label", name), "unit": spec.get("unit", "count"),
           "good": spec.get("good", "up"), "value": None, "prior": None}
    if spec.get("source") == "crm":
        ds = _filtered(deals if deals is not None else ctx.store.select("deals"), spec.get("filter"))
        base = spec.get("base", name)
        out["value"] = crm_value(base, ds, at)
        if base in FLOW:
            out["prior"] = crm_value(base, ds, at - timedelta(days=7))
    elif spec.get("source") == "snowflake":
        if not (spec.get("sql") or "").strip():
            return {**out, "note": "not configured: add its SQL in config/exec_brief.yaml"}
        if warehouse is None:
            return {**out, "note": "Snowflake not connected: set SNOWFLAKE_* settings"}
        try:
            row = warehouse.scalar(spec["sql"])
        except Exception as e:
            return {**out, "note": f"query failed: {type(e).__name__}: {str(e)[:160]}"}
        out["value"], out["prior"] = row.get("value"), row.get("prior")
    else:
        return {**out, "note": f"unknown source {spec.get('source')}"}
    if out["prior"] is None:  # stock metric or a query with no prior: last week's stored snapshot
        day = (at - timedelta(days=7)).date().isoformat()
        out["prior"] = (snapshots(ctx).get(day) or {}).get(name)
    return judge(out)


def judge(m: dict) -> dict:
    v, p = m.get("value"), m.get("prior")
    if v is None or p is None:
        m["change"], m["signal"] = None, "none"
        return m
    m["change"] = round(v - p, 3)
    m["change_pct"] = round((v - p) / abs(p), 3) if p else None
    if v == p:
        m["signal"] = "flat"
    else:
        better = (v > p) == (m["good"] == "up")
        m["signal"] = "good" if better else "bad"
    return m


def _strength(m: dict) -> float:
    """How strongly a metric moved in its good (+) or bad (-) direction, for picking a department's best and worst."""
    if m.get("signal") not in ("good", "bad"):
        return 0.0
    mag = abs(m["change_pct"]) if m.get("change_pct") is not None else 1.0
    return mag if m["signal"] == "good" else -mag


def compute(ctx, names: list[str], at: datetime | None = None, warehouse=None) -> list[dict]:
    at = at or datetime.now(timezone.utc)
    cfg = config(ctx)
    deals = ctx.store.select("deals")
    return [metric(ctx, n, cfg, at, deals, warehouse) for n in names]


def role_brief(ctx, role: str, at=None, warehouse=None) -> dict:
    cfg = config(ctx)
    r = (cfg.get("roles") or {}).get(role)
    if not r:
        return {"error": f"unknown role {role}; roles: {', '.join(cfg.get('roles') or {})}"}
    return {"role": role, "title": r.get("title", role), "person": r.get("person") or {},
            "metrics": compute(ctx, r.get("metrics") or [], at, warehouse)}


def company_snapshot(ctx, at=None, warehouse=None) -> dict:
    cfg = config(ctx)
    out = {}
    for dept, names in (cfg.get("departments") or {}).items():
        ms = [m for m in compute(ctx, names, at, warehouse) if m.get("value") is not None]
        ranked = sorted(ms, key=_strength)
        best = ranked[-1] if ranked and _strength(ranked[-1]) > 0 else None
        worst = ranked[0] if ranked and _strength(ranked[0]) < 0 else None
        out[dept] = {"good": best, "bad": worst,
                     "not_configured": [n for n in names if n not in {m["name"] for m in ms}]}
    return out


def save_snapshot(ctx, at=None, warehouse=None) -> dict:
    """Store today's value of every configured metric (for next week's comparisons)."""
    at = at or datetime.now(timezone.utc)
    cfg = config(ctx)
    names = list((cfg.get("metrics") or {}).keys())
    vals = {m["name"]: m["value"] for m in compute(ctx, names, at, warehouse) if m.get("value") is not None}
    snaps = snapshots(ctx)
    snaps[at.date().isoformat()] = vals
    cut = (at - timedelta(days=KEEP_DAYS)).date().isoformat()
    ctx.store.set_state(SNAP_KEY, {k: v for k, v in snaps.items() if k >= cut})
    return vals


def heat_map(ctx, weeks: int = 5, at=None) -> dict:
    """Command center: each metric's value on the same weekday for the last N weeks, each cell judged against the
    week before it."""
    at = at or datetime.now(timezone.utc)
    cfg = config(ctx)
    snaps = snapshots(ctx)
    days = [(at - timedelta(days=7 * i)).date().isoformat() for i in range(weeks, -1, -1)]
    rows = []
    for n in cfg.get("command_center") or []:
        spec = (cfg.get("metrics") or {}).get(n) or {}
        vals = [(snaps.get(d) or {}).get(n) for d in days]
        cells = []
        for prev, cur in zip(vals, vals[1:]):
            cells.append(judge({"value": cur, "prior": prev, "good": spec.get("good", "up")})["signal"])
        rows.append({"name": n, "label": spec.get("label", n), "unit": spec.get("unit"), "values": vals[1:],
                     "cells": cells})
    return {"weeks": days[1:], "rows": rows}


# ---------------- formatting ----------------
ICON = {"good": ":large_green_square:", "bad": ":large_red_square:", "flat": ":white_large_square:",
        "none": ":black_square_button:"}


def fmt(v, unit):
    if v is None:
        return "n/a"
    if unit == "usd":
        return f"${v:,.0f}"
    if unit == "pct":
        return f"{v * 100:.1f}%" if abs(v) <= 1.5 else f"{v:.1f}%"
    if unit == "days":
        return f"{v:,.1f} days"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def line(m: dict) -> str:
    if m.get("note"):
        return f"- {m.get('label', m['name'])}: {m['note']}"
    chg = ""
    if m.get("change") is not None:
        arrow = "up" if m["change"] > 0 else "down" if m["change"] < 0 else "flat"
        pct = f" ({m['change_pct'] * 100:+.0f}%)" if m.get("change_pct") is not None else ""
        chg = f", {arrow}{pct} vs last week"
    return f"{ICON[m.get('signal', 'none')]} {m['label']}: {fmt(m['value'], m['unit'])}{chg}"


def format_role(b: dict) -> str:
    return f"*{b['title']} brief*\n" + "\n".join(line(m) for m in b["metrics"])


def format_snapshot(s: dict) -> str:
    out = ["*Company snapshot*"]
    for dept, v in s.items():
        g = line(v["good"]) if v["good"] else "- no number moved the right way"
        b = line(v["bad"]) if v["bad"] else "- no number moved the wrong way"
        out.append(f"*{dept.replace('_', ' ').title()}*\n{g}\n{b}")
    return "\n".join(out)


def format_heat(h: dict) -> str:
    out = ["*Command center*  (weeks oldest to newest; green better, red worse than the week before)"]
    for r in h["rows"]:
        out.append("".join(ICON[c] for c in r["cells"]) + f"  {r['label']}: {fmt(r['values'][-1], r['unit'])}")
    return "\n".join(out)
