from datetime import datetime, timezone

import pytest

from gtm_core.agents import Context, Manifest, load_module
from gtm_core.connectors.base import NullCRM
from gtm_core.connectors.sequencer import Sequencer
from gtm_core.connectors.slack import Slack
from gtm_core.executors import register_core_executors
from gtm_core.mcp_server import bind_tools
from gtm_core.scoring import signal_id
from gtm_core.store import Store

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def ctx(settings):
    slack = Slack(settings)
    slack.post = lambda text, **kw: slack.sent.append({"text": text}) or {"ok": True}
    c = Context.build(settings, Manifest.load("agents/icp-outbound"), store=Store("sqlite:///:memory:"), crm=NullCRM(),
                      slack=slack, sequencer=Sequencer())
    st = c.store
    st.upsert_account({"id": "proseware.example", "name": "Proseware", "domain": "proseware.example",
                       "industry": "Software", "employees": 350, "country": "US"})
    st.upsert_account({"id": "northwind.example", "name": "Northwind", "domain": "northwind.example",
                       "industry": "Logistics", "employees": 600, "country": "US"})
    st.upsert("deals", {"id": "d1", "account_id": "northwind.example", "name": "NW", "stage": "Evaluation", "status": "open",
                        "owner": "Sam Rivera"})
    st.upsert("contacts", {"id": "omar", "email": "omar@proseware.example", "name": "Omar Haddad", "title": "VP of Sales",
                           "account_id": "proseware.example"})
    st.upsert("contacts", {"id": "dana", "email": "dana@northwind.example", "name": "Dana Cole", "title": "VP Sales",
                           "account_id": "northwind.example"})
    st.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
              ("r", "signal-scout", "proseware.example", 85, "A", NOW.isoformat()))
    st.add_signal({"id": signal_id("proseware.example", "funding_round", "b", "2026-10-15"), "account_id": "proseware.example",
                   "signal_type": "funding_round", "category": "money", "observed_at": "2026-10-15", "payload": {}})
    return c


def test_tools_and_conflicts(ctx):
    t = bind_tools(ctx)
    assert not t["check_conflicts"](account="northwind.example")["clear"]
    assert t["check_conflicts"](account="proseware.example")["clear"]
    assert t["why_now"](account="proseware.example")["signal"]["signal_type"] == "funding_round"
    assert t["pick_contacts"](account="proseware.example")["contacts"][0]["name"] == "Omar Haddad"
    lst = t["build_target_list"]()
    assert [a["account_id"] for a in lst["accounts"]] == ["proseware.example"]
    assert t["draft_sequence"](account="northwind.example")["skipped"]


def test_draft_sequence_queues_one_send_and_executes(ctx):
    out = bind_tools(ctx)["draft_sequence"](account="proseware.example")
    assert [s["step"] for s in out["steps"]] == ["first_touch", "bump", "breakup"]
    assert all(s["gate_passed"] for s in out["steps"])
    [appr] = ctx.approvals.list()
    assert appr["action"] == "sequence_enroll" and len(appr["payload"]["steps"]) == 3
    assert ctx.store.get("contacts", "omar")["outbound_queued_at"]
    register_core_executors(ctx)
    ctx.approvals.decide(appr["id"], True)
    ctx.approvals.execute_approved()
    assert ctx.sequencer.sent[0]["contact"]["email"] == "omar@proseware.example"
    # once sent, the account counts as recently contacted
    assert any("contacted in the last" in r for r in bind_tools(ctx)["check_conflicts"](account="proseware.example")["reasons"])


def test_jobs(ctx):
    jobs = load_module(ctx.manifest, "jobs")
    r = jobs.weekly_list_build(ctx, now=NOW)
    assert r["targets"] == 1 and r["active_pipeline_conflicts"] == 1
    assert "Skipped, active pipeline" in ctx.slack.sent[-1]["text"]
    assert jobs.daily_drafts(ctx, now=NOW)["drafted"] == 1
    assert jobs.daily_drafts(ctx, now=NOW)["drafted"] == 0  # never drafts the same contact twice


def test_person_signal_not_said_to_someone_else(ctx):
    st = ctx.store
    st.add_signal({"id": "s2", "account_id": "proseware.example", "signal_type": "new_exec_in_buyer_function",
                   "category": "leadership", "observed_at": "2026-10-20", "payload": {"title": "New CRO"}})
    eng = load_module(ctx.manifest, "engine")
    acct = st.account("proseware.example")
    a = eng.angle(ctx, acct, NOW, "VP of Sales", "Omar Haddad")
    assert a["signal"]["signal_type"] == "funding_round"
    st.add_signal({"id": "s3", "account_id": "proseware.example", "signal_type": "new_exec_in_buyer_function",
                   "category": "leadership", "observed_at": "2026-10-21", "payload": {"title": "New VP of Sales"}})
    assert eng.angle(ctx, acct, NOW, "VP of Sales", "Omar Haddad")["signal"]["say_it"] == "Congrats on the new role"


def test_inbound_lead_blocks_cold_outbound(ctx_for):
    from gtm_core.agents import load_module
    ctx = ctx_for("icp-outbound")
    ctx.store.upsert_account({"id": "woodgrove.example", "name": "Woodgrove Bank", "domain": "woodgrove.example",
                              "industry": "Financial Services", "employees": 1400, "country": "CA"})
    eng = load_module(ctx.manifest, "engine")
    assert not any("inbound" in c for c in eng.conflicts(ctx, ctx.store.account("woodgrove.example")))
    ctx.store.upsert("leads", {"id": "l1", "email": "lena@woodgrove.example", "domain": "woodgrove.example", "name": "Lena",
                               "status": "routed", "owner": "Priya Shah", "received_at": "2099-01-01T00:00:00+00:00"})
    assert any("inbound lead in progress" in c for c in eng.conflicts(ctx, ctx.store.account("woodgrove.example")))


def test_draft_sequence_guards(ctx_for):
    from gtm_core.agents import load_module
    ctx = ctx_for("icp-outbound")
    ctx.store.upsert_account({"id": "fourth.example", "name": "Fourth Coffee", "domain": "fourth.example",
                              "industry": "Software", "employees": 500, "country": "US"})
    ctx.store.upsert_account({"id": "nw.example", "name": "Northwind", "domain": "nw.example", "industry": "Logistics",
                              "employees": 600, "country": "US"})
    ctx.store.upsert("contacts", {"id": "rosa@fourth.example", "email": "rosa@fourth.example", "name": "Rosa Diaz",
                                  "title": "VP Sales", "account_id": "fourth.example"})
    ctx.store.upsert("contacts", {"id": "dana@nw.example", "email": "dana@nw.example", "name": "Dana",
                                  "title": "VP Sales", "account_id": "nw.example"})
    eng = load_module(ctx.manifest, "engine")
    acct = ctx.store.account("fourth.example")
    rosa = {"contact_id": "rosa@fourth.example", "email": "rosa@fourth.example", "name": "Rosa Diaz", "title": "VP Sales",
            "function": "sales"}
    first = eng.draft_sequence(ctx, acct, rosa)
    assert first["approval"]
    again = eng.draft_sequence(ctx, acct, rosa)
    assert again["skipped"] and any("already drafted" in r for r in again["reasons"])
    other = eng.draft_sequence(ctx, acct, {"contact_id": "dana@nw.example", "email": "dana@nw.example", "name": "Dana"})
    assert other["skipped"] and any("another account" in r for r in other["reasons"])
    stranger = eng.draft_sequence(ctx, acct, {"email": "x@elsewhere.example", "name": "X"})
    assert stranger["skipped"] and any("domain" in r for r in stranger["reasons"])


def test_sent_sequence_events_feed_angle_performance(ctx):
    t = bind_tools(ctx)
    out = t["draft_sequence"](account="proseware.example")
    assert out["value_prop"]["id"] == "prioritization"  # VP of Sales, no data yet: persona default
    [appr] = ctx.approvals.list()
    meta = appr["payload"]["meta"]
    assert meta["angle_key"] == "signal:funding_round" and meta["value_prop"] == "prioritization"
    register_core_executors(ctx)
    ctx.approvals.decide(appr["id"], True)
    ctx.approvals.execute_approved()
    first = out["steps"][0]["draft_id"]
    assert t["record_email_event"](email="omar@proseware.example", event="sent", occurred_at="2026-10-23T13:00:00Z",
                                   draft_id=first)["matched_draft"] == first
    r = t["record_email_event"](email="omar@proseware.example", event="opened", occurred_at="2026-10-23T15:00:00Z")
    assert r["matched_draft"] == first and not r["machine"]
    perf = t["angle_performance"](days=3650)
    assert perf["by_value_prop"]["prioritization"]["open_rate"] == 1.0
    assert perf["by_angle"]["signal:funding_round"]["sends"] == 1
