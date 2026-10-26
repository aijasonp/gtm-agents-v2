from datetime import datetime, timezone

import pytest

from gtm_core.agents import Manifest, load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def manifests():
    return {"proposal-builder": Manifest.load("agents/proposal-builder")}


@pytest.fixture
def ctx(ctx_for, tmp_path):
    c = ctx_for("proposal-builder")
    c.manifest.config["output_dir"] = str(tmp_path / "out")
    c.store.upsert_account({"id": "proseware.example", "name": "Proseware", "domain": "proseware.example"})
    c.store.upsert("deals", {"id": "d1", "account_id": "proseware.example", "name": "Proseware new", "stage": "Proposal",
                             "status": "open", "crm_id": "crm-1",
                             "meddpicc": {"identify_pain": "lists built in spreadsheets", "metrics": ""}})
    return c


def test_tools_bind_and_quote(ctx):
    t = bind_tools(ctx)
    assert set(t) == {"list_products", "build_quote", "check_discount", "render_proposal", "send_proposal", "get_quote"}
    assert {p["sku"] for p in t["list_products"]()["products"]} == {"AGENT-SEAT", "PLATFORM", "ONBOARD"}
    q = t["build_quote"](deal="d1", lines=[{"sku": "AGENT-SEAT", "qty": 100}], term_years=3)
    assert q["lines"][0]["unit_price"] == "960.00" and q["annual_recurring"] == "86400.00"
    assert q["total_contract_value"] == "259200.00" and q["status"] == "ready"
    assert t["build_quote"](deal="nobody", lines=[{"sku": "PLATFORM", "qty": 1}])["error"]
    assert t["check_discount"](discount_pct=12, role="manager")["status"] == "ok"
    assert t["check_discount"](discount_pct=25, role="manager")["level"] == "vp"
    assert t["get_quote"](quote_id="q_missing")["error"]


def test_discount_approval_flow_then_send(ctx):
    t = bind_tools(ctx)
    jobs = load_module(ctx.manifest, "jobs")
    jobs.register_executors(ctx)
    q = t["build_quote"](deal="d1", lines=[{"sku": "AGENT-SEAT", "qty": 30}, {"sku": "ONBOARD", "qty": 1}],
                         discount_pct=18, role="ae")
    assert q["status"] == "pending_approval" and q["guardrail"]["level"] == "manager"
    assert "Approval #" in ctx.slack.sent[-1]["text"]
    r = t["render_proposal"](quote_id=q["quote_id"])
    html = open(r["html_path"]).read()
    assert "Draft:" in html and "lists built in spreadsheets" in html and "What success looks like" not in html
    assert t["send_proposal"](quote_id=q["quote_id"], to_email="omar@proseware.example")["error"]
    ctx.approvals.decide(q["approval_id"], True, by="Sam Rivera")
    ctx.approvals.execute_approved()
    assert t["get_quote"](quote_id=q["quote_id"])["status"] == "ready"
    r2 = t["render_proposal"](quote_id=q["quote_id"])
    assert "Draft:" not in open(r2["html_path"]).read() and r2["ready_to_send"]
    s = t["send_proposal"](quote_id=q["quote_id"], to_email="omar@proseware.example")
    ctx.approvals.decide(s["queued_for_approval"], True, by="Sam Rivera")
    res = ctx.approvals.execute_approved()
    assert res[0]["result"]["to"] == "omar@proseware.example"
    assert t["get_quote"](quote_id=q["quote_id"])["status"] == "sent"


def test_rejected_discount_blocks_render(ctx):
    t = bind_tools(ctx)
    q = t["build_quote"](deal="d1", lines=[{"sku": "AGENT-SEAT", "qty": 30}], discount_pct=18)
    ctx.approvals.decide(q["approval_id"], False)
    assert "discount_rejected" in t["render_proposal"](quote_id=q["quote_id"])["error"]


def test_expiring_quotes_job(ctx):
    eng = load_module(ctx.manifest, "engine")
    eng.build_quote(ctx, "d1", [{"sku": "PLATFORM", "qty": 1}], now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    out = load_module(ctx.manifest, "jobs").expiring_quotes(ctx, now=NOW)
    assert out["expiring"] == 1 and "expiring this week" in ctx.slack.sent[-1]["text"]
