import json
from datetime import datetime, timezone

from gtm_core.agents import load_module
from gtm_core.executors import register_core_executors
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)


def _seed(ctx):
    ctx.store.upsert_account({"id": "nw.example", "name": "Northwind", "domain": "nw.example", "crm_id": "1"})
    ctx.store.upsert("contacts", {"id": "dana@nw.example", "email": "dana@nw.example", "name": "Dana Cole",
                                  "crm_id": "c1", "account_id": "nw.example", "owner": "Sam Rivera"})


def test_opt_out_is_local_at_once_and_stop_executes(ctx_for):
    ctx = ctx_for("reply-desk")
    _seed(ctx)
    tools = bind_tools(ctx)
    r = tools["add_reply"](from_email="dana@nw.example", from_name="Dana Cole", body="Stop emailing me.")
    assert r["class"] == "unsubscribe"
    assert ctx.store.get("contacts", "dana@nw.example")["do_not_contact"] is True
    register_core_executors(ctx)
    for a in ctx.approvals.list():
        ctx.approvals.decide(a["id"], True)
    ctx.approvals.execute_approved()
    assert ctx.sequencer.stopped[0]["email"] == "dana@nw.example"
    assert ctx.crm.writes[-1] == {"kind": "contact_update", "crm_id": "c1", "fields": {"gtm_do_not_contact": True}}


def test_model_can_never_override_an_opt_out(ctx_for, monkeypatch):
    from gtm_core import writer
    ctx = ctx_for("reply-desk")
    eng = load_module(ctx.manifest, "engine")
    monkeypatch.setattr(writer, "extract", lambda *a, **k: {"class": "positive", "category": None, "evidence": "x"})
    c = eng.classify("Please remove me.", now=NOW)
    assert eng.refine_with_model(ctx, c, "Please remove me.")["class"] == "unsubscribe"
    low = eng.classify("Got it.", now=NOW)
    assert eng.refine_with_model(ctx, low, "Got it.")["class"] == "positive"  # low confidence may be refined


def test_inbox_job_and_digest(ctx_for, tmp_path):
    ctx = ctx_for("reply-desk")
    _seed(ctx)
    inbox = tmp_path / "inbox"; inbox.mkdir()
    (inbox / "r.json").write_text(json.dumps([
        {"from_email": "dana@nw.example", "from_name": "Dana Cole", "subject": "Re: hi", "body": "Happy to chat, send times.",
         "received_at": "2026-10-23T14:00:00+00:00"},
        {"from_email": "dana@nw.example", "from_name": "Dana Cole", "subject": "Re: hi", "body": "Happy to chat, send times.",
         "received_at": "2026-10-23T14:00:00+00:00"},
        {"from_email": "x@nw.example", "subject": "Automatic reply", "body": "Out of office until Nov 2.",
         "received_at": "2026-10-23T14:05:00+00:00"}]))
    ctx.manifest.config["reply_inbox"] = str(inbox)
    jobs = load_module(ctx.manifest, "jobs")
    res = jobs.process_replies(ctx, now=NOW)
    assert {k: res["inbox"][k] for k in ("files", "replies")} == {"files": 1, "replies": 2} and res["classes"] == {"positive": 1, "out_of_office": 1}
    assert any("replied interested" in m["text"] for m in ctx.slack.sent)
    d = jobs.reply_digest(ctx, now=NOW)
    assert d["owners"] == 1 and any("Reply Desk for Sam Rivera" in m["text"] for m in ctx.slack.sent)
    assert jobs.process_replies(ctx, now=NOW)["handled"] == 0


def test_needing_action_lists_interested_first(ctx_for):
    ctx = ctx_for("reply-desk")
    _seed(ctx)
    tools = bind_tools(ctx)
    tools["add_reply"](from_email="a@nw.example", body="Got it.")
    tools["add_reply"](from_email="dana@nw.example", body="Sounds good, let's talk.")
    out = tools["replies_needing_action"](days=36500)
    assert [r["class"] for r in out["replies"]][:2] == ["positive", "neutral"]


def test_business_hours_sla_rolls_over_weekend():
    import importlib.util
    spec = importlib.util.spec_from_file_location("rd_engine", "agents/reply-desk/engine.py")
    eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
    fri_late = datetime(2026, 10, 23, 20, 30, tzinfo=timezone.utc)  # 16:30 New York on a Friday
    due = eng.add_business_hours(fri_late, 2, "America/New_York")
    assert due == datetime(2026, 10, 26, 14, 30, tzinfo=timezone.utc)  # Monday 10:30 New York


def test_greeting_then_yes_and_send_times_is_positive():
    import sys
    from gtm_core.agents import Manifest, load_module
    eng = load_module(Manifest.load("agents/reply-desk"), "engine")
    for text in ["Hi Sam, yes this is timely. Can you send a couple of times for next Tuesday?",
                 "Thanks Sam. Sure, send over a few options.", "Can you send some times next week?"]:
        assert eng.classify(text)["class"] == "positive", text
    assert eng.classify("Hi Sam, not interested, thanks.")["class"] == "objection"


def test_opt_out_blocks_every_other_send(ctx_for, manifests):
    """An opt-out rejects pending sends, stops sequences at once, and later sends are skipped at run time."""
    from gtm_core import suppression
    ctx = ctx_for("reply-desk")
    _seed(ctx)
    pending = ctx.request_approval("sequence_enroll", {"contact": {"email": "dana@nw.example"},
                                                       "steps": [{"subject": "s", "body": "b"}]})
    bind_tools(ctx)["add_reply"](from_email="dana@nw.example", body="Hi Sam,\nThanks.\nPlease remove me from your list.")
    assert ctx.store.one("SELECT status FROM approvals WHERE id=?", (pending,))["status"] == "rejected"
    assert ctx.sequencer.stopped and ctx.sequencer.stopped[0]["email"] == "dana@nw.example"  # no human needed
    assert suppression.is_suppressed(ctx.store, "dana@nw.example")
    # a send approved later (e.g. by another agent) is skipped when it executes
    register_core_executors(ctx)
    late = ctx.request_approval("sequence_enroll", {"contact": {"email": "dana@nw.example"}, "steps": []})
    ctx.approvals.decide(late, True)
    res = [r for r in ctx.approvals.execute_approved() if r["id"] == late][0]
    assert res["result"]["skipped"].startswith("suppressed") and not ctx.sequencer.sent
    # other agents' pickers skip her too
    out = load_module(manifests["icp-outbound"], "engine")
    from gtm_core.agents import Context
    octx = Context.build(ctx.settings, manifests["icp-outbound"], store=ctx.store, crm=ctx.crm, slack=ctx.slack,
                         sequencer=ctx.sequencer, dialer=ctx.dialer)
    ctx.store.upsert("contacts", {"id": "dana@nw.example", "title": "VP Sales"})
    assert all(p["email"] != "dana@nw.example" for p in out.pick_contacts(octx, ctx.store.account("nw.example")))


def test_bad_inbox_file_is_quarantined_and_the_next_file_still_runs(ctx_for, tmp_path):
    ctx = ctx_for("reply-desk")
    _seed(ctx)
    inbox = tmp_path / "replies" / "inbox"; inbox.mkdir(parents=True)
    (inbox / "a-broken.json").write_text('[{"from_email": "x@nw.example", "body": ')
    (inbox / "b-list.json").write_text(json.dumps([{"from_email": "y@nw.example", "subject": ["a", "b"], "body": "Remove me"}]))
    (inbox / "c-cp1252.csv").write_bytes("from_email,body\nz@nw.example,Caf\xe9 is closed. Please remove me\n".encode("cp1252"))
    (inbox / "d-good.json").write_text(json.dumps([{"from_email": "dana@nw.example", "body": "Please remove me."}]))
    ctx.manifest.config["reply_inbox"] = str(inbox)
    res = load_module(ctx.manifest, "jobs").process_replies(ctx, now=NOW)
    assert res["inbox"]["failed_files"] == ["a-broken.json"]
    assert res["inbox"]["replies"] == 3 and (tmp_path / "replies" / "failed" / "a-broken.json").exists()
    assert ctx.store.get("contacts", "dana@nw.example")["do_not_contact"] is True


def test_redropped_reply_without_timestamp_is_not_handled_twice(ctx_for):
    ctx = ctx_for("reply-desk")
    _seed(ctx)
    eng = load_module(ctx.manifest, "engine")
    row = {"from_email": "dana@nw.example", "body": "Happy to chat, send times."}
    assert eng.ingest_row(ctx, row, NOW)
    assert eng.ingest_row(ctx, row, datetime(2026, 10, 24, tzinfo=timezone.utc)) is None
    a = {"from_email": "dana@nw.example", "body": "ok", "received_at": "2026-10-23T14:00:00+00:00"}
    b = {"from_email": "dana@nw.example", "body": "ok", "received_at": "2026-10-23T09:00:00-05:00"}
    assert eng.ingest_row(ctx, a, NOW) and eng.ingest_row(ctx, b, NOW) is None


def test_referral_intro_is_addressed_to_the_referred_person(ctx_for):
    ctx = ctx_for("reply-desk")
    _seed(ctx)
    bind_tools(ctx)["add_reply"](from_email="dana@nw.example", from_name="Dana Cole",
                                 body="I'm not the right person. Please contact Priya Nair at priya@nw.example.")
    d = [x for x in ctx.store.drafts() if x["kind"] == "reply_referral"][0]
    assert d["meta"]["to"] == "priya@nw.example"
