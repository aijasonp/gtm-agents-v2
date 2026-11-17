from datetime import datetime, timezone

import pytest

from gtm_core.agents import Manifest, load_module
from gtm_core.executors import register_core_executors

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


@pytest.fixture
def manifests():
    return {"account-health": Manifest.load("agents/account-health")}


def _seed(ctx, eng):
    ctx.store.upsert_account({"id": "acme.example", "name": "Acme", "domain": "acme.example", "crm_id": "C9",
                              "customer": True, "arr": 100000, "seats": 20, "renewal_date": "2027-01-10", "owner": "Lee Park"})
    for at, v in (("2026-09-20", 20), ("2026-10-25", 12)):
        assert eng.add_usage(ctx, "acme.example", "wau", v, at)["ok"]


def test_tools_match_manifest(ctx_for):
    ctx = ctx_for("account-health")
    tools = load_module(ctx.manifest, "tools").TOOLS
    assert set(tools) == set(ctx.manifest.tools)


def test_alias_and_drop(ctx_for):
    ctx = ctx_for("account-health")
    eng = load_module(ctx.manifest, "engine")
    _seed(ctx, eng)
    x = eng.assess(ctx, ctx.store.account("acme.example"), NOW)
    assert "usage_drop" in x["risk_keys"]
    assert x["usage"]["metrics"]["active_users"]["change"] == -0.4
    assert x["days_to_renewal"] is not None and x["renewal_window"]


def test_usage_upsert_same_day(ctx_for):
    ctx = ctx_for("account-health")
    eng = load_module(ctx.manifest, "engine")
    _seed(ctx, eng)
    r = eng.add_usage(ctx, "acme.example", "active_users", 13, "2026-10-25")
    assert r["ok"] and r["updated"]
    assert len(eng.usage_rows(ctx, "acme.example")) == 2


def test_approved_task_executes(ctx_for):
    ctx = ctx_for("account-health")
    register_core_executors(lambda: ctx)
    eng = load_module(ctx.manifest, "engine")
    _seed(ctx, eng)
    ctx.store.upsert("meetings", {"id": "m1", "account_id": "acme.example", "started_at": "2026-11-01T10:00:00+00:00",
                                  "summary": "They said the price increase means they may switch to another vendor."})
    res = eng.assess_all(ctx, now=NOW)
    assert res[0]["recommendation"] == "save"
    ch = eng.changes(ctx, res, NOW)
    assert len(ch["tasks_queued"]) == 1
    a = ctx.approvals.list()[0]
    assert a["action"] == "crm_task" and a["status"] == "pending"
    assert a["payload"]["account_crm_id"] == "C9" and a["payload"]["owner"] == "Lee Park"


def test_negation_window():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ah_engine", "agents/account-health/engine.py")
    eng = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eng)
    assert eng._phrase_hits("We won't cancel this year.", ["cancel"]) == []
    assert eng._phrase_hits("Legal wants to cancel.", ["cancel"])[0][0] == "cancel"
    assert eng._phrase_hits("We expanded the team.", ["expand"]) == []
