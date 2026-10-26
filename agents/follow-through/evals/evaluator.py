"""Follow-Through evaluator: trigger facts, decisions, tee-up effects, SLAs, dedupe and engine parity."""
from __future__ import annotations

import json
from datetime import datetime

from gtm_core import engagement, rules
from gtm_core.agents import load_module
from gtm_core.executors import register_core_executors


def seed(ctx, spec: dict) -> None:
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for aid, tier in spec.get("scores", {}).items():
        ctx.store.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
                         ("seed", "signal-scout", aid, 50, tier, spec["now"]))
    for i, aid in enumerate(spec.get("open_deals", [])):
        ctx.store.upsert("deals", {"id": f"d{i}", "account_id": aid, "name": f"{aid} deal", "owner": "Priya Shah",
                                   "stage": "evaluation", "status": "open", "amount": 50000})
    for c in spec["contacts"]:
        ctx.store.upsert("contacts", c)
        did = ctx.store.add_draft("icp-outbound", "first_touch", "Hi", subject="Hello", gate_score=36, gate_passed=True,
                                  source="template", status="sent", account_id=c["account_id"], contact_id=c["id"],
                                  meta={"owner": "Sam Rivera", "step": "first_touch"})
        engagement.record(ctx.store, c["email"], "sent", spec["sent_at"], did, "first_touch")
    for email, evs in spec["events"].items():
        for e in evs:
            engagement.record(ctx.store, email, e[0], e[1])


def evaluate(m, spec, make_ctx) -> list[dict]:
    out = []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    now = datetime.fromisoformat(spec["now"])
    ex = spec["expect"]
    eng = load_module(m, "engine")

    ctx = make_ctx(m)
    seed(ctx, spec)
    register_core_executors(ctx)
    res = {r["email"]: r for r in eng.evaluate_recent(ctx, now)["results"]}
    for email, want in ex["decisions"].items():
        r = res.get(email)
        got = (r["decision"]["output"].get("rule"), (r.get("result") or {}).get("action")) if r else None
        add(f"{email} -> {want['rule']} ({want['action']})", got == (want["rule"], want["action"]), got)
    for email, n in ex["human_opens"].items():
        add(f"{email} counts {n} human opens (machine opens dropped)", res[email]["facts"]["human_opens"] == n,
            res[email]["facts"]["human_opens"])
    teed = [e for e, w in ex["decisions"].items() if w["action"] == "tee_up"]
    stopped = {s["email"] for s in ctx.sequencer.stopped}
    add("every tee-up paused automation at once", set(teed) <= stopped, sorted(stopped))
    add("nothing else was paused", stopped <= set(teed), sorted(stopped - set(teed)))
    pending = [a for a in ctx.approvals.list("pending", all_agents=True) if a["action"] == "crm_task"]
    add("one CRM task waits for approval per tee-up", len(pending) == len(teed), len(pending))
    tasks = {t["contact_id"]: t for t in ctx.store.select("tasks", "source=?", ("follow-through",))}
    add("local AE task per tee-up, owned by the sender's AE",
        len(tasks) == len(teed) and all(t["owner"] == ex["owner"] for t in tasks.values()),
        [(k, t["owner"]) for k, t in tasks.items()])
    for email, due in ex["due"].items():
        got = (res[email].get("result") or {}).get("due_at")
        add(f"{email} due in business hours ({due})", got == due, got)
    briefs = [s["text"] for s in ctx.slack.sent]
    why_lines = [ln for b in briefs for ln in b.splitlines() if ln.startswith(("Why now", "Trigger"))]
    add("briefs never put opens or clicks in a sayable line",
        not any("open" in ln.lower() and "why now" in ln.lower() for ln in why_lines), why_lines)
    add("FYI for the open-deal contact changes nothing", "eve@adatum.example" not in stopped and
        any("FYI" in b and "Eve Kim" in b for b in briefs), "")

    again = eng.evaluate_email(ctx, "ben@contoso.example", now)
    add("second run does not tee up twice", again["decision"]["output"].get("rule") == ex["second_run_rule"]
        and len(eng.open_teeups(ctx)) == len(teed), again["decision"]["output"])
    closed = eng.resolve_teeup(ctx, "ben@contoso.example", "meeting_booked", now)
    add("resolving closes the tee-up and its task",
        closed["closed"] == 1 and ctx.store.get("tasks", tasks["c-ben"]["id"])["status"] == "done", closed)

    # the builtin and zen engines agree on every person
    if rules.zen_available():
        c2 = make_ctx(m)
        seed(c2, spec)
        t = eng.trigger_config(c2)[1]["engagement"]
        diffs = []
        for email in ex["decisions"]:
            f = {k: v for k, v in eng.facts_for(c2, email, now).items() if not k.startswith("_")}
            a, b = rules.evaluate(t, f, "builtin").output, rules.evaluate(t, f, "zen").output
            if a.get("rule") != b.get("rule"):
                diffs.append((email, a.get("rule"), b.get("rule")))
        add("builtin and zen engines pick the same rule for everyone", not diffs, diffs)
        jdm = rules.parse_table("jdm", {"jdm": spec["expect"]["jdm"]}, m.path("evals"))
        for email in ("ben@contoso.example", "dan@contoso.example", "fay@fabrikam.example", "gus@contoso.example"):
            f = {k: v for k, v in eng.facts_for(c2, email, now).items() if not k.startswith("_")}
            got = rules.evaluate(jdm, f).output.get("rule")
            add(f"GoRules JDM file decides {email} like the YAML table", got == ex["decisions"][email]["rule"], got)
    else:
        add("builtin and zen engines pick the same rule for everyone", True, "zen-engine not installed: skipped")

    try:
        rules.parse_table("bad", {"rules": [{"when": {"x": ">= "}, "then": {}}]})
        add("a broken cell is refused at load time", False, "loaded")
    except rules.RuleError as e:
        add("a broken cell is refused at load time", True, str(e))
    add("tee-up facts are stored for the audit trail",
        all(json.loads(r["facts"]) for r in ctx.store.query("SELECT facts FROM teeups")), "")
    return out
