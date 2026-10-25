"""Reply Desk evaluator: classification, actions, local flags, owner, SLA, outcomes, gate, idempotency."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for a in spec.get("accounts", []):
        ctx.store.upsert_account(a)
    for d in spec.get("deals", []):
        ctx.store.upsert("deals", d)
    for c in spec.get("contacts", []):
        ctx.store.upsert("contacts", c)
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    res = {}
    for r in spec["replies"]:
        rid = eng.ingest_row(ctx, {**r, "received_at": spec["now"]}, now)
        res[r["id"]] = eng.handle(ctx, rid, now)
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:300]})

    for rid, cls in ex["class"].items():
        add(f"{rid} is {cls}", res[rid]["class"] == cls, f"{res[rid]['class']}: {res[rid]['reason']}")
    for rid, cat in ex.get("category", {}).items():
        add(f"{rid} category {cat}", res[rid]["category"] == cat, res[rid]["category"])
    for rid, d in ex.get("follow_up_date", {}).items():
        add(f"{rid} follow-up {d}", (res[rid]["follow_up_at"] or "")[:10] == d, res[rid]["follow_up_at"])
    for rid, acts in ex.get("actions_include", {}).items():
        add(f"{rid} actions {acts}", set(acts) <= set(res[rid]["actions"]), res[rid]["actions"])
    for rid in ex.get("no_approvals", []):
        add(f"{rid} queues nothing", not res[rid]["approvals"], res[rid]["approvals"])
    for cid, flags in ex.get("local_flags", {}).items():
        c = ctx.store.get("contacts", cid) or {}
        ok = all((str(c.get(k))[:10] == str(v)[:10]) if isinstance(v, str) else c.get(k) == v for k, v in flags.items())
        add(f"{cid} local flags {flags}", ok, {k: c.get(k) for k in flags})
    for rid, o in ex.get("owner", {}).items():
        add(f"{rid} owner {o}", res[rid]["owner"] == o, f"{res[rid]['owner']} via {res[rid]['owner_source']}")
    for rid, due in ex.get("sla_due", {}).items():
        tasks = [a for a in ctx.approvals.list(None) if a["id"] in res[rid]["approvals"] and a["action"] == "crm_task"]
        add(f"{rid} SLA due {due}", any(t["payload"].get("due_at") == due for t in tasks), [t["payload"].get("due_at") for t in tasks])
    for acct, outs in ex.get("outcomes", {}).items():
        got = sorted(r["outcome"] for r in ctx.store.query("SELECT outcome FROM outcomes WHERE account_id=?", (acct,)))
        add(f"{acct} outcomes {outs}", got == sorted(outs), got)
    for rid in ex.get("drafts_pass_gate", []):
        d = res[rid]["draft"] or {}
        add(f"{rid} draft passes Copy QA Gate", d.get("gate_passed"), f"{d.get('gate_score')}/40 {d.get('fix')}")
    q = ex.get("question_without_facts_gets_task")
    if q:
        add(f"{q} not answered without approved facts", res[q]["draft"] is None and "crm_task" in res[q]["actions"],
            res[q]["actions"])
    rid = ex.get("second_handle_is_noop")
    if rid:
        before = len(ctx.approvals.list(None))
        again = eng.handle(ctx, res[rid]["reply_id"], now)
        add(f"{rid} second handle does nothing", again.get("skipped") and len(ctx.approvals.list(None)) == before, again)
    return out
