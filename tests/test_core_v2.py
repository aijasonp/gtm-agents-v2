"""Tests for the shared pieces the 8 workflow agents use."""
import json
from datetime import datetime, timezone

import httpx

from gtm_core import meddpicc, personas, pipeline, transcripts, writer
from gtm_core.approvals import Approvals
from gtm_core.connectors.hubspot import HubSpot
from gtm_core.connectors.sequencer import SmartleadSequencer, WebhookSequencer
from gtm_core.executors import register_core_executors
from gtm_core.gateway import Gateway
from gtm_core.store import Store
from gtm_core.sync import upsert_deal


def test_record_upsert_merges_attrs():
    st = Store("sqlite:///:memory:"); st.init()
    st.upsert("deals", {"id": "d1", "name": "Pilot", "stage": "discovery", "region": "west", "meddpicc": {"metrics": "cut 3 hrs"}})
    st.upsert("deals", {"id": "d1", "amount": 50000, "segment": "mid"})
    d = st.get("deals", "d1")
    assert d["name"] == "Pilot" and d["amount"] == 50000 and d["region"] == "west" and d["segment"] == "mid"
    assert d["meddpicc"] == {"metrics": "cut 3 hrs"}


def test_handoffs_dedupe_and_consume(ctx_for):
    ctx = ctx_for("signal-scout")
    a = ctx.handoffs.send("seller-follow-up", "meeting_recap", "m1", {"x": 1})
    assert ctx.handoffs.send("seller-follow-up", "meeting_recap", "m1") is None
    from gtm_core.handoffs import Handoffs
    recv = Handoffs(ctx.store, "seller-follow-up")
    assert [h["id"] for h in recv.pending()] == [a]
    recv.consume(a)
    assert recv.pending() == []


def test_personas():
    assert personas.seniority("VP of Sales Development") == "vp"
    assert personas.seniority("Chief Revenue Officer") == "c_level"
    assert personas.function("Director, Revenue Operations") == "revops"
    m = personas.persona_match("Head of Sales", ["sales", "revops"], "director")
    assert m["match"] and m["seniority"] == "vp"
    assert not personas.persona_match("Sales Intern", ["sales"], "manager")["match"]


def test_transcript_parse_and_analyze():
    raw = """WEBVTT

00:00:01.000 --> 00:00:05.000
<v Sam Rep>Thanks for joining. What made you take the call?</v>

00:00:06.000 --> 00:00:20.000
<v Dana Buyer>Our reps build lists manually and it takes forever. We already use Acme Intel but it is too expensive.</v>

00:10:00.000 --> 00:10:09.000
<v Sam Rep>Great. Next step: I'll send over a pilot plan by Friday. Who signs off on budget?</v>

00:10:10.000 --> 00:10:15.000
<v Dana Buyer>Our CFO has final say. Procurement needs a security review.</v>
"""
    turns = transcripts.parse(raw)
    assert [t.speaker for t in turns] == ["Sam Rep", "Dana Buyer", "Sam Rep", "Dana Buyer"]
    a = transcripts.analyze(turns, rep_names=["Sam"], competitors=["Acme Intel"])
    assert a.duration_min == 10.2
    assert "Acme Intel" in a.competitors
    assert "price" in a.objections
    assert a.next_steps
    for e in ("identify_pain", "economic_buyer", "paper_process", "competition"):
        assert e in a.meddpicc_evidence, e


def test_plain_transcript_format():
    turns = transcripts.parse("Sam: hello there\nDana: hi. we struggle with routing\ncontinued line\nDana: second")
    assert len(turns) == 2 and "continued line" in turns[1].text and "second" in turns[1].text


def test_meddpicc_gaps_and_merge():
    raw = {"identify_pain": "confirmed: lists take 6 hours a week", "metrics": "save time"}
    assert meddpicc.score(raw)["total"] == 3
    g = {x["element"] for x in meddpicc.gaps(raw, "Proposal Sent")}
    assert {"metrics", "champion", "economic_buyer", "paper_process"} <= g
    merged = meddpicc.merge_evidence(raw, {"champion": ["Dana: I'll push this internally"]}, "call")
    assert merged["champion"]["score"] == 1 and merged["identify_pain"]["score"] == 2


def test_pipeline_slips_and_weighted():
    h = [{"close_date": "2026-09-30"}, {"close_date": "2026-10-31"}, {"close_date": "2026-10-31"}, {"close_date": "2026-11-30"}]
    assert pipeline.slips(h) == 2
    deals = [{"stage": "proposal", "amount": 100, "status": "open"}, {"stage": "closed won", "amount": 500, "status": "won"}]
    assert pipeline.weighted(deals) == 60.0
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    assert pipeline.days_since("2026-10-13", now) == 10


def test_deal_stage_tracking(ctx_for):
    ctx = ctx_for("signal-scout")
    upsert_deal(ctx, {"id": "d1", "stage": "discovery", "created_at": "2026-09-01"}, "2026-09-01T00:00:00+00:00")
    upsert_deal(ctx, {"id": "d1", "stage": "discovery"}, "2026-09-10T00:00:00+00:00")
    assert ctx.store.get("deals", "d1")["stage_entered_at"] == "2026-09-01"
    upsert_deal(ctx, {"id": "d1", "stage": "evaluation"}, "2026-10-01T00:00:00+00:00")
    assert ctx.store.get("deals", "d1")["stage_entered_at"] == "2026-10-01T00:00:00+00:00"
    assert len(ctx.store.deal_history("d1")) == 3


def test_writer_template_path(ctx_for):
    ctx = ctx_for("copy-qa-gate")
    d = writer.write(ctx, "email", {"name": "Dana"}, "short note",
                     "Subject: quick idea\nHi Dana,\n\nSaw the new SDR team. Worth 15 minutes Tuesday?\n\nSam")
    assert d.source == "template" and d.subject == "quick idea" and d.passed


def _fake_gateway(ctx, replies):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        text = replies[min(len(calls) - 1, len(replies) - 1)]
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}],
                                         "usage": {"input_tokens": 100, "output_tokens": 50}})
    ctx.settings.anthropic_api_key = "test-key"; ctx.settings.offline = False
    ctx.gateway = Gateway(ctx.settings, ctx.budgets, ctx.manifest.id, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return calls


def test_writer_rewrites_until_gate_passes(ctx_for):
    ctx = ctx_for("copy-qa-gate")
    calls = _fake_gateway(ctx, [
        "Subject: hi\nI hope this email finds you well! We leverage cutting-edge AI to unlock 10x growth! Call? Now?",
        "Subject: your SDR list\nHi Dana,\n\nSaw you are hiring four SDRs. We rank accounts each morning so new reps start on the right ones.\n\nWorth 15 minutes Tuesday?\n\nSam",
    ])
    d = writer.write(ctx, "email", {"name": "Dana"}, "first touch", "Subject: x\nfallback?")
    assert d.source == "model" and d.passed and d.attempts == 2 and len(calls) == 2
    assert "Failures:" in calls[1]["messages"][0]["content"]
    assert ctx.budgets.usage()["tokens_today"] == 300


def test_writer_extract_parses_json(ctx_for):
    ctx = ctx_for("copy-qa-gate")
    _fake_gateway(ctx, ['Here you go:\n```json\n{"champion": "Dana"}\n```'])
    assert writer.extract(ctx, "find champion", "text", "{champion}") == {"champion": "Dana"}


def test_core_executors_and_sequencer(ctx_for):
    ctx = ctx_for("signal-scout")
    register_core_executors(ctx)
    did = ctx.store.add_draft("icp-outbound", "first_touch", "body", subject="s")
    rid = ctx.request_approval("sequence_enroll", {"contact": {"email": "a@b.example", "name": "A B"},
                                                   "steps": [{"subject": "s", "body": "body"}], "draft_ids": [did]},
                               summary="enroll A B")
    rid2 = ctx.request_approval("crm_task", {"subject": "Follow up", "deal_crm_id": "123"})
    for r in (rid, rid2):
        ctx.approvals.decide(r, True)
    res = ctx.approvals.execute_approved()
    assert all("result" in r for r in res), res
    assert ctx.sequencer.sent[0]["contact"]["email"] == "a@b.example"
    assert ctx.crm.writes[-1]["kind"] == "task"
    assert ctx.store.drafts()[0]["status"] == "sent"
    assert any("Approval #" in m["text"] for m in ctx.slack.sent)


def test_approvals_scoped_per_agent():
    st = Store("sqlite:///:memory:"); st.init()
    Approvals(st, "a").request("x", {})
    Approvals(st, "b").request("y", {})
    assert len(Approvals(st, "a").list()) == 1
    assert len(Approvals(st, "a").list(all_agents=True)) == 2


def test_webhook_and_smartlead_payloads():
    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    WebhookSequencer("https://hooks.example/x", client=client).enroll({"email": "a@b.example"}, [{"subject": "s", "body": "b"}])
    SmartleadSequencer("k", "77", client=client).enroll({"email": "a@b.example", "name": "Ann Lee"}, [{"subject": "s", "body": "b"}])
    assert seen[0][1]["event"] == "sequence_enroll"
    assert "/campaigns/77/leads" in seen[1][0]
    lead = seen[1][1]["lead_list"][0]
    assert lead["first_name"] == "Ann" and lead["custom_fields"]["gtm_body_1"] == "b"


def test_hubspot_task_payload():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "9"})
    hs = HubSpot("t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    hs.create_task("Send recap", "body", "2026-10-24", deal_crm_id="55")
    assert seen[0]["properties"]["hs_task_subject"] == "Send recap"
    assert seen[0]["associations"][0]["types"][0]["associationTypeId"] == 216


def test_bad_signal_date_never_poisons_scoring(ctx_for, tmp_path):
    from gtm_core.importers import import_signals
    from gtm_core.agents import load_module
    ctx = ctx_for("signal-scout")
    ctx.store.upsert_account({"id": "a.example", "name": "A", "industry": "Software", "employees": 300, "country": "US"})
    f = tmp_path / "s.csv"
    f.write_text("account_id,signal_type,observed_at,url\na.example,funding_round,2026/10/20,u1\n"
                 "a.example,hiring_buyer_team,garbage,u2\na.example,pricing_page_visit,1761868800000,u3\n")
    assert import_signals(ctx, f) == {"added": 2, "duplicates": 0, "unknown_types": 0, "invalid": 1}
    assert all("T" in s["observed_at"] for s in ctx.store.signals_for("a.example"))
    load_module(ctx.manifest, "jobs").daily_sweep(ctx)  # no crash


def test_double_execute_is_impossible(ctx_for):
    from gtm_core.approvals import executor
    ctx = ctx_for("signal-scout")
    calls = []
    executor("count_me")(lambda p: calls.append(1) or {"ok": True})
    rid = ctx.approvals.request("count_me", {})
    ctx.approvals.decide(rid, True)
    ctx.approvals.execute_approved()
    ctx.store.execute("UPDATE approvals SET status='approved' WHERE id=? AND status='never'", (rid,))
    ctx.approvals.execute_approved()
    assert calls == [1]


def test_rejecting_marks_drafts_rejected(ctx_for):
    ctx = ctx_for("signal-scout")
    rid = ctx.approvals.request("sequence_enroll", {})
    did = ctx.store.add_draft("icp-outbound", "first_touch", "b", status="queued", approval_id=rid)
    ctx.approvals.decide(rid, False)
    assert ctx.store.drafts()[0]["status"] == "rejected" and ctx.store.drafts()[0]["id"] == did


def test_handoff_failure_retries_then_fails(ctx_for):
    from gtm_core.handoffs import Handoffs
    ctx = ctx_for("signal-scout")
    Handoffs(ctx.store, "a").send("b", "k", "r1")
    Handoffs(ctx.store, "a").send("b", "k", "r2")
    recv = Handoffs(ctx.store, "b")

    def boom(h):
        if h["ref"] == "r1":
            raise RuntimeError("bad")
        return h["ref"]
    out = recv.process("k", boom)
    assert out == {"processed": 1, "failed": 1, "results": ["r2"]}
    recv.process("k", boom); recv.process("k", boom)
    assert recv.all("failed")[0]["payload"]["_attempts"] == 3 and not recv.pending("k")


def test_budgets_are_per_agent(ctx_for):
    a, b = ctx_for("signal-scout"), ctx_for("copy-qa-gate")
    b.store = a.store
    from gtm_core.budgets import Budgets, BudgetExceeded
    import pytest
    ba = Budgets(a.store, daily_tokens=100, agent="signal-scout")
    bb = Budgets(a.store, daily_tokens=100, agent="copy-qa-gate")
    ba.record("signal-scout", "m", "cheap", 90, 20)
    with pytest.raises(BudgetExceeded):
        ba.check()
    bb.check()  # other agent unaffected


def test_upsert_none_clears():
    st = Store("sqlite:///:memory:"); st.init()
    st.upsert("meetings", {"id": "m", "processed_at": "2026-10-01", "title": "x"})
    st.upsert("meetings", {"id": "m", "processed_at": None})
    m = st.get("meetings", "m")
    assert m["processed_at"] is None and m["title"] == "x"


def test_suppression_blocks_sends_at_run_time(ctx_for):
    from gtm_core import suppression
    ctx = ctx_for("signal-scout")
    register_core_executors(ctx)
    ctx.store.upsert("contacts", {"id": "a@b.example", "email": "a@b.example", "name": "A"})
    pending = ctx.request_approval("sequence_enroll", {"contact": {"email": "a@b.example"}, "steps": []})
    approved = ctx.request_approval("dialer_enqueue", {"contact": {"email": "a@b.example", "phone": "+15555550100"}})
    ctx.approvals.decide(approved, True)
    out = suppression.suppress(ctx.store, "A@b.example", "opt-out")
    assert set(out["rejected_approvals"]) == {pending, approved}
    assert ctx.store.contact_by_email("a@b.example")["do_not_contact"] is True
    late = ctx.request_approval("sequence_enroll", {"contact": {"email": "a@b.example"}, "steps": []})
    ctx.approvals.decide(late, True)
    res = ctx.approvals.execute_approved()
    assert res[0]["result"]["skipped"].startswith("suppressed") and not ctx.sequencer.sent


def test_auto_safe_stop_runs_at_once(ctx_for):
    ctx = ctx_for("signal-scout")
    rid = ctx.request_approval("sequence_stop", {"email": "x@y.example", "reason": "opt-out"}, auto_safe=True)
    assert ctx.sequencer.stopped[0]["email"] == "x@y.example"
    assert ctx.store.one("SELECT status, decided_by FROM approvals WHERE id=?", (rid,)) == {"status": "executed", "decided_by": "auto:safety"}
    rid2 = ctx.request_approval("sequence_enroll", {"contact": {"email": "x@y.example"}}, auto_safe=True)
    assert ctx.store.one("SELECT status FROM approvals WHERE id=?", (rid2,))["status"] == "pending"  # sends never auto-run
