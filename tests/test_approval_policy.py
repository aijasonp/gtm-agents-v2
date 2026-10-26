from datetime import datetime, timedelta, timezone

import pytest

from gtm_core import sequences
from gtm_core.approval_policy import ApprovalRefused, Policy
from gtm_core.executors import register_core_executors
from gtm_core.agents import load_module


def policy(**rules):
    p = Policy.load("config")
    p.rules.update(rules)
    return p


def test_policy_resolves_people_and_refuses_generic_names():
    p = policy()
    assert p.person("Sam Rivera") == "Sam Rivera" and p.person("sam@beacon.example") == "Sam Rivera"
    assert p.person("Jordan Avery") == "Jordan Avery"  # the manager
    assert p.person("operator") is None and p.person("api-approver") is None and p.person("") is None
    p.people["Sam Rivera"]["slack_id"] = "U0SAM"
    assert p.person("slack:U0SAM") == "Sam Rivera"
    assert p.check("crm_task", {}, "operator") == (None, "operator")       # CRM writes are not sends
    assert p.check("sequence_enroll", {}, "operator")[0]
    assert p.check("sequence_enroll", {}, "sam@beacon.example") == (None, "Sam Rivera")


def test_owner_confirms_pipeline_email():
    p = policy(delegates={"Sam Rivera": ["Lee Park"]})
    pay = {"approver": "Sam Rivera"}
    assert p.check("pipeline_email", pay, "Sam Rivera")[0] is None
    assert "Sam Rivera's to confirm" in p.check("pipeline_email", pay, "Priya Shah")[0]
    assert p.check("pipeline_email", pay, "Lee Park")[0] is None          # delegate
    assert p.check("pipeline_email", pay, "Jordan Avery")[0] is None      # manager
    assert policy(managers_can_confirm=False).check("pipeline_email", pay, "Jordan Avery")[0]
    assert policy(named_approver="warn").check("pipeline_email", pay, "operator")[0] is None
    assert policy(named_approver="off").check("sequence_enroll", {}, "operator") == (None, "operator")


def test_refused_decision_changes_nothing_and_send_guard_blocks_backdoor(ctx_for):
    ctx = ctx_for("icp-outbound")
    register_core_executors(ctx)
    rid = ctx.approvals.request("sequence_enroll", {"contact": {"email": "a@x.example"}, "steps": [{"subject": "s", "body": "b"}]})
    with pytest.raises(ApprovalRefused):
        ctx.approvals.decide(rid, True)  # default by=operator
    assert ctx.approvals.list("pending")[0]["id"] == rid
    # a row marked approved outside the queue, with no person on record, still does not send
    ctx.store.execute("UPDATE approvals SET status='approved', decided_by='operator' WHERE id=?", (rid,))
    res = ctx.approvals.execute_approved()
    assert "send refused" in res[0]["error"] and ctx.sequencer.sent == []


def test_per_step_release_holds_and_releases_one_email_at_a_time(ctx_for, monkeypatch):
    ctx = ctx_for("follow-through")
    ctx.approvals._policy = policy(sequence_release="per_step", step_gap_business_days=2)
    register_core_executors(ctx)
    ctx.store.upsert("contacts", {"id": "c1", "name": "Ana Lopez", "email": "ana@northwind.example"})
    steps = [{"subject": f"s{i}", "body": f"b{i}"} for i in (1, 2, 3)]
    rid = ctx.approvals.request("sequence_enroll", {"contact": {"email": "ana@northwind.example", "name": "Ana Lopez"},
                                                    "steps": steps, "draft_ids": [], "meta": {"owner": "Sam Rivera"}})
    ctx.approvals.decide(rid, True, by="Sam Rivera")
    out = ctx.approvals.execute_approved()[0]["result"]
    assert len(ctx.sequencer.sent[0]["steps"]) == 1 and len(out["held"]) == 2
    cad = load_module(ctx.manifest, "cadence")
    later = datetime.now(timezone.utc) + timedelta(days=4)
    assert cad.release_held(ctx, later)["queued"] == 1  # step 2 due after 2 business days, step 3 not yet
    step = next(a for a in ctx.approvals.list("pending") if a["action"] == "sequence_step")
    assert step["payload"]["approver"] == "Sam Rivera"
    with pytest.raises(ApprovalRefused):
        ctx.approvals.decide(step["id"], True, by="Priya Shah")
    ctx.approvals.decide(step["id"], True, by="Sam Rivera")
    assert ctx.approvals.execute_approved()[0]["result"]["ok"]
    assert ctx.sequencer.sent[-1]["steps"] == [{"subject": "s2", "body": "b2"}]
    # a reply cancels the rest
    from gtm_core import engagement
    engagement.record(ctx.store, "ana@northwind.example", "reply", later.isoformat())
    res = cad.release_held(ctx, later + timedelta(days=10))
    assert res == {"queued": 0, "cancelled": 1}
    assert {r["status"] for r in ctx.store.query("SELECT status FROM held_steps")} == {"sent", "cancelled"}


def test_pipeline_email_executor_is_the_touch(ctx_for):
    ctx = ctx_for("follow-through")
    register_core_executors(ctx)
    did = ctx.store.add_draft("follow-through", "cadence_check_in", "Hi Ana", subject="Next step", status="queued",
                              contact_id="c1")
    rid = ctx.approvals.request("pipeline_email", {"contact": {"email": "ana@northwind.example"}, "subject": "Next step",
                                                   "body": "Hi Ana", "draft_id": did, "approver": "Sam Rivera",
                                                   "step": "cadence_check_in"})
    ctx.approvals.decide(rid, True, by="Jordan Avery", edits={"body": "Hi Ana, quick check on next steps."})
    ctx.approvals.execute_approved()
    sent = ctx.sequencer.sent[-1]
    assert sent["steps"] == [{"subject": "Next step", "body": "Hi Ana, quick check on next steps."}]
    assert ctx.store.one("SELECT status FROM drafts WHERE id=?", (did,))["status"] == "sent"
    assert ctx.store.one("SELECT event FROM email_events WHERE email='ana@northwind.example'")["event"] == "sent"
