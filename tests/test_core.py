import json
from datetime import date

import pytest

from gtm_core import copy_gate, license as lic
from gtm_core.approvals import executor
from gtm_core.audit import mask
from gtm_core.budgets import BudgetExceeded, Budgets
from gtm_core.guardrails import LoopLimitExceeded, StepCounter
from gtm_core.store import Store


def test_approval_flow(ctx_for):
    ctx = ctx_for("signal-scout")
    calls = []

    @executor("test_action")
    def _run(payload):
        calls.append(payload)
        return {"ok": True}

    rid = ctx.approvals.request("test_action", {"x": 1})
    assert ctx.approvals.execute_approved() == []  # nothing approved yet
    ctx.approvals.decide(rid, True)
    assert ctx.approvals.execute_approved()[0]["result"] == {"ok": True}
    assert calls == [{"x": 1}]
    with pytest.raises(ValueError):
        ctx.approvals.decide(rid, True)


def test_budget_pauses_and_alerts():
    st = Store("sqlite:///:memory:"); st.init()
    alerts = []
    b = Budgets(st, daily_tokens=100, notify=alerts.append)
    b.record("a", "m", "cheap", 80, 30)
    with pytest.raises(BudgetExceeded):
        b.check()
    assert b.paused() and alerts
    b.resume()
    assert not b.paused()


def test_step_counter():
    with pytest.raises(LoopLimitExceeded):
        with StepCounter(limit=2) as s:
            for _ in range(3):
                s.tick()


def test_mask_hides_secrets():
    out = mask({"api_key": "abc", "note": "Bearer sk-ant-1234567890abcdef"})
    assert out["api_key"] == "***" and "sk-ant" not in out["note"]


def test_copy_gate_scores():
    good = "Saw you joined Northwind last month. We rank your accounts each morning on fit and fresh signals. Worth 15 minutes next week?"
    assert copy_gate.check(good).passed
    assert not copy_gate.check("I hope this email finds you well! We leverage synergy. 10x growth guaranteed! Call? Now? Later?").passed


def test_license_roundtrip(tmp_path):
    priv, pub = lic.keygen(tmp_path)
    doc = lic.issue(priv.read_bytes(), "Acme", ["signal-scout"], "2027-10-23")
    ok = lic.verify(doc, pub.read_bytes(), today=date(2026, 10, 23))
    assert ok["valid"] and not ok["expired"]
    assert lic.verify(doc, pub.read_bytes(), today=date(2028, 1, 1))["expired"]
    doc["agents"] = ["signal-scout", "deal-intel"]
    assert not lic.verify(doc, pub.read_bytes())["valid"]
