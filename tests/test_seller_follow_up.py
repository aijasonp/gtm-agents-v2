from datetime import datetime, timezone

import pytest

from gtm_core.agents import Context, Manifest, load_module
from gtm_core.connectors.base import NullCRM
from gtm_core.connectors.sequencer import Sequencer
from gtm_core.connectors.slack import Slack
from gtm_core.executors import register_core_executors
from gtm_core.mcp_server import bind_tools
from gtm_core.store import Store

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def ctx(settings):
    slack = Slack(settings)
    slack.post = lambda text, **kw: slack.sent.append({"text": text}) or {"ok": True}
    c = Context.build(settings, Manifest.load("agents/seller-follow-up"), store=Store("sqlite:///:memory:"), crm=NullCRM(),
                      slack=slack, sequencer=Sequencer())
    c.store.upsert_account({"id": "contoso.example", "name": "Contoso", "crm_id": "1002"})
    c.store.upsert("contacts", {"id": "lee", "email": "lee@contoso.example", "name": "Lee Wong", "title": "CRO",
                                "account_id": "contoso.example"})
    c.store.upsert("deals", {"id": "d1", "crm_id": "5002", "account_id": "contoso.example", "name": "Contoso Agents",
                             "owner": "Sam Rivera", "stage": "Proposal", "status": "open", "amount": 140000,
                             "next_step": "Send revised proposal", "next_step_date": "2026-10-10",
                             "last_activity_at": "2026-09-25"})
    c.store.upsert("meetings", {"id": "m1", "deal_id": "d1", "account_id": "contoso.example", "title": "Contoso review",
                                "started_at": "2026-10-21T17:00:00+00:00", "owner": "Sam Rivera",
                                "attendees": ["Sam Rivera", "Lee Wong"],
                                "transcript": "Sam Rivera: I'll send over the security docs by Monday.\n"
                                              "Lee Wong: Our reps update the CRM manually and it is a problem."})
    return c


def test_digest_job_and_cooldown(ctx):
    jobs = load_module(ctx.manifest, "jobs")
    r = jobs.daily_digest(ctx, now=NOW)
    assert r["items"] == 2 and r["by_kind"]["no_recap"] == 1
    text = ctx.slack.sent[-1]["text"]
    assert "Follow-ups for Sam Rivera (2)" in text and "also:" in text and "draft #" in text
    n = len(ctx.slack.sent)
    assert jobs.daily_digest(ctx, now=NOW)["items"] == 0 and len(ctx.slack.sent) == n  # silent when nothing new


def test_recap_from_transcript_without_summary(ctx):
    out = bind_tools(ctx)["draft_recap"](meeting="m1")
    body = out["draft"]["body"]
    assert out["draft"]["gate_passed"]
    assert "security docs" in body and "update the CRM manually" in body
    assert out["tasks"][0]["due_at"] == "2026-10-26"  # "by Monday" after a Wednesday call
    assert [a["action"] for a in ctx.approvals.list()] == ["crm_task", "deal_note", "crm_task"]


def test_tools_follow_up_next_step_snooze(ctx):
    t = bind_tools(ctx)
    items = t["whats_overdue"](owner="Sam Rivera")
    assert items["count"] >= 1
    f = t["draft_follow_up"](deal="contoso")
    assert f["to"] == "lee@contoso.example" and f["gate_passed"] and f["approval"]
    r = t["log_next_step"](deal="d1", text="Pricing call with Lee", due_at="2026-10-30")
    assert ctx.store.get("deals", "d1")["next_step"] == "Pricing call with Lee" and len(r["queued_for_approval"]) == 2
    register_core_executors(ctx)
    for a in ctx.approvals.list():
        ctx.approvals.decide(a["id"], True)
    ctx.approvals.execute_approved()
    assert {w["kind"] for w in ctx.crm.writes} >= {"task", "deal_update"}
    item = t["whats_overdue"](owner="Sam Rivera")["owners"]["Sam Rivera"][0]["item_id"]
    t["snooze"](item_id=item, days=3)
    assert all(i["item_id"] != item for i in t["whats_overdue"](owner="Sam Rivera")["owners"].get("Sam Rivera", []))


def test_failing_recap_is_never_queued_to_send(ctx_for, monkeypatch):
    from gtm_core import writer
    from gtm_core.agents import load_module
    ctx = ctx_for("seller-follow-up")
    ctx.store.upsert_account({"id": "nw.example", "name": "Northwind", "crm_id": "1"})
    ctx.store.upsert("deals", {"id": "d1", "crm_id": "5", "account_id": "nw.example", "name": "NW", "owner": "Sam Rivera",
                               "stage": "Evaluation", "status": "open"})
    ctx.store.upsert("meetings", {"id": "m1", "account_id": "nw.example", "deal_id": "d1", "title": "Call",
                                  "started_at": "2026-10-20T15:00:00+00:00", "owner": "Sam Rivera",
                                  "attendees": "Sam Rivera; Dana Cole", "transcript": "Dana Cole: we need help.",
                                  "summary": {"next_steps": ["Sam Rivera: I'll send the plan by Friday"]}})
    monkeypatch.setattr(writer, "write", lambda *a, **k: writer.Draft("s", "slop!!! leverage synergy", 10, False, "model", 3, ["x"]))
    out = load_module(ctx.manifest, "engine").build_recap(ctx, "m1", None)
    subjects = [a["payload"].get("subject", "") for a in ctx.approvals.list()]
    assert not any(s.startswith("Send recap") for s in subjects)
    assert out.get("needs_rewrite") and ctx.store.drafts()[0]["status"] == "needs_rewrite"
