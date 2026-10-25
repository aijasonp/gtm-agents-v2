"""Proposal Builder evaluator: exact quote math, guardrails, approvals, proposal content and send gating."""
from __future__ import annotations

import tempfile
from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    ctx.manifest.config["output_dir"] = tempfile.mkdtemp(prefix="proposals-")
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    ctx.store.upsert_account(spec["account"])
    ctx.store.upsert("deals", spec["deal"])
    out = []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    first = None
    for c in spec["quotes"]:
        q = eng.build_quote(ctx, spec["deal"]["id"], c["lines"], c["term_years"], c["discount_pct"], c["role"], now)
        ex = c["expect"]
        if "error" in q:
            add(c["name"], False, q["error"])
            continue
        first = first or q
        for k, v in ex.items():
            if k == "tier":
                got = q["lines"][0]["tier"]
            elif k == "guardrail":
                got = q["guardrail"]["status"]
            elif k == "level":
                got = q["guardrail"].get("level")
            elif k == "reason_has":
                got = v if v in q["guardrail"].get("reason", "") else q["guardrail"].get("reason")
            else:
                got = q[k]
            add(f"{c['name']}: {k}", got == v, f"got {got}, want {v}")
        if ex.get("guardrail") == "needs_approval":
            add(f"{c['name']}: discount approval queued", q["approval_id"] and q["status"] == "pending_approval",
                q["status"])
        if ex.get("guardrail") == "blocked":
            add(f"{c['name']}: blocked quote cannot render", "error" in eng.render_proposal(ctx, q["quote_id"]))
    for e in spec["errors"]:
        q = eng.build_quote(ctx, spec["deal"]["id"], e["lines"], e["term_years"], 0, "ae", now)
        add(f"rejects {e['has']}", e["has"] in q.get("error", ""), q.get("error"))
    r = eng.render_proposal(ctx, first["quote_id"])
    html = open(r["html_path"]).read()
    for s in spec["proposal"]["must_include"]:
        add(f"proposal includes {s!r}", s in html, "")
    for s in spec["proposal"]["must_not_include"]:
        add(f"proposal omits {s!r}", s not in html, "")
    add("proposal is self-contained (no scripts)", "<script" not in html.lower())
    send = eng.queue_send(ctx, first["quote_id"], "dana@northwind.example")
    add("send waits for approval", send.get("queued_for_approval"), send)
    pend = next(c for c in spec["quotes"] if c["expect"].get("guardrail") == "needs_approval")
    pq = eng.build_quote(ctx, spec["deal"]["id"], pend["lines"], pend["term_years"], pend["discount_pct"], pend["role"], now)
    add("pending discount cannot be sent", "error" in eng.queue_send(ctx, pq["quote_id"], "dana@northwind.example"))
    return out
