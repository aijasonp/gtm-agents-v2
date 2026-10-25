from datetime import datetime, timezone

from gtm_core.agents import load_module
from gtm_core.executors import register_core_executors
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 9, tzinfo=timezone.utc)


def _seed(ctx):
    ctx.store.upsert_account({"id": "proseware.example", "name": "Proseware", "domain": "proseware.example", "crm_id": "9",
                              "industry": "Software", "employees": 350, "country": "US"})
    ctx.store.upsert("deals", {"id": "d1", "account_id": "northwind.example", "name": "NW", "owner": "Sam Rivera",
                               "stage": "Evaluation", "status": "open"})
    ctx.store.upsert_account({"id": "northwind.example", "name": "Northwind", "domain": "northwind.example", "industry": "Logistics",
                              "employees": 600, "country": "US"})


def test_add_lead_triages_and_queues(ctx_for):
    ctx = ctx_for("lead-triage")
    _seed(ctx)
    tools = bind_tools(ctx)
    r = tools["add_lead"](email="omar@proseware.example", name="Omar Haddad", title="VP of Sales", company="Proseware",
                          source="demo_request", message="How does routing work?")
    assert r["tier"] == "hot" and r["draft"]["gate_passed"]
    assert tools["add_lead"](email="omar@proseware.example", source="demo_request")["duplicate"]
    actions = [a["action"] for a in ctx.approvals.list()]
    assert actions == ["crm_contact", "crm_task", "sequence_enroll"]
    register_core_executors(ctx)
    for a in ctx.approvals.list():
        ctx.approvals.decide(a["id"], True)
    ctx.approvals.execute_approved()
    assert ctx.sequencer.sent and ctx.sequencer.sent[0]["contact"]["email"] == "omar@proseware.example"


def test_active_pipeline_never_gets_outreach(ctx_for):
    ctx = ctx_for("lead-triage")
    _seed(ctx)
    r = bind_tools(ctx)["add_lead"](email="x@northwind.example", name="X Y", title="CRO", source="demo_request")
    assert r["active_pipeline"] and r["owner"] == "Sam Rivera" and r["draft"] is None
    assert [a["action"] for a in ctx.approvals.list()] == ["crm_task"]


def test_triage_job_digest_and_sla(ctx_for):
    ctx = ctx_for("lead-triage")
    _seed(ctx)
    ctx.store.upsert("leads", {"id": "l1", "email": "omar@proseware.example", "name": "Omar", "title": "VP Sales",
                               "company": "Proseware", "source": "demo_request", "received_at": "2026-10-23T08:00:00+00:00",
                               "status": "new", "domain": "proseware.example"})
    jobs = load_module(ctx.manifest, "jobs")
    out = jobs.triage_inbox(ctx, now=NOW)
    assert out["triaged"] == 1 and out["tiers"]["hot"] == 1
    assert "Lead Triage: 1 new" in ctx.slack.sent[-1]["text"]
    late = jobs.sla_check(ctx, now=NOW)
    assert late["late"] == 1 and "SLA missed" in ctx.slack.sent[-1]["text"]
    assert jobs.sla_check(ctx, now=NOW)["late"] == 0  # nudged once only


def test_retriage_never_queues_a_second_send(ctx_for):
    ctx = ctx_for("lead-triage")
    _seed(ctx)
    tools = bind_tools(ctx)
    tools["add_lead"](email="omar@proseware.example", name="Omar", title="VP of Sales", company="Proseware",
                      source="demo_request")
    before = len(ctx.approvals.list())
    again = tools["triage_lead"](lead="omar@proseware.example")
    assert again["already_triaged"] and len(ctx.approvals.list()) == before
    eng = load_module(ctx.manifest, "engine")
    lead = ctx.store.select("leads")[0]
    assert eng.process(ctx, lead)["skipped"]
    assert len(ctx.approvals.list()) == before


def test_route_preview_does_not_advance_round_robin(ctx_for):
    ctx = ctx_for("lead-triage")
    tools = bind_tools(ctx)
    ctx.store.upsert("leads", {"id": "l1", "email": "a@new.example", "name": "A", "title": "VP Sales", "source": "demo_request",
                               "status": "new", "domain": "new.example", "country": "US"})
    owners = {tools["route_lead"](lead="l1")["owner"] for _ in range(3)}
    assert len(owners) == 1


def test_opted_out_lead_gets_no_automated_outreach(ctx_for):
    from gtm_core import suppression
    ctx = ctx_for("lead-triage")
    _seed(ctx)
    suppression.suppress(ctx.store, "omar@proseware.example", "opt-out")
    r = bind_tools(ctx)["add_lead"](email="omar@proseware.example", name="Omar", title="VP of Sales",
                                    company="Proseware", source="demo_request")
    assert r["suppressed"] and r["draft"] is None and "DO NOT CONTACT" in r["flags"][0]
    assert [a["action"] for a in ctx.approvals.list()] == ["crm_task"]
