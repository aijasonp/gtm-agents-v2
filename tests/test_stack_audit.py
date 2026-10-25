import json
from datetime import datetime, timezone

import pytest

from gtm_core.agents import Manifest, load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)


@pytest.fixture
def manifests():  # only this agent, so the test does not depend on other agents' folders
    return {"stack-audit": Manifest.load("agents/stack-audit")}


def test_tools_bind_on_sample_inventory(ctx_for):
    ctx = ctx_for("stack-audit")
    tools = bind_tools(ctx)
    assert set(tools) == {"stack_summary", "overlap_matrix", "renewal_calendar", "savings_scenarios", "compare_lists", "cut_memo"}
    s = tools["stack_summary"]()
    assert s["tools"] == 9 and s["unknown_cost"] == ["Meeting Notes I"]
    assert tools["overlap_matrix"]()["overlapping"] == 2
    assert tools["compare_lists"](tool="X", file="/nope.txt")["error"]
    m = tools["cut_memo"](tool="Community Signals B")
    assert m["draft_id"] and "cut Community Signals B" in m["subject"]
    assert tools["cut_memo"](tool="Not A Tool")["error"]


def test_json_inventory_and_missing_fields(ctx_for, tmp_path):
    ctx = ctx_for("stack-audit")
    f = tmp_path / "inv.json"
    f.write_text(json.dumps([{"tool": "Only Tool", "capabilities": ["sequencing"], "seats_purchased": "", "annual_cost": "$12,000"},
                             {"tool": "", "capabilities": "x"}]))
    eng = load_module(ctx.manifest, "engine")
    s = eng.scenarios(ctx, str(f), NOW)
    r = s["recommendations"][0]
    assert len(s["recommendations"]) == 1 and r["action"] == "keep" and r["annual_cost"] == 12000
    assert eng.calendar(ctx, 120, str(f), NOW) == []  # no renewal date: nothing invented


def test_jobs_post_to_slack(ctx_for):
    ctx = ctx_for("stack-audit")
    jobs = load_module(ctx.manifest, "jobs")
    r = jobs.renewal_watch(ctx, now=NOW)
    assert r["alerts"] == 5 and "notice deadline" in ctx.slack.sent[-1]["text"]
    assert jobs.renewal_watch(ctx, now=NOW)["alerts"] == 0
    u = jobs.monthly_utilization(ctx, now=NOW)
    assert u["possible_savings"] == 166200 and "monthly utilization" in ctx.slack.sent[-1]["text"]
    assert "Meeting Notes I" in ctx.slack.sent[-1]["text"]
