"""Sales Execution evaluator."""
from __future__ import annotations

import json
from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for a in spec.get("accounts", []):
        ctx.store.upsert_account(a)
    for kind in ("contacts", "deals", "tasks", "meetings"):
        for r in spec.get(kind, []):
            ctx.store.upsert(kind, r)
    for i in spec.get("insights", []):
        ctx.store.add_insight("meeting-intelligence", i["kind"], i["key"], None, i["evidence"], i["observed_at"],
                              account_id=i.get("account_id"), meeting_id=i.get("meeting_id"))
    for s in spec.get("scores", []):
        ctx.store.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, reasons) VALUES (?,?,?,?,?,?)",
                         ("r1", "signal-scout", s["account_id"], s["score"], s["tier"], json.dumps(s["reasons"])))
    jobs, eng = load_module(m, "jobs"), load_module(m, "engine")
    tools = load_module(m, "tools").TOOLS
    now = datetime.fromisoformat(spec["now"])
    run = jobs.precall_briefs(ctx, now=now)
    again = jobs.precall_briefs(ctx, now=now)
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:300]})

    add("briefs only meetings in the next 48h without transcript", run["meetings"] == ex["briefed"], run)
    add("second run does not re-brief", again["briefed"] == ex["second_run"], again)
    stored = ctx.store.insights("precall_brief")
    b = stored[0]["value"] if stored else {}
    text = stored[0]["evidence"] if stored else ""
    gaps = [g["element"] for g in b.get("meddpicc_gaps", [])]
    add(f"gaps include {ex['gaps_include']}", set(ex["gaps_include"]) <= set(gaps), gaps)
    plan = b.get("plan", [])
    add("plan opens with the biggest gap question", plan and ex["plan_first_question"] in plan[0], plan)
    add(f"plan has at most {ex['max_plan_steps']} steps, ends on next step",
        0 < len(plan) <= ex["max_plan_steps"] and "next step" in plan[-1].lower(), plan)
    od = [t["title"] for t in b.get("overdue_tasks", [])]
    add("overdue task listed, future task not", ex["overdue_task"] in od and ex["not_overdue_task"] not in od, od)
    add("last call next steps carried", any(ex["last_call_step"] in s for s in (b.get("last_call") or {}).get("next_steps", [])),
        b.get("last_call"))
    add("competitor history shown", ex["competitor"] in (b.get("history") or {}).get("competitors", {}) and ex["competitor"] in text,
        b.get("history"))
    ppl = b.get("people", [])
    add("most senior attendee first", ppl and ppl[0]["name"] == ex["first_person"], [p["name"] for p in ppl])
    add("unknown attendee kept as unknown", any(p["name"] == ex["unknown_attendee"] and p["title"] == "unknown" for p in ppl),
        [p["name"] for p in ppl])
    add("signal score included", (b.get("signal_score") or {}).get("tier") == ex["signal_tier"], b.get("signal_score"))
    add("brief posted to Slack", any("Pre-call:" in s["text"] for s in ctx.slack.sent), len(ctx.slack.sent))
    for text_in, cat in ex["objections"].items():
        r = tools["objection_help"](ctx, text_in)
        add(f"objection '{text_in}' -> {cat}", r["category"] == cat and r["playbook"], r["category"])
    r = tools["objection_help"](ctx, ex["competitor_positioning_for"])
    add("competitor positioning attached", r["competitor_positioning"] and r["competitor_positioning"][0]["name"] == "Acme Intel",
        r["competitor_positioning"])
    p = tools["proposal_outline"](ctx, "deal-northwind")
    add("proposal flags missing inputs", set(ex["proposal_missing_northwind"]) <= set(p["missing"]) and not p["ready_to_send"],
        p["missing"])
    add("proposal never invents: missing sections carry a question",
        all(s["content"].startswith("MISSING") for s in p["sections"] if s["missing"]), p["sections"])
    for did in ex["proposal_ready"]:
        p2 = tools["proposal_outline"](ctx, did)
        add(f"{did} proposal ready", p2["ready_to_send"], p2["missing"])
    q = tools["meddpicc_questions"](ctx, "deal-northwind")
    add("questions for every gap", q["gaps"] and all(len(g["questions"]) >= 2 for g in q["gaps"]), [g["element"] for g in q["gaps"]])
    ns = eng.next_steps(ctx, ctx.store.get("deals", ex["next_steps_overdue"]), now)
    add("next steps mark overdue items", any(i["overdue"] for i in ns["items"]) and any("overdue" in f for f in ns["flags"]),
        ns["flags"])
    return out
