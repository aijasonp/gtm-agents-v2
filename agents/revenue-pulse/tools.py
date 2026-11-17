"""Revenue Pulse MCP tools. Every number is computed from the store; nothing is estimated."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def pipeline_summary(ctx, owner: str = "") -> dict:
    """Open and weighted pipeline, quarter coverage, this week's created/won/lost, slipped and stale counts.
    Optional owner filter (quota and coverage are team-level only)."""
    eng = _eng(ctx)
    p = eng.pulse(ctx, owner=owner)
    keep = ("as_of", "owner", "open_deals", "open_pipeline", "weighted_pipeline", "quarter", "created", "won", "lost",
            "win_rate", "wow")
    return {**{k: p[k] for k in keep}, "slipped": {k: p["slipped"][k] for k in ("count", "amount")},
            "stale": {k: p["stale"][k] for k in ("days", "count", "amount")}, "text": eng.format_pulse(p)}


def forecast_rollup(ctx) -> dict:
    """Open amount closing this month and this quarter by forecast category, overall and per owner."""
    from gtm_core import pipeline
    eng = _eng(ctx)
    now = eng._now(None)
    ms, me = eng.month_bounds(now)
    qs, qe = eng.quarter_bounds(now)
    out = {"month": {}, "quarter": {}, "by_owner": {}}
    for d in ctx.store.select("deals"):
        if not pipeline.is_open(d):
            continue
        cat = (d.get("forecast_category") or "uncategorized").lower()
        cd = pipeline.parse_dt(d.get("close_date"))
        a = eng.amt(d)
        if cd and cd < qe:
            out["quarter"][cat] = round(out["quarter"].get(cat, 0) + a, 2)
            o = out["by_owner"].setdefault(d.get("owner") or "Unassigned", {})
            o[cat] = round(o.get(cat, 0) + a, 2)
        if cd and ms <= cd < me:
            out["month"][cat] = round(out["month"].get(cat, 0) + a, 2)
    return out


def slipped_deals(ctx, days: int = 7) -> dict:
    """Open deals whose close date moved later in the last N days, largest first."""
    p = _eng(ctx).pulse(ctx, period_days=days)
    return {"days": days, **p["slipped"]}


def stale_deals(ctx, days: int = 14) -> dict:
    """Open deals with no activity for more than N days, longest idle first."""
    p = _eng(ctx).pulse(ctx, stale_days=days)
    return p["stale"]


def top_risks(ctx, limit: int = 5) -> dict:
    """Highest-risk open deals, from the latest Deal Inspection results (rule-based when it has not run)."""
    eng = _eng(ctx)
    p = eng.pulse(ctx)
    from gtm_core import pipeline
    open_ = [d for d in ctx.store.select("deals") if pipeline.is_open(d)]
    rs = eng.risks(ctx, open_, {s["deal_id"] for s in p["slipped"]["deals"]}, eng._now(None), limit)
    return {"count": len(rs), "risks": rs}


def owner_scorecard(ctx, owner: str) -> dict:
    """One owner's open and weighted pipeline, won this quarter, created/won/lost this week, stale, slipped, overdue tasks and risks."""
    eng = _eng(ctx)
    p = eng.pulse(ctx, owner=owner)
    if not p["open_deals"] and not p["won"]["count"] and not p["lost"]["count"] and not p["by_owner"]:
        return {"error": f"no deals found for owner '{owner}'"}
    row = next((o for o in p["by_owner"] if o["owner"].lower() == owner.lower()), {})
    row = {("stale_count" if k == "stale" else "slipped_count" if k == "slipped" else k): v for k, v in row.items()}
    return {**row, "owner": owner, "created": p["created"], "won_this_week": p["won"], "lost_this_week": p["lost"],
            "slipped_deals": p["slipped"]["deals"], "stale_deals": p["stale"]["deals"], "top_risks": p["top_risks"]}


def daily_report(ctx, days: int = 1) -> dict:
    """Whole-funnel report for the last N days: leads by source, signals, new tier A accounts, outbound drafted and
    sent, human opens and replies (machine opens counted apart), meetings, deals created, moved, won and lost,
    and approvals waiting."""
    r = _eng(ctx).daily(ctx, days=int(days))
    return {**r, "text": _eng(ctx).format_daily(r)}


def adoption_report(ctx, window_days: int = 0, lookback_days: int = 0, min_actions: int = 0) -> dict:
    """Which reps use the agents (active = min_actions or more actions in the window), adoption and month-over-month
    retention, and win rate on deals closed in the lookback for reps who were active before the close vs those who
    were not, with the lift in points and how many closers used the agents. Zero means the configured default."""
    from gtm_core import adoption
    r = _eng(ctx).adoption(ctx, window_days=window_days, lookback_days=lookback_days, min_actions=min_actions)
    return {**r, "text": adoption.format_report(r)}


TOOLS = {f.__name__: f for f in [pipeline_summary, forecast_rollup, slipped_deals, stale_deals, top_risks, owner_scorecard,
                                 daily_report, adoption_report]}
