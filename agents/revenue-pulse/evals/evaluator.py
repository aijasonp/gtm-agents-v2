"""Revenue Pulse evaluator: exact metric checks against hand-computed values."""
from __future__ import annotations

import json
from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    for did, snaps in spec.get("history", {}).items():
        for at, stage, cd in snaps:
            ctx.store.insert("INSERT INTO deal_history (deal_id, snapshot_at, stage, status, close_date) VALUES (?,?,?,?,?)",
                             (did, at, stage, "open", cd))
    for t in spec.get("tasks", []):
        ctx.store.upsert("tasks", t)
    for i in spec.get("inspections", []):
        ctx.store.add_insight("deal-inspection", "deal_inspection", i["deal_id"],
                              {"risk": i["risk"], "recommendation": i["recommendation"], "flags": [f"risk {i['risk']}"]},
                              observed_at=i["observed_at"], deal_id=i["deal_id"])
    eng = load_module(m, "engine")
    if spec.get("previous_pulse"):
        ctx.store.set_state(eng.STATE_KEY, spec["previous_pulse"])
    now = datetime.fromisoformat(spec["now"])
    p = eng.pulse(ctx, now=now)
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)})

    q = p["quarter"]
    add("open pipeline", p["open_pipeline"] == ex["open_pipeline"], p["open_pipeline"])
    add("weighted pipeline", p["weighted_pipeline"] == ex["weighted_pipeline"], p["weighted_pipeline"])
    add("won QTD", q["won_qtd"] == ex["won_qtd"], q["won_qtd"])
    add("remaining quota", q["remaining"] == ex["remaining"], q["remaining"])
    add("quarter pipeline (excludes next quarter)", q["pipeline"] == ex["quarter_pipeline"], q["pipeline"])
    add("coverage", q["coverage"] == ex["coverage"], q["coverage"])
    for k in ("created", "won", "lost"):
        got = {"count": p[k]["count"], "amount": p[k]["amount"]}
        add(f"{k} this period", got == ex[k], got)
    add("win rate", p["win_rate"] == ex["win_rate"], p["win_rate"])
    sl = {s["deal_id"]: s for s in p["slipped"]["deals"]}
    add("slipped deals (only moves inside the period)", sorted(sl) == sorted(ex["slipped_ids"]), sorted(sl))
    add("slipped amount", p["slipped"]["amount"] == ex["slipped_amount"], p["slipped"]["amount"])
    add("slip days", all(sl.get(k, {}).get("days") == v for k, v in ex["slip_days"].items()),
        {k: v.get("days") for k, v in sl.items()})
    got = {k: p["stage_moves"][k] for k in ("forward", "back")}
    add("stage moves", got == ex["stage_moves"], got)
    add("stale deals", [s["deal_id"] for s in p["stale"]["deals"]] == ex["stale_ids"], p["stale"]["deals"])
    add("closing this month by category", p["closing_this_month"] == ex["closing_this_month"], p["closing_this_month"])
    owners = {o["owner"]: o["open_pipeline"] for o in p["by_owner"]}
    add("per-owner open pipeline", all(owners.get(k) == v for k, v in ex["owner_open"].items()), owners)
    add("overdue tasks", p["overdue_tasks"] == ex["overdue_tasks"], p["overdue_tasks"])
    order = [r["deal_id"] for r in p["top_risks"]]
    add("top risks use latest inspection, open deals only", order[:len(ex["top_risk_order"])] == ex["top_risk_order"]
        and "E" not in order, order)
    w = p["wow"]
    add("week-over-week deltas", all(w.get(k) == v for k, v in ex["wow"].items()), w)

    if ex.get("job_posts_summary"):
        jobs = load_module(m, "jobs")
        r = jobs.weekly_pulse(ctx, now=now)
        text = ctx.slack.sent[-1]["text"] if ctx.slack.sent else ""
        add("job posts pulse with 5 summary bullets", "Revenue Pulse" in text and
            text.split("Summary:")[-1].count("\n- ") + text.split("Summary:")[-1].startswith("\n- ") >= 5 and r["summary_source"] == "template",
            text[-400:])
        add("job stores snapshot for next week", ctx.store.get_state(eng.STATE_KEY)["open_pipeline"] == ex["open_pipeline"],
            json.dumps(ctx.store.get_state(eng.STATE_KEY)))
        add("every number in the post is from the pulse", "$270,000" in text and "$120,000" in text and "0.26x" in text, "")
    d = eng.daily(ctx, now, days=7)
    add("daily report: won in window matches the pulse", d["deals"]["won"]["count"] == p["won"]["count"],
        (d["deals"]["won"], p["won"]))
    add("daily report text renders", "Daily GTM report" in eng.format_daily(d), "")
    return out
