from datetime import datetime, timezone
from pathlib import Path

import pytest

from gtm_core.agents import Manifest, load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
EV = Path("agents/call-coach/evals")


@pytest.fixture
def manifests():
    return {"call-coach": Manifest.load("agents/call-coach")}


def test_tools_bind_and_roleplay(ctx_for):
    ctx = ctx_for("call-coach")
    t = bind_tools(ctx)
    assert set(t) == {"list_scenarios", "start_roleplay", "score_roleplay", "drill_plan"}
    types = {s["type"] for s in t["list_scenarios"]()["scenarios"]}
    assert types == {"discovery", "objection", "pricing", "competitor", "champion"}
    r = t["start_roleplay"](scenario="competitor_globex_signals", persona="revops")
    assert "Globex Signals" in r["buyer_prompt"] and r["brief"]["you_are_calling"] == "Director of Revenue Operations"
    assert "error" in t["start_roleplay"](scenario="nope")


def test_scoring_rubric(ctx_for):
    t = bind_tools(ctx_for("call-coach"))
    good = t["score_roleplay"](transcript=(EV / "good-discovery.txt").read_text(), scenario="discovery_first_call")
    weak = t["score_roleplay"](transcript=(EV / "weak-discovery.txt").read_text(), scenario="discovery_first_call")
    assert good["total"] >= 90 and weak["total"] <= 30
    assert sum(good["max"].values()) == 100
    assert len(weak["top_fixes"]) == 3 and all(f["measured"] and f["fix"] for f in weak["top_fixes"])
    assert weak["points"]["talk_ratio"] == 0 and "93%" in weak["measured"]["talk_ratio"]
    assert "error" in t["score_roleplay"](transcript="hello")
    assert "error" in t["score_roleplay"](transcript="A: hi\nB: hi", scenario="nope")


def test_rep_label_and_first_speaker_fallback(ctx_for):
    t = bind_tools(ctx_for("call-coach"))
    r = t["score_roleplay"](transcript="Rep: What is your biggest problem today?\nBuyer: Lists by hand.")
    assert r["rep_speakers"] == ["Rep"]
    r = t["score_roleplay"](transcript="Alex: How do you plan the week?\nJo: Spreadsheets.")
    assert r["rep_speakers"] == ["Alex"]


def test_weekly_drills_job(ctx_for):
    ctx = ctx_for("call-coach")
    weak = (EV / "weak-discovery.txt").read_text()
    ctx.store.upsert("meetings", {"id": "m1", "owner": "Sam Rivera", "started_at": "2026-10-20T15:00:00+00:00", "transcript": weak})
    out = load_module(ctx.manifest, "jobs").weekly_drills(ctx, now=NOW)
    assert out["with_drills"] == 1 and len(out["plans"]["Sam Rivera"]) == 3
    assert "Sam Rivera" in ctx.slack.sent[-1]["text"] and "run `" in ctx.slack.sent[-1]["text"]
    assert out["plans"]["Priya Shah"] == []
    assert ctx.approvals.list() == []  # coaching never queues CRM writes


def test_drill_plan_reads_coaching_insights(ctx_for):
    ctx = ctx_for("call-coach")
    ctx.store.add_insight("meeting-intelligence", "coaching", "next_step", {"rep": "Lee Park", "pct": 20})
    p = bind_tools(ctx)["drill_plan"](rep="Lee Park", days=30)
    assert p["drills"][0]["skill"] == "next_step"
