"""Seller Follow-Up evaluator: detection, no-spam rules, recap building, approvals."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    st = ctx.store
    for a in spec.get("accounts", []):
        st.upsert_account(a)
    for kind in ("contacts", "deals", "tasks", "leads", "meetings"):
        for r in spec.get(kind, []):
            st.upsert(kind, r)
    for lid in spec.get("sent_lead_drafts", []):
        st.add_draft("lead-triage", "lead_follow_up", "body", status="sent", lead_id=lid)
    eng = load_module(m, "engine")
    jobs = load_module(m, "jobs")
    now = datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": detail})

    raw = eng.collect(ctx, now)
    ids = {i["item_id"] for i in raw} | {x for i in raw for x in i.get("merged", [])}
    for iid in ex["items_present"]:
        add(f"detects {iid}", iid in ids, "")
    for iid in ex["items_absent"]:
        add(f"ignores {iid}", iid not in ids, "")
    per = eng.due_now(ctx, now)
    for owner, cap in ex["max_per_owner"].items():
        add(f"{owner} capped at {cap}", len(per.get(owner, [])) == cap, f"got {len(per.get(owner, []))}")
    deal_lines = [i for i in per.get("Sam Rivera", []) if i.get("deal_id") == ex["one_line_per_deal"] and i["kind"] != "no_recap"]
    add("one digest line per deal", len(deal_lines) == 1 and deal_lines[0].get("also"), str([i["title"] for i in deal_lines]))

    first = eng.due_now(ctx, now, mark=True)
    again = eng.due_now(ctx, now)
    shown = {i["item_id"] for v in first.values() for i in v}
    repeated = shown & {i["item_id"] for v in again.values() for i in v}
    add("cooldown: nothing repeats the same day", shown and not repeated, f"{len(repeated)} repeated")
    eng.snooze(ctx, "lead:l-late", 5, now)
    later = eng.due_now(ctx, datetime.fromisoformat("2026-10-27T12:00:00+00:00"))
    add("snoozed item stays hidden", all(i["item_id"] != "lead:l-late" for v in later.values() for i in v), "")

    ctx.handoffs.send("seller-follow-up", "meeting_recap", spec["recap_handoff"]["meeting_id"], spec["recap_handoff"])
    res = jobs.process_recaps(ctx, now)
    add("recap handoff consumed", res["recaps"] == 1 and not ctx.handoffs.pending("meeting_recap"), str(res))
    d = st.drafts(agent=m.id)[0]
    add("recap passes Copy QA Gate", d["gate_passed"] == 1, f"{d['gate_score']}/40")
    add("recap only to buyer attendees", d["meta"]["to"] == ex["recap_to"], str(d["meta"]["to"]))
    add("recap uses only call facts", all(w.lower() in d["body"].lower() for w in ex["recap_mentions"]), d["body"][:200])
    acts = [a["action"] for a in ctx.approvals.list()]
    add("recap queues send task, deal note and one task per step", acts == ex["recap_approvals"], str(acts))
    tasks = {a["payload"]["subject"]: a["payload"]["due_at"] for a in ctx.approvals.list() if a["action"] == "crm_task"}
    for text, due in ex["recap_due"].items():
        add(f"next step due {due}: {text[:30]}", tasks.get(text) == due, str(tasks))
    return out
