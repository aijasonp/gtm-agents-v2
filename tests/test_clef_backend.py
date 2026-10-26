import json

import httpx

from gtm_core.decision.backends import ClefBackend
from gtm_core.decision.engine import _run, resolve_backend
from gtm_core.decision.model import DecisionModel

MODEL = DecisionModel.from_dict("icp", {"questions": [
    {"id": "uses_ai", "kind": "bool", "ask": "Does the company run AI in production?", "weight": 1},
    {"id": "regulated", "kind": "bool", "ask": "Is the company in a regulated industry?", "weight": 1,
     "rules": {"yes_any": ["bank"]}},
    {"id": "pain", "kind": "choice", "ask": "Main sales pain?", "options": {"pipeline": 1, "forecast": 0.5, "ramp": 0.3}},
    {"id": "fit", "kind": "score", "ask": "How well does it fit?", "weight": 2},
    {"id": "urgency", "kind": "score", "ask": "How urgent?"},
    {"id": "size", "kind": "score", "ask": "How large?"}]})


class Ctx:
    class settings:
        offline = False

    def __init__(self):
        self.logged = []
        self.audit = type("A", (), {"log": lambda _s, ev, **kw: self.logged.append((ev, kw))})()


def clef_client(seen, answers=None, success=True):
    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json={"success": success, "errors": [] if success else [{"message": "bad"}],
                                         "result": {"answers": answers or {}}})
    return httpx.Client(transport=httpx.MockTransport(handler))


ANSWERS = {
    "uses_ai": {"noul": 0.91},
    "regulated": {"noul": 0.55},                                                # too unsure: falls back to rules
    "pain": {"choice": "forecast", "confidence": 0.82, "probabilities": {"pipeline": 0.1, "forecast": 0.82, "ramp": 0.08}},
    "fit": {"probabilities": {"1": 0.0, "2": 0.05, "3": 0.1, "4": 0.75, "5": 0.1}},
    "urgency": {"probabilities": [0.05, 0.05, 0.8, 0.05, 0.05]},                # index list: position 2 is level 3
    "size": {"probabilities": {"0": 0.02, "1": 0.03, "2": 0.05, "3": 0.1, "4": 0.8},
             "legend": {"0": "1", "1": "2", "2": "3", "3": "4", "4": "5"}},     # keyed by index, named by legend
}


def test_request_shape_and_reading_every_kind():
    seen = {}
    b = ClefBackend(Ctx(), "acct123", "tok", "clef-flash", 0.7, client=clef_client(seen, ANSWERS))
    got = b.answer(MODEL, {"account": {"name": "Northwind", "industry": "Banking"}})
    assert seen["url"] == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/run/@cf/cloudflare/clef-flash"
    assert seen["auth"] == "Bearer tok"
    q = seen["body"]["questions"]
    assert q["uses_ai"] == {"type": "noul", "instructions": "Does the company run AI in production?"}
    assert q["pain"]["type"] == "choice" and q["pain"]["criteria"] == ["forecast", "pipeline", "ramp"]
    assert q["fit"]["criteria"] == ["1", "2", "3", "4", "5"]
    assert {k: (a.value, a.confidence) for k, a in got.items()} == {
        "uses_ai": (True, 0.91), "pain": ("forecast", 0.82), "fit": (4, 0.75), "urgency": (3, 0.8), "size": (5, 0.8)}
    assert all(a.source == "clef" and a.evidence.startswith("clef p=") for a in got.values())


def test_low_confidence_and_errors_fall_back_to_rules(monkeypatch):
    ctx = Ctx()
    ctx.decision_client = clef_client({}, ANSWERS)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_AUTH_TOKEN", "t")
    cfg = {"backend": "auto", "clef": {"min_confidence": 0.7}}
    assert resolve_backend(ctx, cfg) == "clef"
    answers, used = _run(ctx, cfg, "clef", MODEL, {"account": {"name": "Northwind", "industry": "bank"}})
    assert used == "clef" and answers["regulated"].source == "rules" and answers["regulated"].value is True
    bad = ClefBackend(Ctx(), "a", "t", client=clef_client({}, ANSWERS, success=False))
    assert bad.answer(MODEL, {}) == {}
    assert ClefBackend(Ctx(), None, "t").available() is False
    off = Ctx()
    off.settings = type("S", (), {"offline": True})
    assert ClefBackend(off, "a", "t").available() is False


def test_invalid_choice_is_rejected_not_coerced():
    ctx = Ctx()
    b = ClefBackend(ctx, "a", "t", client=clef_client({}, {"pain": {"choice": "pricing", "confidence": 0.99}}))
    assert b.answer(MODEL, {}) == {}
    assert ctx.logged and ctx.logged[0][0] == "decision.invalid"
