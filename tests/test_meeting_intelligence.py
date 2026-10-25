from datetime import datetime, timezone

import pytest

from gtm_core.agents import Context, Manifest, load_module
from gtm_core.connectors.base import NullCRM
from gtm_core.connectors.sequencer import Sequencer
from gtm_core.connectors.slack import Slack
from gtm_core.executors import register_core_executors
from gtm_core.handoffs import Handoffs
from gtm_core.mcp_server import bind_tools
from gtm_core.store import Store

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
TRANSCRIPT = """[00:00:05] Sam Rivera: What made you take the call?
[00:00:20] Dana Cole: Reps build lists manually and it takes forever. We already use Acme Intel.
[00:05:00] Sam Rivera: Who signs off?
[00:05:30] Dana Cole: Our CFO has final say. Procurement needs a security review.
[00:09:00] Sam Rivera: Next step: I'll send over a pilot plan by Friday."""


@pytest.fixture
def ctx(settings):
    m = Manifest.load("agents/meeting-intelligence")
    slack = Slack(settings)
    slack.post = lambda text, **kw: slack.sent.append({"text": text}) or {"ok": True}
    c = Context.build(settings, m, store=Store("sqlite:///:memory:"), crm=NullCRM(), slack=slack, sequencer=Sequencer())
    c.store.upsert_account({"id": "northwind.example", "name": "Northwind", "domain": "northwind.example"})
    c.store.upsert("deals", {"id": "d1", "crm_id": "5001", "account_id": "northwind.example", "name": "NW Platform",
                             "stage": "Evaluation", "status": "open", "owner": "Sam Rivera"})
    c.store.upsert("meetings", {"id": "m1", "account_id": "northwind.example", "deal_id": "d1", "title": "NW discovery",
                                "owner": "Sam Rivera", "started_at": "2026-10-20T15:00:00+00:00", "transcript": TRANSCRIPT})
    return c


def test_process_job_end_to_end(ctx):
    out = load_module(ctx.manifest, "jobs").process_meetings(ctx, now=NOW)
    assert out["processed"] == 1 and out["handoffs"] == 2 and out["approvals_queued"] == 1
    m = ctx.store.get("meetings", "m1")
    assert m["processed_at"] and "pilot plan" in " ".join(m["summary"]["next_steps"])
    assert "Meeting Intelligence: 1 call processed" in ctx.slack.sent[-1]["text"]
    assert [i["key"] for i in ctx.store.insights("competitor_mention")] == ["Acme Intel"]
    recap = Handoffs(ctx.store, "seller-follow-up").pending("meeting_recap")[0]
    assert recap["payload"]["owner"] == "Sam Rivera" and recap["payload"]["next_steps"]
    ev = Handoffs(ctx.store, "deal-inspection").pending("meddpicc_evidence")[0]["payload"]
    assert {"economic_buyer", "paper_process", "identify_pain"} <= set(ev["evidence"])
    register_core_executors(ctx)
    note = ctx.approvals.list()[0]
    ctx.approvals.decide(note["id"], True)
    ctx.approvals.execute_approved()
    assert ctx.crm.writes[-1]["kind"] == "deal_note" and "Pain:" in ctx.crm.writes[-1]["note"]


def test_tools(ctx):
    tools = bind_tools(ctx)
    assert tools["list_meetings"]()["count"] == 1
    pasted = tools["analyze_call"](meeting=TRANSCRIPT)
    assert "Acme Intel" in pasted["analysis"]["competitors"]
    assert tools["meeting_summary"](meeting="m1")["processed"] is False
    load_module(ctx.manifest, "jobs").process_meetings(ctx, now=NOW)
    s = tools["meeting_summary"](meeting="NW discovery")
    assert s["processed"] and "Next steps:" in s["text"]
    c = tools["coaching_notes"](meeting="m1")
    assert "tips" in c and isinstance(c["missed_meddpicc_areas"], list)
    hits = tools["search_mentions"](kind="competitor_mention", key="acme intel", days=3650)
    assert hits["count"] == 1 and hits["mentions"][0]["meeting_id"] == "m1"
    assert "error" in tools["analyze_call"](meeting="nope")


def test_ingest_inbox(ctx, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "call2.txt").write_text(TRANSCRIPT)
    (inbox / "call2.meta.json").write_text('{"id": "m2", "title": "Second call", "deal_id": "d1"}')
    ctx.manifest.config["meeting_inbox"] = str(inbox)
    out = load_module(ctx.manifest, "jobs").process_meetings(ctx, now=NOW)
    assert out["ingested"] == 1 and out["processed"] == 2
    assert not list(inbox.iterdir()) and (tmp_path / "processed" / "call2.txt").exists()
