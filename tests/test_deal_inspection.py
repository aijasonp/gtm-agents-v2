from datetime import datetime, timezone

import pytest

from gtm_core.agents import Manifest, load_module
from gtm_core.executors import register_core_executors
from gtm_core.handoffs import Handoffs
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def manifests():  # only this agent, so the test does not depend on other agents' folders
    return {"deal-inspection": Manifest.load("agents/deal-inspection")}


def _ctx(ctx_for, manifests):
    return ctx_for("deal-inspection")


def _seed(ctx):
    ctx.store.upsert_account({"id": "contoso.example", "name": "Contoso", "domain": "contoso.example",
                              "industry": "Healthcare Technology", "employees": 900, "country": "US"})
    ctx.store.upsert("contacts", {"id": "jo@contoso.example", "account_id": "contoso.example", "name": "Jo Patel",
                                  "title": "Sales Operations Manager"})
    ctx.store.upsert("deals", {"id": "d1", "crm_id": "5002", "account_id": "contoso.example", "name": "Contoso Agents",
                               "owner": "Sam Rivera", "stage": "Proposal", "status": "open", "amount": 140000,
                               "close_date": "2026-10-15", "stage_entered_at": "2026-09-01",
                               "last_activity_at": "2026-09-25", "next_step": "Send proposal", "next_step_date": "2026-10-10",
                               "meddpicc": {"identify_pain": "confirmed: forecast misses", "champion": "Jo Patel"}})


def test_inspect_contoso_is_fix_with_prioritized_actions(ctx_for, manifests):
    ctx = _ctx(ctx_for, manifests)
    _seed(ctx)
    eng = load_module(ctx.manifest, "engine")
    i = eng.inspect(ctx, ctx.store.get("deals", "d1"), NOW)
    assert i["recommendation"] == "fix" and i["risk"] >= 70
    assert i["actions"][0].startswith("Reset the close date")
    assert i["actions"][1].startswith("Get the economic buyer") and "Jo Patel" in i["actions"][1]
    assert "Contoso Agents | Proposal | $140,000" in eng.format_one(i)


def test_negative_evidence_is_not_missing_data(ctx_for, manifests):
    ctx = _ctx(ctx_for, manifests)
    _seed(ctx)
    ctx.store.add_insight("meeting-intelligence", "objection", "price",
                          evidence="Lee Wong: Budget is frozen until next quarter.", deal_id="d1")
    i = load_module(ctx.manifest, "engine").inspect(ctx, ctx.store.get("deals", "d1"), NOW)
    assert i["negative_evidence"] and any(d.startswith("negative evidence") for d in i["drivers"])


def test_tools_and_meddpicc_update_queue_approval(ctx_for, manifests):
    ctx = _ctx(ctx_for, manifests)
    _seed(ctx)
    tools = bind_tools(ctx)
    assert tools["inspect_deal"](deal="Contoso Agents")["deal_id"] == "d1"
    assert tools["list_at_risk"](owner="Sam Rivera")["count"] == 1
    gaps = {g["element"] for g in tools["meddpicc_gaps"](deal="d1")["gaps"]}
    assert "economic_buyer" in gaps
    assert "error" in tools["update_meddpicc"](deal="d1", element="budget", evidence="x")
    r = tools["update_meddpicc"](deal="d1", element="economic_buyer", evidence="Lee Wong signs", confirmed=True)
    assert r["score"] == 2 and r["approval"]
    gaps = {g["element"] for g in tools["meddpicc_gaps"](deal="d1")["gaps"]}
    assert "economic_buyer" not in gaps
    register_core_executors(ctx)
    ctx.approvals.decide(r["approval"], True)
    ctx.approvals.execute_approved()
    assert ctx.crm.writes[-1] == {"kind": "deal_update", "crm_id": "5002",
                                  "fields": {"meddpicc_economic_buyer": "confirmed: Lee Wong signs"}}
    rec = tools["recommend_action"](deal="d1")
    assert rec["summary_source"] == "template" and rec["recommendation"] in ("fix", "disqualify")


def test_weekly_job_applies_evidence_and_posts(ctx_for, manifests):
    ctx = _ctx(ctx_for, manifests)
    _seed(ctx)
    Handoffs(ctx.store, "meeting-intelligence").send("deal-inspection", "meddpicc_evidence", "d1",
                                                    {"deal_id": "d1", "meeting_id": "m1",
                                                     "evidence": {"paper_process": ["Lee: procurement needs a security review"]}})
    out = load_module(ctx.manifest, "jobs").weekly_inspection(ctx, now=NOW)
    assert out["deals"] == 1 and out["evidence_applied"] == 1
    assert "Deal Inspection: 1 open deals" in ctx.slack.sent[-1]["text"]
    assert ctx.store.get("deals", "d1")["meddpicc"]["paper_process"]["source"] == "call:m1"
    assert ctx.store.insights("deal_inspection")[0]["key"] == "d1"
