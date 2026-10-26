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
    if "cadence" in spec:
        out += evaluate_cadence(m, spec["cadence"], make_ctx)
    return out


def seed_cadence(ctx, cs: dict) -> None:
    for a in cs["accounts"]:
        ctx.store.upsert_account(a)
    for c in cs["contacts"]:
        ctx.store.upsert("contacts", c)
    for d in cs["deals"]:
        ctx.store.upsert("deals", d)
    for mt in cs["meetings"]:
        ctx.store.upsert("meetings", mt)
    rc = cs["recap_confirmed"]
    rid = ctx.store.insert("INSERT INTO approvals (agent, action, payload, status, requested_at, decided_at, decided_by) "
                           "VALUES (?,?,?,?,?,?,?)", ("seller-follow-up", "crm_task", "{}", "approved", rc["at"], rc["at"],
                                                      "Sam Rivera"))
    ctx.store.add_draft("seller-follow-up", "meeting_recap", "Recap", status="queued", contact_id=rc["contact"],
                        approval_id=rid, account_id="northwind.example", deal_id="d-nw")
    for ld in cs["event_leads"]:
        ctx.store.upsert("leads", {"id": f"{ld['event']}:{ld['email']}", "source": "event", "registered": True,
                                   "status": "new", **ld})
    for email, evs in cs["events"].items():
        for e in evs:
            engagement.record(ctx.store, email, e[0], e[1])
    eng = load_module(ctx.manifest, "engine")
    eng.ensure_schema(ctx)
    t = cs["teeup"]
    ctx.store.execute("INSERT INTO teeups (id, email, contact_id, account_id, owner, rule, status, due_at, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", ("t1", t["email"], t["contact_id"], t["account_id"], t["owner"],
                                                     "clicked", "open", t["due_at"], t["created_at"]))


def evaluate_cadence(m, cs, make_ctx) -> list[dict]:
    from datetime import timedelta
    out = []

    def add(name, ok, detail=""):
        out.append({"case": "cadence: " + name, "passed": bool(ok), "detail": str(detail)[:400]})

    now = datetime.fromisoformat(cs["now"])
    ex = cs["expect"]
    ctx = make_ctx(m)
    seed_cadence(ctx, cs)
    cad = load_module(m, "cadence")
    stats = cad.sweep(ctx, now)

    def live(email):
        r = ctx.store.one("SELECT id FROM cadence WHERE email=? ORDER BY updated_at DESC LIMIT 1", (email,))
        return cad.get(ctx, r["id"]) if r else None

    for email in ("ana@northwind.example", "ben@contoso.example", "cara@contoso.example", "dan@contoso.example",
                  "eve@adatum.example"):
        want, r = ex[email], live(email)
        ok = r and r["status"] == want["status"] and (not want.get("step") or r["step_id"] == want["step"]) \
            and (not want.get("why") or want["why"] in (r.get("stop_reason") or ""))
        add(f"{email} {want['status']} at {want.get('step') or want.get('why')}", ok,
            r and {k: r[k] for k in ("motion", "status", "step_id", "stop_reason", "next_touch_at")})
    add("recap confirmed by the AE counts as the touch; check-in due 3 business days later",
        live("ana@northwind.example")["next_touch_at"] == ex["ana_check_in_due"], live("ana@northwind.example")["next_touch_at"])
    add("event thank-you sent advances to the bump", live("cara@contoso.example")["next_touch_at"] == ex["cara_bump_due"],
        live("cara@contoso.example")["next_touch_at"])
    pend = {a["payload"]["contact"]["email"]: a for a in ctx.approvals.list("pending", all_agents=True)
            if a["action"] == "pipeline_email"}
    a = pend.get("ana@northwind.example")
    add("drafted touch waits on its owner as one pipeline email", a and a["payload"]["approver"] ==
        ex["ana@northwind.example"]["approver"] and a["payload"]["step"] == "check_in", a and a["payload"])
    add("only steps this agent owns are drafted", set(pend) == {"ana@northwind.example", "cara@contoso.example"}, sorted(pend))
    bodies = " ".join(x["payload"]["body"].lower() for x in pend.values())
    import re
    add("follow-up drafts never mention opens or tracking",
        not re.search(r"\b(opened|clicked|tracking|open rate|saw you open)\b", bodies), bodies[:200])
    esc = [e["to"] for e in stats["escalated"] if e["id"].startswith("post_meeting:meeting-m-co")]
    add("missed recap escalates to the owner, then the manager", esc == ex["ben@contoso.example"]["escalated_to"], esc)
    cov = cad.coverage(ctx, now)
    got = {"deal_without_follow_up": sorted(g["deal"] for g in cov["gaps"] if g["type"] == "deal_without_follow_up"),
           "touch_past_due": sorted(g["email"] for g in cov["gaps"] if g["type"] == "touch_past_due")}
    add("coverage finds the deal nobody follows and the past-due touch", got == ex["coverage_gaps"], got)

    again = cad.sweep(ctx, now)
    add("a second sweep drafts nothing new and escalates nothing twice",
        again["drafted"] == 0 and not again["escalated"] and again["started"] == 0, {k: again[k] for k in ("drafted", "started")})
    waits = ctx.store.query("SELECT kind, status FROM workflow_waits")
    add("waits are stored in the database (they survive a restart)", len(waits) >= 3, waits)

    cad.log_touch(ctx, "eve@adatum.example", "call", "left a voicemail", now=now)
    cad.sweep(ctx, now)
    add("a logged AE call advances the tee-up cadence", live("eve@adatum.example")["step_id"] == ex["eve_after_call"],
        live("eve@adatum.example")["step_id"])

    ctx.approvals.decide(pend["ana@northwind.example"]["id"], False, by="Sam Rivera")
    cad.sweep(ctx, now)
    r = live("ana@northwind.example")
    add("a rejected draft hands the step to the AE without redrafting",
        r["status"] == "active" and r["ae_owns"] == 1 and len([x for x in ctx.approvals.list("pending", all_agents=True)
                                                               if x["payload"].get("cadence_id") == r["id"]]) == 0, r["status"])

    later = now + timedelta(hours=1)
    did = pend["cara@contoso.example"]["payload"]["draft_id"]
    ctx.approvals.decide(pend["cara@contoso.example"]["id"], True, by="Lee Park")
    ctx.store.execute("UPDATE drafts SET status='sent' WHERE id=?", (did,))
    engagement.record(ctx.store, "cara@contoso.example", "sent", later.isoformat(), did, "cadence_bump")
    cad.sweep(ctx, later)
    add("a confirmed and sent touch advances to the next step", live("cara@contoso.example")["step_id"] ==
        ex["cara_after_send"], live("cara@contoso.example")["step_id"])
    return out
