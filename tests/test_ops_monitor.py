from datetime import datetime, timezone

import pytest

from gtm_core.agents import Manifest, load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 11, 2, 10, tzinfo=timezone.utc)


@pytest.fixture
def manifests():  # only this agent, so the test does not depend on other agents' folders
    return {"ops-monitor": Manifest.load("agents/ops-monitor")}


def _ms():
    return {a: Manifest.load(f"agents/{a}") for a in ("ops-monitor", "signal-scout")}


def test_tools_bind(ctx_for):
    ctx = ctx_for("ops-monitor")
    tools = bind_tools(ctx)
    assert set(tools) == {"health_report", "job_status", "stuck_items", "spend_report", "export_traces"}
    assert "skipped" in tools["export_traces"]()  # Langfuse not configured
    s = tools["stuck_items"]()
    assert s["approvals_executing"] == [] and s["runs_stuck"] == []
    assert tools["spend_report"](days=3)["total_tokens"] == 0


def test_health_job_alerts_only_on_change(ctx_for, monkeypatch):
    ctx = ctx_for("ops-monitor")
    eng = load_module(ctx.manifest, "engine")
    monkeypatch.setattr(eng, "manifests_for", lambda c, m=None: _ms())
    monkeypatch.setattr("gtm_core.agents.DISCOVERY_ERRORS", {})
    jobs = load_module(ctx.manifest, "jobs")
    r1 = jobs.health_check(ctx, now=NOW)
    assert r1["new_problems"] > 0 and "never run" in ctx.slack.sent[-1]["text"]  # fresh install: jobs never ran
    n = len(ctx.slack.sent)
    assert jobs.health_check(ctx, now=NOW)["new_problems"] == 0 and len(ctx.slack.sent) == n
    ctx.store.execute("INSERT INTO runs (id, agent, job, started_at, status) VALUES ('x','signal-scout','daily_sweep',?,'ok')",
                      ("2026-11-02T06:00:01+00:00",))
    r3 = jobs.health_check(ctx, now=NOW)
    assert r3["recovered"] == 1 and "Recovered" in ctx.slack.sent[-1]["text"]
    d = jobs.daily_ops_summary(ctx, now=NOW)
    assert d["runs_24h"] == {"ok": 1} and "daily summary" in ctx.slack.sent[-1]["text"]


def test_spend_against_budget(ctx_for, monkeypatch):
    ctx = ctx_for("ops-monitor")
    eng = load_module(ctx.manifest, "engine")
    ctx.store.insert("INSERT INTO token_usage (ts, agent, model, input_tokens, output_tokens, usd) VALUES (?,?,?,?,?,?)",
                     ("2026-11-02T09:00:00+00:00", "signal-scout", "m", 2100000, 0, 9.5))
    rows = eng.spend(ctx, _ms(), 1, NOW)
    assert rows[0]["pct_of_budget"] == 105.0
    assert eng.spend_checks(ctx, _ms(), NOW)[0]["status"] == "fail"


def test_paused_and_stuck_replies_detected(ctx_for, manifests):
    from datetime import datetime, timezone
    from gtm_core.agents import load_module
    ctx = ctx_for("ops-monitor")
    eng = load_module(manifests["ops-monitor"], "engine")
    ctx.store.set_state("paused:lead-triage", True)
    assert any(c["status"] == "fail" for c in eng.pause_checks(ctx))
    assert eng.reply_checks(ctx, datetime(2026, 10, 23, tzinfo=timezone.utc)) == []  # no replies table yet: skipped
    ctx.store.execute("CREATE TABLE replies (id TEXT PRIMARY KEY, status TEXT, created_at TEXT, reason TEXT)")
    ctx.store.execute("INSERT INTO replies VALUES ('r1','error','2026-10-22T00:00:00+00:00','boom')")
    ctx.store.execute("INSERT INTO replies VALUES ('r2','handling','2026-10-22T00:00:00+00:00','')")
    out = {c["id"]: c["status"] for c in eng.reply_checks(ctx, datetime(2026, 10, 23, tzinfo=timezone.utc))}
    assert out == {"replies:stuck": "warn", "replies:error": "fail"}
