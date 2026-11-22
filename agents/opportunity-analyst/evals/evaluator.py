"""Opportunity Analyst evaluator: exact checks against hand-computed values."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    for i, (deal, stage, at) in enumerate(spec["stage_history"]):
        ctx.store.upsert("deal_stage_history", {"id": f"h{i}", "deal_id": deal, "stage": stage, "changed_at": at})
    eng = load_module(m, "engine")
    at = datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)})

    wl = eng.win_loss(ctx, at=at)
    for k, v in ex["win_loss"].items():
        add(f"win_loss {k}", wl[k] == v, wl[k])
    for by, key in (("lead_source", "win_rate_by_lead_source"), ("segment", "win_rate_by_segment")):
        g = {x["key"]: x["win_rate"] for x in eng.win_loss(ctx, group_by=by, at=at)["groups"]}
        for k, v in ex[key].items():
            add(f"win rate {by}={k}", g.get(k) == v, g.get(k))

    la = eng.loss_analysis(ctx, at=at)
    e = ex["loss"]
    add("lost count", la["lost"] == e["lost"], la["lost"])
    add("lost amount", la["lost_amount"] == e["lost_amount"], la["lost_amount"])
    add("top loss reason", la["by_reason"][0]["key"] == e["top_reason"], la["by_reason"])
    sl = {x["key"]: x["count"] for x in la["by_stage_lost"]}
    add("stage lost at", sl == e["stage_lost"], sl)
    add("largest loss", la["largest"][0]["id"] == e["largest"], la["largest"][0])
    add("old loss outside window excluded", all(r["id"] != "G" for r in la["largest"]))

    op = eng.open_pipeline(ctx, at=at)
    e = ex["open"]
    add("open count", op["open"] == e["open"], op["open"])
    add("open amount", op["open_amount"] == e["open_amount"], op["open_amount"])
    add("past due", (op["past_due_close"]["count"], op["past_due_close"]["amount"]) ==
        (e["past_due_count"], e["past_due_amount"]), op["past_due_close"])

    sc = eng.stage_conversion(ctx, at=at)
    e = ex["conversion"]
    st = {s["stage"]: s for s in sc["stages"]}
    add("cohort", sc["cohort"] == e["cohort"], sc["cohort"])
    add("history source is crm", sc["history_source"] == "crm", sc["history_source"])
    for k, v in e["reached"].items():
        add(f"reached {k}", st[k]["reached"] == v, st[k]["reached"])
    for k, v in e["to_next_rate"].items():
        add(f"to next {k}", st[k]["to_next_rate"] == v, st[k]["to_next_rate"])
    for k, v in e["win_rate_from_stage"].items():
        add(f"win from {k}", st[k]["win_rate_from_stage"] == v, st[k]["win_rate_from_stage"])
    for k, v in e["avg_days_in_stage"].items():
        add(f"days in {k}", st[k]["avg_days_in_stage"] == v, st[k]["avg_days_in_stage"])

    tr = eng.trend(ctx, periods=3, at=at)["periods"]
    for want, got in zip(ex["trend_3_months"], tr):
        add(f"trend {want['period']}", all(got[k] == v for k, v in want.items()), got)

    f = eng.list_opps(ctx, status="lost", at=at)
    add("find lost (all history)", (f["count"], f["total_amount"]) ==
        (ex["find_lost_all"]["count"], ex["find_lost_all"]["total_amount"]), f)
    f = eng.list_opps(ctx, status="lost", since="365d", at=at)
    e = ex["find_lost_365d"]
    add("find lost 365d", (f["count"], f["total_amount"], f["opportunities"][0]["id"]) ==
        (e["count"], e["total_amount"], e["first"]), f)

    dt = eng.detail(ctx, "rollout")
    e = ex["detail_rollout"]
    add("detail by name", dt.get("opportunity", {}).get("id") == e["id"], dt.get("opportunity", {}).get("id"))
    add("detail history", len(dt.get("stage_history", [])) == e["history_rows"], len(dt.get("stage_history", [])))
    add("detail cycle days", dt.get("cycle_days") == e["cycle_days"], dt.get("cycle_days"))
    return out
