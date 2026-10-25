"""Stack Audit evaluator: exact spend, savings, actions, renewals, overlap and side-by-side numbers."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    s = eng.scenarios(ctx, None, now)
    recs = {r["tool"]: r for r in s["recommendations"]}
    add("known spend excludes unknown cost", s["total_spend"] == ex["total_spend"] and s["unknown_cost"] == ex["unknown_cost"],
        (s["total_spend"], s["unknown_cost"]))
    for tool, a in ex["actions"].items():
        add(f"{tool} -> {a}", recs[tool]["action"] == a, recs[tool]["action"])
    for tool, v in ex["savings"].items():
        add(f"{tool} savings {v}", recs[tool]["savings"] == v, recs[tool]["savings"])
    for tool, v in ex["keep_seats"].items():
        add(f"{tool} keeps {v} seats", recs[tool].get("keep_seats") == v, recs[tool].get("keep_seats"))
    for tool, v in ex["consolidate_into"].items():
        add(f"{tool} consolidates into {v}", recs[tool].get("into") == v, recs[tool].get("into"))
    add("unknown-cost cut counts no savings", recs["Meeting Notes I"]["savings"] is None and "unknown" in recs["Meeting Notes I"].get("note", ""),
        recs["Meeting Notes I"])
    add("total savings", s["total_savings"] == ex["total_savings"], s["total_savings"])
    add("every cut and consolidate carries a condition",
        all(r.get("condition") for r in recs.values() if r["action"] in ("cut", "consolidate")), "")
    add("partial or missing coverage blocks a cut", ex["intent_gap"] in recs["Intent Platform A"]["gaps"], recs["Intent Platform A"]["gaps"])
    tools = eng.enriched(ctx, None, now)
    add("overlap capabilities", sorted(eng.overlap(tools)) == ex["overlap"], sorted(eng.overlap(tools)))
    cpas = {t["tool"]: t["cost_per_active_seat"] for t in tools}
    add("cost per active seat", all(cpas[k] == v for k, v in ex["cost_per_active_seat"].items()), cpas)
    cal = eng.calendar(ctx, 120, None, now)
    add("renewal calendar soonest first, passed deadline flagged",
        cal[0]["tool"] == ex["first_renewal"] and "passed" in cal[0]["status"], cal[:2])
    al = {a["tool"]: a["band"] for a in eng.renewal_alerts(ctx, None, now)}
    add("alert bands", all(al.get(k) == v for k, v in ex["bands"].items()), al)
    add("alerts fire once per band", eng.renewal_alerts(ctx, None, now) == [], "")
    sb = spec["side_by_side"]
    for acct, tier in sb["agent_scores"].items():
        ctx.store.insert("INSERT INTO scores (run_id, agent, account_id, score, tier) VALUES (?,?,?,?,?)",
                         ("r1", "signal-scout", acct, 50, tier))
    for acct, o in sb["outcomes"].items():
        ctx.store.add_outcome(acct, o)
    c = eng.compare(ctx, sb["tool"], str(m.path(sb["file"])))
    e = ex["side_by_side"]
    add("side by side overlap and misses", c["overlap_pct"] == e["overlap_pct"] and c["tool_only_converted"] == e["tool_only_converted"]
        and c["agent_only"] == e["agent_only"], c)
    add("side by side condition", c["converted_caught_pct"] == e["converted_caught_pct"] and c["condition_met"] == e["condition_met"],
        (c["converted_caught_pct"], c["condition_met"]))
    memo = eng.memo(ctx, "Enrichment Workbench D", side_by_side=None, now=now)
    add("memo saved as draft with numbers and deadline",
        memo["draft_id"] and "$24,000 a year" in memo["body"] and "2026-12-01" in memo["subject"] and memo["source"] == "template",
        memo.get("subject"))
    return out
