"""Salesforce: every opportunity (open, won, lost), custom loss reason and competitor fields, stage history,
incremental sync. Snowflake stays read only. The autonomy overlay changes only what it names."""
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from gtm_core.connectors.salesforce import Salesforce
from gtm_core.connectors.snowflake import ReadOnlyError, Snowflake, check_read_only
from gtm_core.sync import sync_all

OPPS = [
    {"Id": "006A", "Name": "Contoso Platform", "AccountId": "001A", "Account": {"Name": "Contoso"}, "OwnerId": "005S",
     "Owner": {"Name": "Sam Rivera", "Email": "sam@beacon.example"}, "StageName": "Proposal", "Amount": 100000,
     "CloseDate": "2026-12-15", "CreatedDate": "2026-09-01T10:00:00.000+0000", "IsClosed": False, "IsWon": False,
     "Type": "New Business", "LeadSource": "Web", "Loss_Reason__c": None, "Primary_Competitor__c": None},
    {"Id": "006B", "Name": "Fabrikam Data", "AccountId": "001B", "Account": {"Name": "Fabrikam"}, "OwnerId": "005P",
     "Owner": {"Name": "Priya Shah"}, "StageName": "Closed Lost", "Amount": 40000, "CloseDate": "2026-10-10",
     "CreatedDate": "2026-07-01T10:00:00.000+0000", "IsClosed": True, "IsWon": False, "Type": "New Business",
     "LeadSource": "Web", "Loss_Reason__c": "No Decision", "Primary_Competitor__c": "Rival A"},
]
HISTORY = [{"Id": "008a", "OpportunityId": "006B", "StageName": "Discovery", "CreatedDate": "2026-07-01T10:00:00.000+0000"},
           {"Id": "008b", "OpportunityId": "006B", "StageName": "Closed Lost", "CreatedDate": "2026-10-10T10:00:00.000+0000"}]


def _sf(seen):
    def handler(req):
        url = urlparse(str(req.url))
        if url.path.endswith("/sobjects/Opportunity/describe"):
            return httpx.Response(200, json={"fields": [{"name": n} for n in (
                "Id", "Name", "StageName", "Loss_Reason__c", "Primary_Competitor__c", "Segment__c")]})
        q = parse_qs(url.query).get("q", [""])[0]
        seen.append(q)
        if "FROM OpportunityHistory" in q:
            return httpx.Response(200, json={"records": HISTORY})
        if "FROM Opportunity" in q:
            if "LastModifiedDate >" in q:
                return httpx.Response(200, json={"records": [OPPS[0]]})
            return httpx.Response(200, json={"records": OPPS})
        return httpx.Response(200, json={"records": []})
    return Salesforce("https://acme.my.salesforce.example", "tok",
                      client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_pulls_all_history_with_custom_fields(monkeypatch):
    monkeypatch.setenv("SALESFORCE_OPP_FIELDS", "Segment__c,Not_A_Field__c")
    seen = []
    deals = _sf(seen).list_deals()
    q = seen[0]
    assert "WHERE" not in q and "LIMIT" not in q  # every open, won and lost deal
    assert "Loss_Reason__c" in q and "Primary_Competitor__c" in q and "Segment__c" in q
    assert "Not_A_Field__c" not in q
    lost = deals[1]
    assert lost["status"] == "lost" and lost["loss_reason"] == "No Decision" and lost["competitor"] == "Rival A"
    assert deals[0]["owner"] == "Sam Rivera" and deals[0]["owner_crm_id"] == "005S"
    assert deals[0]["account_name"] == "Contoso" and deals[0]["lead_source"] == "Web"


def test_since_days_and_pinned_loss_field(monkeypatch):
    monkeypatch.setenv("SALESFORCE_OPP_SINCE_DAYS", "730")
    monkeypatch.setenv("SALESFORCE_LOSS_REASON_FIELD", "Segment__c")
    seen = []
    _sf(seen).list_deals()
    assert "LAST_N_DAYS:730" in seen[0] and "IsClosed = false" in seen[0]


def test_sync_stores_deals_history_and_goes_incremental(ctx_for):
    ctx = ctx_for("opportunity-analyst")
    seen = []
    ctx.crm = _sf(seen)
    first = sync_all(ctx)
    assert first["deals"] == 2 and first["deals_mode"] == "full" and first["deal_history"] == 2
    d = ctx.store.get("deals", "sf-opp-006B")
    assert d["status"] == "lost" and d["loss_reason"] == "No Decision"
    assert len(ctx.store.query("SELECT * FROM deal_stage_history WHERE deal_id='sf-opp-006B'")) == 2
    second = sync_all(ctx)
    assert second["deals_mode"] == "incremental" and second["deals"] == 1
    assert any("LastModifiedDate >" in q and "Z" in q for q in seen)
    again = sync_all(ctx)  # history rows are keyed by the CRM id: no duplicates
    assert again["deals"] == 1
    assert len(ctx.store.query("SELECT * FROM deal_stage_history")) == 2
    assert sync_all(ctx, full=True)["deals_mode"] == "full"


def test_analyst_tools_answer_from_synced_data(ctx_for):
    ctx = ctx_for("opportunity-analyst")
    ctx.crm = _sf([])
    from gtm_core.agents import load_module
    tools = load_module(ctx.manifest, "tools").TOOLS
    tools["sync_crm"](ctx)
    lost = tools["find_opportunities"](ctx, status="lost")
    assert lost["count"] == 1 and lost["opportunities"][0]["loss_reason"] == "No Decision"
    la = tools["loss_analysis"](ctx, since="3650d")
    assert la["by_reason"][0]["key"] == "No Decision" and la["by_stage_lost"][0]["key"] == "discovery"
    assert tools["open_pipeline"](ctx)["open_amount"] == 100000


@pytest.mark.parametrize("sql", ["SELECT 1 AS value", "with x as (select 1) select * from x",
                                 "select 'drop table' as value", "-- note\nSELECT count(*) AS value FROM leads;"])
def test_snowflake_allows_reads(sql):
    assert check_read_only(sql)


@pytest.mark.parametrize("sql", ["DELETE FROM leads", "select 1; drop table leads", "UPDATE t SET a=1",
                                 "with x as (select 1) insert into t select * from x", "", "CALL proc()"])
def test_snowflake_refuses_writes(sql):
    with pytest.raises(ReadOnlyError):
        check_read_only(sql)


def test_snowflake_scalar_with_fake_connection():
    class Cur:
        description = [("VALUE",), ("PRIOR",)]
        def execute(self, sql, params): self.sql = sql
        def fetchmany(self, n): return [(42, 40)]
        def close(self): pass

    class Conn:
        def cursor(self): return Cur()

    assert Snowflake(conn=Conn()).scalar("SELECT 42 AS value, 40 AS prior") == {"value": 42, "prior": 40}


def test_autonomy_overlay_only_changes_named_actions(monkeypatch):
    from gtm_core.autonomy import Autonomy
    base = Autonomy.load()
    assert base.level("crm_note", "meeting-intelligence")[0] == "approve"
    monkeypatch.setenv("GTM_AUTONOMY_OVERLAY", "deploy/itential/autonomy.overlay.yaml")
    a = Autonomy.load()
    assert a.level("crm_note", "meeting-intelligence")[0] == "auto"
    assert a.level("crm_task", "seller-follow-up")[0] == "auto"
    assert a.level("pipeline_email", "seller-follow-up")[0] == "approve"   # buyer emails stay with the rep
    assert a.level("sequence_enroll", "icp-outbound")[0] == "approve"
    assert a.rules["auto_allowed"] == base.rules["auto_allowed"]
