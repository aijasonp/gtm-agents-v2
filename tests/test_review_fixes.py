"""Regressions for the independent review: scoped STOP, stale sends, one touch per cadence step."""
from datetime import datetime, timedelta, timezone

from gtm_core import autonomy, engagement, sequences
from gtm_core.agents import load_module
from gtm_core.api import Api
from gtm_core.executors import register_core_executors
from gtm_core.store import Store


def ft(ctx_for):
    ctx = ctx_for("follow-through")
    register_core_executors(ctx)
    return ctx


def test_one_touch_advances_one_step(ctx_for):
    ctx = ft(ctx_for)
    cad = load_module(ctx.manifest, "cadence")
    t0 = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    row = cad.start(ctx, "proposal_out", "ana@northwind.example", t0, "proposal-x", "Sam Rivera")
    engagement.record(ctx.store, "ana@northwind.example", "sent", (t0 + timedelta(hours=1)).isoformat())
    steps = []
    for i in range(3):
        cad.sweep(ctx, t0 + timedelta(hours=2, minutes=15 * i))
        steps.append(cad.get(ctx, row["id"])["step_id"])
    assert len(set(steps)) == 1 and cad.get(ctx, row["id"])["status"] != "done"


def test_scoped_stop_holds_cadence_and_sequence_sends(ctx_for):
    ctx = ft(ctx_for)
    autonomy.stop(ctx.store, "Sam Rivera", "test", ["pipeline"])
    rid = ctx.approvals.request("pipeline_email", {"contact": {"email": "ana@northwind.example"}, "subject": "s",
                                                   "body": "b", "approver": "Sam Rivera", "cadence": "post_meeting",
                                                   "motion": "post_meeting"})
    ctx.approvals.decide(rid, True, by="Sam Rivera")
    assert ctx.approvals.execute_approved()[0].get("held")
    autonomy.resume(ctx.store, "x")
    autonomy.stop(ctx.store, "Sam Rivera", "test", ["outbound"])
    rid2 = ctx.approvals.request("sequence_step", {"contact": {"email": "bo@northwind.example"}, "subject": "s",
                                                   "body": "b", "approver": "Sam Rivera"})
    ctx.approvals.decide(rid2, True, by="Sam Rivera")
    res = {r["id"]: r for r in ctx.approvals.execute_approved()}
    assert res[rid2].get("held") and res[rid].get("result")  # pipeline runs again after resume; outbound holds


def test_approved_email_is_not_sent_after_a_reply_or_a_stop(ctx_for):
    ctx = ft(ctx_for)
    rid = ctx.approvals.request("pipeline_email", {"contact": {"email": "ana@northwind.example"}, "subject": "s",
                                                   "body": "b", "approver": "Sam Rivera"})
    ctx.approvals.decide(rid, True, by="Sam Rivera")
    engagement.record(ctx.store, "ana@northwind.example", "reply")
    assert "replied" in ctx.approvals.execute_approved()[0]["result"]["skipped"]
    sequences.hold(ctx.store, 7, {"email": "bo@northwind.example"}, [{}, {"subject": "s2", "body": "b2"}], [],
                   "Sam Rivera", 0)
    hid = ctx.store.one("SELECT id FROM held_steps")["id"]
    pend = ctx.approvals.request("sequence_step", {"held_id": hid, "contact": {"email": "bo@northwind.example"},
                                                   "subject": "s2", "body": "b2", "approver": "Sam Rivera"})
    sequences.mark(ctx.store, hid, sequences.QUEUED, approval_id=pend)
    ctx.request_approval("sequence_stop", {"email": "bo@northwind.example", "reason": "teed up"}, auto_safe=True)
    assert ctx.store.one("SELECT status FROM approvals WHERE id=?", (pend,))["status"] == "rejected"


def test_cadence_stop_closes_the_pending_draft_approval(ctx_for):
    ctx = ft(ctx_for)
    cad = load_module(ctx.manifest, "cadence")
    t0 = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    row = cad.start(ctx, "proposal_out", "ana@northwind.example", t0, "proposal-y", "Sam Rivera")
    rid = ctx.approvals.request("pipeline_email", {"contact": {"email": "ana@northwind.example"}, "body": "b",
                                                   "approver": "Sam Rivera", "cadence_id": row["id"]})
    row = cad.get(ctx, row["id"])
    row["approval_id"] = rid
    cad._stop(ctx, row, "replied")
    assert ctx.store.one("SELECT status FROM approvals WHERE id=?", (rid,))["status"] == "rejected"


def test_owner_fyi_posts_once_per_cooldown(ctx_for):
    ctx = ft(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    ctx.store.upsert_account({"id": "nw.example", "name": "NW", "domain": "nw.example", "owner": "Sam Rivera"})
    ctx.store.upsert("contacts", {"id": "c1", "account_id": "nw.example", "email": "ana@nw.example", "name": "Ana"})
    facts = eng.facts_for(ctx, "ana@nw.example")
    d = {"action": "notify_owner", "rule": "open_deal_owner_fyi", "reason": "x"}
    assert eng.act(ctx, facts, d)["action"] == "notify_owner"
    assert eng.act(ctx, facts, d)["action"] == "none"


def test_shared_approver_token_cannot_approve_a_send(settings):
    settings.agents_dir = "agents"
    st = Store("sqlite:///:memory:")
    st.init()
    api = Api(settings, "secret", store=st, approver_token="appr", approver_name="Sam Rivera")
    from gtm_core.approvals import Approvals
    rid = Approvals(st, "follow-through").request("pipeline_email", {"contact": {"email": "a@b.example"},
                                                                     "approver": "Sam Rivera"})
    code, out = api.route("POST", f"/v1/approvals/{rid}/approve", {}, {}, "approver")
    assert code == 403 and "personal token" in out["error"]
    assert api.route("POST", f"/v1/approvals/{rid}/approve", {}, {}, "approver:Sam Rivera")[0] == 200
