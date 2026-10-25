"""CRM Hygiene evaluator: duplicates, survivor choice, orphan matching, bounces, stale deals, approval gating."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for c in spec["contacts"]:
        ctx.store.upsert("contacts", c)
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    da = eng.duplicate_accounts(ctx)
    add("duplicate account groups", sorted(g["ids"] for g in da) == sorted(ex["account_groups"]), [g["ids"] for g in da])
    for k, v in ex["account_survivor"].items():
        g = next((g for g in da if k in g["ids"]), {})
        add(f"survivor {v}", g.get("survivor") == v, g.get("survivor"))
    dc = eng.duplicate_contacts(ctx)
    add("duplicate contact groups", [g["ids"] for g in dc] == ex["contact_groups"], [g["ids"] for g in dc])
    add("contact survivor has CRM id", dc and dc[0]["survivor"] == ex["contact_survivor"], dc[0]["survivor"] if dc else None)
    miss = {r["contact_id"]: r["match"] for r in eng.missing_account(ctx)}
    add("orphan contacts matched by work domain only", miss == ex["missing_match"], miss)
    add("bounced contacts", [r["contact_id"] for r in eng.bounced(ctx)] == ex["bounced"], eng.bounced(ctx))
    st = eng.stale(ctx, now)
    add("stale deals", [r["deal_id"] for r in st] == ex["stale"], [r["deal_id"] for r in st])
    d1 = next((r for r in st if r["deal_id"] == "d1"), {})
    add("past-due close date pushed 30 days", d1.get("proposed_fields", {}).get("close_date") == ex["d1_close_date"], d1)
    before = len(ctx.crm.writes) if hasattr(ctx.crm, "writes") else 0
    r = eng.propose_fix(ctx, "merge_accounts", ex["account_groups"][0])
    add("merge queues approval, writes nothing", r.get("queued_for_approval") and
        (len(ctx.crm.writes) if hasattr(ctx.crm, "writes") else 0) == before, r)
    add("personal email never linked", eng.propose_fix(ctx, "link_contact", ["c4"])["skipped"], "")
    return out
