from datetime import datetime, timezone

from gtm_core.agents import load_module
from gtm_core.approvals import _EXECUTORS
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)


def _seed(ctx):
    st = ctx.store
    st.upsert_account({"id": "northwind.example", "name": "Northwind Logistics", "domain": "northwind.example", "crm_id": "1001"})
    st.upsert_account({"id": "nw-dup", "name": "Northwind Logistics LLC", "domain": "www.northwind.example"})
    st.upsert("contacts", {"id": "c1", "name": "Dana Cole", "email": "dana@northwind.example", "crm_id": "c-1"})
    st.upsert("contacts", {"id": "c2", "name": "Lee Park", "email": "lee@northwind.example", "account_id": "northwind.example",
                           "email_invalid": True})
    st.upsert("deals", {"id": "d1", "name": "NW", "stage": "Proposal", "status": "open", "close_date": "2026-10-01"})


def test_name_normalization():
    eng = load_module(__import__("gtm_core.agents", fromlist=["Manifest"]).Manifest.load("agents/crm-hygiene"), "engine")
    suf = ["inc", "llc", "corp", "ltd"]
    assert eng.norm_name("Acme, Inc.", suf) == eng.norm_name("ACME Corp", suf) == "acme"
    assert eng.norm_name("Smith & Sons Ltd", suf) == "smith and sons"
    assert eng.norm_domain("HTTPS://www.Acme.example/path?q=1") == "acme.example"


def test_tools_and_merge_executor(ctx_for):
    ctx = ctx_for("crm-hygiene")
    _seed(ctx)
    t = bind_tools(ctx)
    d = t["find_duplicate_accounts"]()
    assert d["groups"] == 1 and d["duplicates"][0]["survivor"] == "northwind.example"
    assert t["contacts_missing_account"]()["contacts"][0]["match"] == "northwind.example"
    b = t["bounced_contacts"](request_reenrichment=True)
    assert b["queued"] == 1
    [h] = ctx.store.query("SELECT * FROM handoffs WHERE to_agent='enrichment'")
    assert h["kind"] == "enrich_request"
    assert t["bounced_contacts"](request_reenrichment=True)["queued"] == 0  # no duplicate handoff
    assert t["stale_stages"]()["deals"][0]["deal_id"] == "d1"
    # revise_deal without a CRM id is skipped, not written
    assert t["propose_fix"](kind="revise_deal", ids=["d1"])["skipped"][0]["why"] == "no CRM id"
    link = t["propose_fix"](kind="link_contact", ids=["c1"])
    assert link["queued"][0]["account"] == "northwind.example"
    r = t["propose_fix"](kind="merge_accounts", ids=["northwind.example", "nw-dup"])
    assert r["survivor"]["id"] == "northwind.example"
    load_module(ctx.manifest, "jobs").register_executors(ctx)
    assert "crm_merge" in _EXECUTORS
    ctx.approvals.decide(r["queued_for_approval"], True)
    res = ctx.approvals.execute_one(r["queued_for_approval"])
    assert ctx.store.account("nw-dup")["merged_into"] == "northwind.example"
    assert "merge Northwind Logistics LLC" in ctx.slack.sent[-1]["text"]
    assert t["find_duplicate_accounts"]()["groups"] == 0
    assert res is not None
    assert t["propose_fix"](kind="bogus", ids=["x"])["error"]


def test_weekly_report(ctx_for):
    ctx = ctx_for("crm-hygiene")
    _seed(ctx)
    out = load_module(ctx.manifest, "jobs").weekly_hygiene_report(ctx, now=NOW)
    assert out["duplicate_accounts"] == 1 and out["stale_deals"] == 1
    assert "Nothing was changed" in ctx.slack.sent[-1]["text"]
