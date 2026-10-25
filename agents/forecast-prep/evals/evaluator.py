"""Forecast Prep evaluator: exact totals, suggested commit, flags, questions, changes, pace and alerts."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    for did, snaps in spec.get("history", {}).items():
        for at, stage, status, amount, cd, cat in snaps:
            ctx.store.insert("INSERT INTO deal_history (deal_id, snapshot_at, stage, status, amount, close_date, "
                             "forecast_category) VALUES (?,?,?,?,?,?,?)", (did, at, stage, status, amount, cd, cat))
    for i in spec.get("inspections", []):
        ctx.store.add_insight("deal-inspection", "deal_inspection", i["deal_id"], {"risk": i["risk"], "gaps": i["gaps"]},
                              observed_at="2026-11-10T07:00:00+00:00", deal_id=i["deal_id"])
    eng = load_module(m, "engine")
    if spec.get("previous_snapshot"):
        ctx.store.set_state(eng.SNAP_KEY, [spec["previous_snapshot"]])
    now = datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)})

    sam, lee, pri = (eng.ae_prep(ctx, o, now) for o in ("Sam Rivera", "Lee Park", "Priya Shah"))
    e = ex["sam"]
    q = sam["quarter_totals"]
    add("Sam quarter commit", q["commit"] == e["commit"], q)
    add("Sam best case = commit + best case", q["best_case"] == e["best_case"], q)
    add("Sam pipeline", q["pipeline"] == e["pipeline"], q)
    add("Sam month commit", sam["month_totals"]["commit"] == e["month_commit"], sam["month_totals"])
    add("Sam suggested drops the high-risk commit deal",
        sam["suggested_commit"] == e["suggested"] and [d["name"] for d in sam["dropped"]] == e["dropped"],
        (sam["suggested_commit"], sam["dropped"]))
    add("Sam flagged happy ears", e["flag"] in (sam["flag"] or ""), sam["flag"])
    e = ex["lee"]
    add("Lee won this quarter, lost and next-quarter deals excluded",
        lee["quarter_totals"]["won"] == e["won"] and lee["quarter_totals"]["commit"] == e["commit"], lee["quarter_totals"])
    add("Lee suggested adds the safe late-stage best case deal",
        lee["suggested_commit"] == e["suggested"] and [d["name"] for d in lee["added"]] == e["added"], lee["added"])
    add("Lee flagged sandbagging", e["flag"] in (lee["flag"] or ""), lee["flag"])
    e = ex["priya"]
    add("Priya pipeline excludes next quarter", pri["quarter_totals"]["pipeline"] == e["pipeline"], pri["quarter_totals"])
    add("Priya uninspected commit deal counts but is marked",
        pri["suggested_commit"] == e["suggested"] and pri["not_inspected"] == e["not_inspected"], pri["not_inspected"])
    add("Priya flagged happy ears", e["flag"] in (pri["flag"] or ""), pri["flag"])
    add("quota split evenly", all(r["quota"] == ex["quota_each"] for r in (sam, lee, pri)), [sam["quota"], lee["quota"]])
    qb = eng.questions(ctx)
    contoso = next(f for f in sam["commit_deals"] if f["name"] == "Contoso Health")
    add("Contoso questions in priority order", contoso["questions"] == [qb[k] for k in ex["contoso_questions"]],
        contoso["questions"])
    ch = next((c for c in sam["changes"] if c["name"] == "Contoso Health"), None)
    add("Contoso change detected", ch and any(x["text"] == ex["contoso_change"] for x in ch["changes"]), ch)
    mg = eng.manager_prep(ctx, now)
    add("team coverage", mg["team_coverage"] == ex["team_coverage"], mg["team_coverage"])
    add("slipped twice", [f["name"] for f in mg["slipped_twice"]] == ex["slipped_twice"], mg["slipped_twice"])
    add("first deal to inspect", mg["top_deals"][0]["name"] == ex["first_to_inspect"], [f["name"] for f in mg["top_deals"]])
    xp = eng.exec_prep(ctx, now)
    qs, qe = eng.quarter_bounds(now)
    frac = (now - qs).total_seconds() / (qe - qs).total_seconds()
    add("linear pace and gap", xp["linear_pace"] == round(1200000 * frac, 2) and
        xp["pace_gap"] == round(55000 - 1200000 * frac, 2), (xp["linear_pace"], xp["pace_gap"]))
    add("week over week commit", xp["wow"]["commit"] == ex["wow_commit"], xp["wow"])
    al = eng.change_alerts(ctx, now)
    add("change alerts: left commit, amount move, out of quarter", len(al) == ex["alerts"] and
        {a["alert"].split(" ")[0] for a in al} >= {"moved", "amount", "close"}, al)
    add("alerts fire once", eng.change_alerts(ctx, now) == [], "")
    add("template summaries without a model key",
        sam["summary_source"] == mg["summary_source"] == xp["summary_source"] == "template", "")
    # Forecast calls and the board range
    for c in spec.get("calls", []):
        eng.submit_call(ctx, c["owner"], c["commit"], c.get("best_case"), now=now)
    if "board" in ex:
        b = eng.board_forecast(ctx, now)
        bx = ex["board"]
        add("board range is ordered low <= high", b["range"]["low"] <= b["range"]["high"], b["range"])
        add("board low = won + suggested commit", b["range"]["low"] == round(b["won"] + mg["suggested_commit"], 2), b["range"])
        add("board call uses submitted calls", b["range"]["call"] == bx["call"], b["range"])
        add("reps without a call are listed", sorted(b["no_call_this_quarter"]) == sorted(bx["no_call"]), b["no_call_this_quarter"])
    return out
