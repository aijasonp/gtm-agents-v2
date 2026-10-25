"""Lead Triage evaluator: deterministic checks on scoring, routing, hard rules and approvals."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module

RANK = {"disqualify": 0, "nurture": 1, "warm": 2, "hot": 3}


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
    for lead in spec["leads"]:
        ctx.store.upsert("leads", {**lead, "status": "new"})
        res[lead["id"]] = eng.process(ctx, ctx.store.get("leads", lead["id"]), now)
    approvals = {}
    for row in ctx.approvals.list(None):
        approvals.setdefault(row["action"], []).append(row["id"])
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": detail})

    for lid, t in ex.get("tier", {}).items():
        add(f"{lid} tier {t}", res[lid]["tier"] == t, f"got {res[lid]['tier']} {res[lid]['score']} {res[lid]['disqualify_reason']}")
    for lid, t in ex.get("min_tier", {}).items():
        add(f"{lid} tier >= {t}", RANK[res[lid]["tier"]] >= RANK[t], f"got {res[lid]['tier']} {res[lid]['score']}")
    for lid, o in ex.get("owner", {}).items():
        add(f"{lid} owner {o}", res[lid]["owner"] == o, f"got {res[lid]['owner']} via {res[lid]['routed_by']}")
    for lid, opts in ex.get("owner_in", {}).items():
        add(f"{lid} owner in {opts}", res[lid]["owner"] in opts, f"got {res[lid]['owner']} via {res[lid]['routed_by']}")
    for lid in ex.get("active_pipeline", []):
        add(f"{lid} flagged active pipeline", res[lid]["active_pipeline"] and "ACTIVE PIPELINE" in res[lid]["flags"][0],
            str(res[lid]["flags"]))
    for lid in ex.get("no_outreach_draft", []):
        add(f"{lid} gets no outreach draft", res[lid]["draft"] is None, "draft" if res[lid]["draft"] else "none")
    for lid, due in ex.get("sla_due", {}).items():
        add(f"{lid} SLA due {due}", res[lid]["sla_due"] == due, f"got {res[lid]['sla_due']}")
    for lid in ex.get("drafts_pass_gate", []):
        d = res[lid]["draft"] or {}
        add(f"{lid} draft passes Copy QA Gate", d.get("gate_passed"), f"{d.get('gate_score')}/40 {d.get('fix')}")
    for lid, actions in ex.get("approvals_include", {}).items():
        got = {a for a, ids in approvals.items() if set(ids) & set(res[lid]["approvals"])}
        add(f"{lid} approvals {actions}", set(actions) <= got and len(res[lid]["approvals"]) == len(actions),
            f"got {sorted(got)}")
    return out
