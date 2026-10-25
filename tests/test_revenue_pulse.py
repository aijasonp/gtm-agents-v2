from datetime import datetime, timezone

import pytest

from gtm_core.agents import Manifest, load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def manifests():  # only this agent, so the test does not depend on other agents' folders
    return {"revenue-pulse": Manifest.load("agents/revenue-pulse")}


def _seed(ctx):
    rows = [
        {"id": "A", "name": "Contoso", "owner": "Sam Rivera", "stage": "Proposal", "status": "open", "amount": 100000,
         "close_date": "2026-10-10", "created_at": "2026-09-01", "last_activity_at": "2026-09-20", "forecast_category": "commit"},
        {"id": "B", "name": "Northwind", "owner": "Priya Shah", "stage": "Evaluation", "status": "open", "amount": 50000,
         "close_date": "2026-12-01", "created_at": "2026-10-20", "last_activity_at": "2026-10-22", "next_step": "Pilot"},
        {"id": "W", "name": "Litware", "owner": "Sam Rivera", "stage": "Closed Won", "status": "won", "amount": 1300000,
         "close_date": "2026-10-02", "created_at": "2026-05-01"},
    ]
    for r in rows:
        ctx.store.upsert("deals", r)


def test_quota_met_and_rule_based_risks(ctx_for):
    ctx = ctx_for("revenue-pulse")
    _seed(ctx)
    eng = load_module(ctx.manifest, "engine")
    p = eng.pulse(ctx, now=NOW)
    assert p["quarter"]["remaining"] == 0 and p["quarter"]["coverage"] is None
    assert "coverage quota met" in eng.format_pulse(p)
    r = p["top_risks"][0]
    assert r["deal_id"] == "A" and r["source"] == "rules" and r["risk"] == 30 + 25 + 15
    assert "no activity" in r["why"] and "close date passed" in r["why"]
    assert all(x["deal_id"] != "W" for x in p["top_risks"])


def test_weekly_job_then_deltas(ctx_for):
    ctx = ctx_for("revenue-pulse")
    _seed(ctx)
    jobs = load_module(ctx.manifest, "jobs")
    first = jobs.weekly_pulse(ctx, now=NOW)
    assert first["wow"] == {} and first["summary_source"] == "template"
    ctx.store.upsert("deals", {"id": "B", "amount": 80000})
    second = jobs.weekly_pulse(ctx, now=NOW)
    assert second["wow"]["open_pipeline"] == 30000
    assert "(+$30,000)" in ctx.slack.sent[-1]["text"]


def test_tools(ctx_for):
    ctx = ctx_for("revenue-pulse")
    _seed(ctx)
    t = bind_tools(ctx)
    s = t["pipeline_summary"]()
    assert s["open_pipeline"] == 150000 and "Revenue Pulse" in s["text"]
    assert t["pipeline_summary"](owner="Priya Shah")["open_pipeline"] == 50000
    assert t["stale_deals"](days=14)["count"] == 1
    assert t["top_risks"](limit=1)["count"] == 1
    sc = t["owner_scorecard"](owner="Sam Rivera")
    assert sc["open_pipeline"] == 100000 and sc["stale_count"] == 1 and sc["won_qtd"] == 1300000
    assert "error" in t["owner_scorecard"](owner="Nobody")
    fr = t["forecast_rollup"]()
    assert set(fr) == {"month", "quarter", "by_owner"}
