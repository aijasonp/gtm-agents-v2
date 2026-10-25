"""Judged ICP backbone: typed validation, evidence checks, backends, shadow, caching, learning, and the
open-rate loop into ICP Outbound's value prop choice."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from gtm_core import decision, engagement
from gtm_core.agents import load_module
from gtm_core.decision.backends import ModelBackend, RemoteBackend, RulesBackend
from gtm_core.decision.model import Answer, DecisionModel

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)

MODEL = DecisionModel.from_dict("t", {"questions": [
    {"id": "b2b", "kind": "bool", "ask": "B2B?", "weight": 0.5, "rules": {"yes_any": ["salesforce"]}},
    {"id": "motion", "kind": "choice", "ask": "Motion?", "weight": 0.5,
     "options": {"outbound": 1.0, "self_serve": 0.0}, "rules": {"match": {"outbound": ["outreach"]}}},
    {"id": "scale", "kind": "score", "ask": "Scale?", "weight": 0.0,
     "rules": {"field": "employees", "bands": [[0, 100, 1], [100, None, 5]]}},
]})
STATE = {"account": {"name": "Northwind", "tech": ["salesforce", "outreach"], "employees": 600,
                     "description": "Outbound team of 40 SDRs selling to logistics firms"}, "signals": []}


class FakeGateway:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def available(self, _cls="cheap"):
        return True

    def complete(self, prompt, system="", model_class="cheap", max_tokens=900):
        self.calls += 1
        return SimpleNamespace(text=json.dumps(self.reply))


def test_typed_validation_rejects_wrong_kinds():
    q = MODEL.by_id
    assert q["b2b"].validate("yes") is True
    assert q["motion"].validate("outbound") == "outbound"
    assert q["scale"].validate(4) == 4
    for qid, bad in [("b2b", "maybe"), ("motion", "hybrid"), ("scale", 7), ("scale", 2.5), ("scale", True)]:
        with pytest.raises(ValueError):
            q[qid].validate(bad)
    with pytest.raises(ValueError):
        DecisionModel.from_dict("x", {"questions": [{"id": "a", "kind": "choice", "ask": "?"}]})
    with pytest.raises(ValueError):
        DecisionModel.from_dict("x", {"questions": [{"id": "a", "kind": "bool", "ask": "?"}] * 2})


def test_rules_backend_answers_only_with_evidence():
    a = RulesBackend().answer(MODEL, STATE)
    assert a["b2b"].value is True and a["motion"].value == "outbound" and a["scale"].value == 5
    none = RulesBackend().answer(MODEL, {"account": {"name": "X"}, "signals": []})
    assert none == {}
    score, cov, _ = MODEL.score(a)
    assert score == 100.0 and cov == 1.0
    assert MODEL.score({})[0] is None


def test_word_boundaries_in_rules():
    m = DecisionModel.from_dict("w", {"questions": [{"id": "x", "kind": "bool", "ask": "?", "weight": 1,
                                                     "rules": {"yes_any": ["sdr"]}}]})
    assert RulesBackend().answer(m, {"account": {"description": "40 SDRs"}}) == {}  # "sdrs" is not "sdr"
    assert RulesBackend().answer(m, {"account": {"description": "an SDR team"}})["x"].value is True


def test_model_backend_drops_unsupported_and_invalid_answers(ctx_for):
    ctx = ctx_for("signal-scout")
    ctx.gateway = FakeGateway({"answers": {
        "b2b": {"value": True, "evidence": "selling to logistics firms", "confidence": 0.9},
        "motion": {"value": "outbound", "evidence": "best in class outbound engine"},   # not in facts
        "scale": {"value": 9, "evidence": "600"}}})                                       # out of range
    got = ModelBackend(ctx).answer(MODEL, STATE)
    assert set(got) == {"b2b"} and got["b2b"].source == "model" and got["b2b"].confidence == 0.9
    events = [r["event"] for r in ctx.store.query("SELECT event FROM audit_log")]
    assert "decision.unsupported" in events and "decision.invalid" in events


def test_decide_falls_back_to_rules_and_caches(ctx_for):
    ctx = ctx_for("signal-scout")
    gw = FakeGateway({"answers": {"b2b": {"value": False, "evidence": "selling to logistics firms"}}})
    ctx.gateway = gw
    cfg = {"backend": "model", "cache_days": 30}
    v = decision.decide(ctx, cfg, MODEL, "northwind", STATE, NOW)
    assert v.answers["b2b"].source == "model" and v.answers["b2b"].value is False
    assert v.answers["motion"].source == "rules"  # model said nothing: rules fill the gap
    assert v.backend == "model" and v.score == 50.0
    again = decision.decide(ctx, cfg, MODEL, "northwind", STATE, NOW)
    assert again.cached and gw.calls == 1
    changed = decision.decide(ctx, cfg, MODEL, "northwind", {**STATE, "signals": [{"type": "funding_round"}]}, NOW)
    assert not changed.cached and gw.calls == 2


def test_remote_backend_and_shadow_mode(ctx_for, monkeypatch):
    ctx = ctx_for("signal-scout")
    ctx.settings.offline = False
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"answers": {"b2b": {"value": True, "evidence": "40 SDRs"},
                                                     "motion": {"value": "self_serve", "evidence": "outbound team"}}})
    monkeypatch.setenv("GTM_DECISION_URL", "https://decide.example/v1")
    monkeypatch.setenv("GTM_DECISION_TOKEN", "t0k")
    ctx.decision_client = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = {"backend": "auto", "remote": {}}
    assert decision.resolve_backend(ctx, cfg) == "remote"
    v = decision.decide(ctx, cfg, MODEL, "nw", STATE, NOW)
    assert seen["auth"] == "Bearer t0k" and seen["body"]["model"] == "t" and len(seen["body"]["questions"]) == 3
    assert v.backend == "remote" and v.value("motion") == "self_serve"
    sh = decision.decide(ctx, {"backend": "shadow", "shadow": {"primary": "rules", "candidate": "remote"}},
                         MODEL, "nw2", STATE, NOW)
    assert sh.backend == "rules" and sh.value("motion") == "outbound"
    assert sh.shadow["backend"] == "remote" and sh.shadow["agreement"] == 0.667 and sh.shadow["compared"] == 3


def _send(store, email, account_id, vp, opened, replied, machine_open=False, i=0):
    t0 = (NOW - timedelta(days=5, minutes=i)).isoformat()
    store.insert("INSERT INTO drafts (agent, kind, account_id, contact_id, subject, body, status, meta, created_at) "
                 "VALUES (?,?,?,?,?,?,?,?,?)", ("icp-outbound", "first_touch", account_id, None, "s", "b", "sent",
                                                json.dumps({"value_prop": vp, "angle_key": "value_led"}), t0))
    did = store.query("SELECT MAX(id) AS id FROM drafts")[0]["id"]
    engagement.record(store, email, "sent", t0, draft_id=did)
    if machine_open:
        engagement.record(store, email, "open", (NOW - timedelta(days=5, minutes=i) + timedelta(seconds=2)).isoformat(),
                          draft_id=did)
    if opened:
        engagement.record(store, email, "opened", (NOW - timedelta(days=4, minutes=i)).isoformat(), draft_id=did)
    if replied:
        engagement.record(store, email, "replied", (NOW - timedelta(days=3, minutes=i)).isoformat(), draft_id=did)


def test_engagement_rates_ignore_machine_opens(ctx_for):
    st = ctx_for("icp-outbound").store
    _send(st, "a@x.example", "x.example", "prioritization", False, False, machine_open=True)
    _send(st, "b@x.example", "x.example", "prioritization", True, False, i=1)
    _send(st, "c@x.example", "x.example", "prioritization", False, True, i=2)  # reply proves an open
    r = engagement.rates(engagement.threads(st))
    assert r == {"sends": 3, "open_rate": 0.667, "reply_rate": 0.333, "positive_rate": 0.0}
    assert engagement.record(st, "b@x.example", "opened", (NOW - timedelta(days=4, minutes=1)).isoformat())["duplicate"]
    with pytest.raises(ValueError):
        engagement.record(st, "b@x.example", "teleported")


def test_value_prop_pick_learns_from_engagement(ctx_for):
    ctx = ctx_for("icp-outbound")
    eng = load_module(ctx.manifest, "engine")
    acct = {"id": "acme.example", "name": "Acme"}
    first = eng.choose_value_prop(ctx, acct, "sales", NOW)
    assert first["value_prop"]["id"] == "prioritization"  # no data: persona default
    ctx.store.insert("INSERT INTO decisions (model, subject, answers, score, created_at) VALUES (?,?,?,?,?)",
                     ("icp_fit", "acme.example", json.dumps({"primary_pain": {"value": "follow_up"}}), 80, NOW.isoformat()))
    judged = eng.choose_value_prop(ctx, acct, "sales", NOW)
    assert judged["value_prop"]["id"] == "follow_up" and "judged" in judged["why"]
    for i in range(30):  # deal_hygiene earns replies, the others do not
        _send(ctx.store, f"d{i}@y.example", "y.example", "deal_hygiene", True, i % 2 == 0, i=i)
        _send(ctx.store, f"f{i}@y.example", "y.example", "follow_up", i % 5 == 0, False, i=100 + i)
        _send(ctx.store, f"p{i}@y.example", "y.example", "prioritization", i % 5 == 0, False, i=200 + i)
    learned = eng.choose_value_prop(ctx, acct, "sales", NOW)
    assert learned["value_prop"]["id"] == "deal_hygiene" and "reply" in learned["why"]


def test_learning_moves_question_weights_from_opens(ctx_for):
    ctx = ctx_for("signal-scout")
    st = ctx.store
    for i in range(40):
        good = i < 20
        aid = f"a{i}.example"
        ans = {"b2b": {"value": good}, "motion": {"value": "outbound"}}
        st.insert("INSERT INTO decisions (model, subject, answers, score, created_at) VALUES (?,?,?,?,?)",
                  ("t", aid, json.dumps(ans), 100 if good else 50, NOW.isoformat()))
        _send(st, f"x@{aid}", aid, "prioritization", good or i % 4 == 0, good and i % 2 == 0, i=i)
    rep = decision.learn(st, MODEL, min_per_side=20, now=NOW)
    q = rep["questions"]["b2b"]
    assert q["lift"] > 1.5 and q["to"] > 1.0
    assert "skipped" in rep["questions"]["motion"]  # every account said outbound: no contrast, no change
    assert rep["by_icp_band"]["80-100"]["open_rate"] == 1.0 and rep["by_icp_band"]["40-59"]["open_rate"] == 0.25
    assert decision.multipliers(st, "t")["b2b"] == q["to"]
    v = MODEL.score({"b2b": Answer(True), "motion": Answer("self_serve")}, decision.multipliers(st, "t"))
    assert v[0] > 50  # the learned question now counts for more


def test_signal_scout_weekly_job_reports_judged_learning(ctx_for):
    ctx = ctx_for("signal-scout")
    out = load_module(ctx.manifest, "jobs").weekly_reweight(ctx, now=NOW)
    assert "judged" in out and out["judged"]["threads"] == 0


def test_api_email_events(settings):
    from gtm_core.api import Api
    from gtm_core.store import Store
    api = Api(settings, "tok", store=Store("sqlite:///:memory:"))
    code, out = api.route("POST", "/v1/email-events", {},
                          [{"email": "a@b.example", "event": "sent", "occurred_at": "2026-10-20T10:00:00Z"},
                           {"email": "a@b.example", "event": "opened", "occurred_at": "2026-10-20T12:00:00Z"},
                           {"email": "a@b.example", "event": "nope"}])
    assert code == 201 and out["added"] == 2 and len(out["errors"]) == 1
