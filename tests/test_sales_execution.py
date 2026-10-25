import json
from datetime import datetime, timezone

import httpx
import pytest

from gtm_core.agents import Context, Manifest, load_module
from gtm_core.connectors.base import NullCRM
from gtm_core.connectors.sequencer import Sequencer
from gtm_core.connectors.slack import Slack
from gtm_core.gateway import Gateway
from gtm_core.mcp_server import bind_tools
from gtm_core.store import Store

NOW = datetime(2026, 10, 27, 7, tzinfo=timezone.utc)


@pytest.fixture
def ctx(settings):
    m = Manifest.load("agents/sales-execution")
    slack = Slack(settings)
    slack.post = lambda text, **kw: slack.sent.append({"text": text}) or {"ok": True}
    c = Context.build(settings, m, store=Store("sqlite:///:memory:"), crm=NullCRM(), slack=slack, sequencer=Sequencer())
    c.store.upsert_account({"id": "northwind.example", "name": "Northwind", "domain": "northwind.example",
                            "industry": "Logistics", "employees": 600, "country": "US"})
    c.store.upsert("contacts", {"id": "ana", "account_id": "northwind.example", "name": "Ana Ruiz", "title": "CFO"})
    c.store.upsert("deals", {"id": "d1", "account_id": "northwind.example", "name": "NW Platform", "owner": "Sam Rivera",
                             "stage": "Proposal", "status": "open", "amount": 96000,
                             "meddpicc": {"identify_pain": "confirmed: lists take 6 hours"}})
    c.store.upsert("meetings", {"id": "m1", "account_id": "northwind.example", "deal_id": "d1", "title": "CFO call",
                                "started_at": "2026-10-28T15:00:00+00:00", "attendees": ["Ana Ruiz"]})
    return c


def test_job_and_tools(ctx):
    out = load_module(ctx.manifest, "jobs").precall_briefs(ctx, now=NOW)
    assert out["briefed"] == 1 and out["gaps_total"] >= 5
    assert "Pre-call: CFO call" in ctx.slack.sent[-1]["text"] and "Ana Ruiz" in ctx.slack.sent[-1]["text"]
    tools = bind_tools(ctx)
    assert tools["precall_brief"](meeting="northwind.example")["deal"]["id"] == "d1"
    assert tools["precall_brief"](meeting="CFO call")["meeting_id"] == "m1"
    assert "error" in tools["precall_brief"](meeting="nothing-here")
    assert tools["meddpicc_questions"](deal="NW Platform")["gaps"]
    assert tools["objection_help"](objection="Budget is frozen until next year")["category"] in ("price", "timing")
    p = tools["proposal_outline"](deal="d1")
    assert p["sections"][0]["content"] == "lists take 6 hours" and "Investment" not in p["missing"]
    assert tools["next_steps_summary"](deal="d1")["flags"] == ["No next step anywhere: deal has no dated plan"]


def test_model_plan_replaces_fallback(ctx):
    def handler(request):
        return httpx.Response(200, json={"content": [{"type": "text", "text": "1. Confirm Ana signs.\n2. Agree a date."}],
                                         "usage": {"input_tokens": 10, "output_tokens": 10}})
    ctx.settings.anthropic_api_key = "k"; ctx.settings.offline = False
    ctx.gateway = Gateway(ctx.settings, ctx.budgets, ctx.manifest.id, client=httpx.Client(transport=httpx.MockTransport(handler)))
    b = load_module(ctx.manifest, "engine").brief_with_plan(ctx, meeting=ctx.store.get("meetings", "m1"), now=NOW)
    assert b["plan_source"] == "model" and "Confirm Ana signs." in b["text"]
