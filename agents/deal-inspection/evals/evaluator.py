"""Deal Inspection evaluator: risk, recommendation rules, gap kinds and call-evidence merge."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for a in spec.get("accounts", []):
        ctx.store.upsert_account(a)
    for c in spec.get("contacts", []):
        ctx.store.upsert("contacts", c)
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    for did, dates in spec.get("history", {}).items():
        for i, cd in enumerate(dates):
            ctx.store.insert("INSERT INTO deal_history (deal_id, snapshot_at, stage, status, close_date) VALUES (?,?,?,?,?)",
                             (did, f"2026-09-{10 + i:02d}T00:00:00+00:00", "Proposal", "open", cd))
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    res = {i["deal_id"]: i for i in eng.inspect_all(ctx, now=now)}
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": detail})

    for did, rec in ex.get("recommendation", {}).items():
        add(f"{did} -> {rec}", res[did]["recommendation"] == rec, f"got {res[did]['recommendation']} ({res[did]['rule']}) risk {res[did]['risk']}")
    for did, mx in ex.get("max_risk", {}).items():
        add(f"{did} risk <= {mx}", res[did]["risk"] <= mx, f"risk {res[did]['risk']}: {res[did]['drivers']}")
    for did, mn in ex.get("min_risk", {}).items():
        add(f"{did} risk >= {mn}", res[did]["risk"] >= mn, f"risk {res[did]['risk']}: {res[did]['drivers']}")
    for hi, lo in ex.get("order", []):
        add(f"{hi} riskier than {lo}", res[hi]["risk"] > res[lo]["risk"], f"{res[hi]['risk']} vs {res[lo]['risk']}")
    for did, parts in ex.get("drivers_include", {}).items():
        text = " | ".join(res[did]["drivers"])
        miss = [p for p in parts if p not in text]
        add(f"{did} drivers include {parts}", not miss, f"missing {miss} in: {text}")
    for did, kinds in ex.get("gap_kinds", {}).items():
        got = {g["element"]: g["kind"] for g in res[did]["gaps"]}
        add(f"{did} gap kinds {kinds}", all(got.get(e) == k for e, k in kinds.items()), f"got {got}")
    for did in ex.get("not_inspected", []):
        add(f"{did} (closed) not inspected", did not in res, "inspected" if did in res else "skipped")
    for did, i in res.items():
        if i["recommendation"] != "progress":
            add(f"{did} has 1-3 actions", 1 <= len(i["actions"]) <= 3, str(i["actions"]))
    if "insights_written" in ex:
        n = len(ctx.store.insights("deal_inspection"))
        add("one deal_inspection insight per open deal", n == ex["insights_written"], f"{n} written")

    ev = ex.get("evidence")
    if ev:
        h = spec["evidence_handoff"]
        from gtm_core.handoffs import Handoffs
        Handoffs(ctx.store, "meeting-intelligence").send("deal-inspection", "meddpicc_evidence", h["deal_id"], h)
        jobs = load_module(m, "jobs")
        r = jobs.apply_evidence(ctx)
        changed = r["results"][0].get("changed", []) if r["results"] else []
        add("call evidence fills only missing elements", sorted(changed) == sorted(ev["changed"]), f"changed {changed}")
        acts = [a["action"] for a in ctx.approvals.list()]
        add("CRM write queued for approval", ev["approval_action"] in acts, f"approvals {acts}")
        md = ctx.store.get("deals", h["deal_id"])["meddpicc"]
        add("evidence never confirms an element", all(md[e]["score"] == 1 for e in ev["changed"]), str({e: md[e] for e in ev["changed"]}))
        add("handoff consumed", not ctx.handoffs.pending("meddpicc_evidence"), "")
        after = eng.inspect(ctx, ctx.store.get("deals", h["deal_id"]), now)
        add("evidence reduces gaps", len(after["gaps"]) < len(res[h["deal_id"]]["gaps"]),
            f"{len(res[h['deal_id']]['gaps'])} -> {len(after['gaps'])}")
    return out
