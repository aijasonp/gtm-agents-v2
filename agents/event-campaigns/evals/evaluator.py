"""Event Campaigns evaluator: invite targeting, guards, drafting, attendee import, report and jobs."""
from __future__ import annotations

from datetime import datetime, timedelta

from gtm_core.agents import load_module


def setup(ctx, spec):
    st = ctx.store
    for a in spec["accounts"]:
        st.upsert_account(a)
    for s in spec["scores"]:
        st.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
                  ("r", "signal-scout", s["account_id"], s["score"], s["tier"], spec["now"]))
    for c in spec["contacts"]:
        st.upsert("contacts", c)
    for d in spec["deals"]:
        st.upsert("deals", d)


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    setup(ctx, spec)
    eng = load_module(m, "engine")
    jobs = load_module(m, "jobs")
    now = datetime.fromisoformat(spec["now"])
    ev_id, ex, out = spec["event"], spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    lst = eng.build_invite_list(ctx, ev_id, now)
    order = [a["account_id"] for a in lst["accounts"]]
    add("invite order", order == ex["invite_order"], order)
    got = {a["account_id"]: [c["name"] for c in a["contacts"]] for a in lst["accounts"]}
    add("invite contacts (personas, suppression)", got == ex["invite_contacts"], got)
    exc = {e["account_id"]: " ".join(e["reasons"]) for e in lst["excluded"]}
    for aid, why in ex["excluded"].items():
        add(f"{aid} skipped: {why}", why in exc.get(aid, ""), exc.get(aid))
    add("invite cap = capacity x multiplier", lst["cap"] == ex["cap"], lst["cap"])

    d = eng.draft_invites(ctx, ev_id, 20, now)
    add("drafted invites", d["drafted"] == ex["drafted"], d["drafted"])
    add("each invite queued as its own approval", d["queued"] == ex["queued"] and len(ctx.approvals.list()) == ex["queued"],
        d["queued"])
    appr = ctx.approvals.list()
    add("approval campaign is the event id", all(a["payload"]["campaign"] == ev_id and a["action"] == "sequence_enroll"
                                                 for a in appr), [a["payload"]["campaign"] for a in appr])
    add("all invites pass the Copy QA Gate", all(x["gate_passed"] for x in d["drafts"]), [x["gate_score"] for x in d["drafts"]])
    add("invite carries the registration link",
        all("events.beacon.example/chicago-dinner" in x["body"] for x in d["drafts"]), "")
    again = eng.draft_invites(ctx, ev_id, 20, now)
    add("no second invite to the same person", again["drafted"] == 0 and len(again["skipped"]) == ex["redraft_skipped"],
        again)
    past = eng.build_invite_list(ctx, ev_id, now + timedelta(days=30))
    add("no invites after the event", "error" in past, past.get("error"))

    imp = eng.import_attendees(ctx, ev_id, rows=spec["attendees"], now=now)
    got = {k: imp[k] if k != "errors" else len(imp[k]) for k in ex["import"]}
    add("attendee import", got == ex["import"], imp)
    lead = ctx.store.get("leads", eng.lead_key(ev_id, "dana@northwind.example"))
    add("attendee lead tagged with event and routed as new", lead["event"] == ev_id and lead["status"] == "new"
        and lead["account_id"] == "northwind.example", lead)
    sig = ctx.store.signals_for("northwind.example")
    add("attendance adds event_attended signal", [s["signal_type"] for s in sig] == ["event_attended"], sig)
    re = eng.import_attendees(ctx, ev_id, rows=spec["attendees"], now=now)
    add("re-import updates, never duplicates", re["updated"] == ex["reimport_updated"] and re["added"] == 0
        and re["signals_added"] == 0, re)

    for o in spec["after_event"]["outcomes"]:
        ctx.store.add_outcome(o["account_id"], o["outcome"], observed_at=o["observed_at"])
    for dl in spec["after_event"]["deals"]:
        ctx.store.upsert("deals", dl)
    rep = eng.event_report(ctx, ev_id)
    got = {k: rep[k] for k in ex["report"]}
    add("event report", got == ex["report"], rep)

    r = jobs.event_reminders(ctx, now=datetime.fromisoformat("2026-11-08T12:00:00+00:00"))
    add("reminders go to registrants only", r["reminders"].get(ev_id) == ex["reminder_registrants"], r)
    f = jobs.post_event_followups(ctx, now=datetime.fromisoformat("2026-11-13T12:00:00+00:00"))
    add("post-event follow-ups split attended vs missed", f["followups"].get(ev_id) == ex["followups"], f)
    add("event report posted once", "Revenue Leaders Dinner" in ctx.slack.sent[-1]["text"], ctx.slack.sent[-1]["text"])
    n = len(ctx.slack.sent)
    jobs.post_event_followups(ctx, now=datetime.fromisoformat("2026-11-14T12:00:00+00:00"))
    add("report not reposted", len(ctx.slack.sent) == n, len(ctx.slack.sent) - n)
    return out
