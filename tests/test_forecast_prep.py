from datetime import datetime, timezone

import pytest
import yaml

from gtm_core.agents import Manifest, load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


@pytest.fixture
def manifests():  # only this agent, so the test does not depend on other agents' folders
    return {"forecast-prep": Manifest.load("agents/forecast-prep")}


def _seed(ctx):
    spec = yaml.safe_load(open("agents/forecast-prep/evals/golden.yaml"))
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    for i in spec["inspections"]:
        ctx.store.add_insight("deal-inspection", "deal_inspection", i["deal_id"], {"risk": i["risk"], "gaps": i["gaps"]},
                              deal_id=i["deal_id"])


def test_tools_bind_and_return_text(ctx_for):
    ctx = ctx_for("forecast-prep")
    _seed(ctx)
    tools = bind_tools(ctx)
    assert set(tools) == {"ae_prep", "manager_prep", "exec_prep", "forecast_changes", "call_agenda"}
    assert "Forecast prep: Sam Rivera" in tools["ae_prep"](owner="Sam Rivera")["text"]
    assert "Forecast rollup" in tools["manager_prep"]()["text"]
    assert tools["call_agenda"](level="ae")["error"]
    ag = tools["call_agenda"](level="manager")
    assert ag["total_minutes"] == sum(i["minutes"] for i in ag["items"]) and any("Rep:" in i["topic"] for i in ag["items"])


def test_weekly_job_posts_and_snapshots(ctx_for):
    ctx = ctx_for("forecast-prep")
    _seed(ctx)
    channels = []
    ctx.slack.post = lambda text, **kw: ctx.slack.sent.append({"text": text}) or channels.append(kw.get("channel")) or {"ok": True}
    jobs = load_module(ctx.manifest, "jobs")
    res = jobs.forecast_prep(ctx, now=NOW)
    assert res["reps"] == 3 and res["flags"] == 3
    assert channels[-1] == "#forecast" and "Forecast rollup" in ctx.slack.sent[-1]["text"]
    eng = load_module(ctx.manifest, "engine")
    snaps = ctx.store.get_state(eng.SNAP_KEY)
    assert snaps[-1]["org"]["commit"] == 496000 and snaps[-1]["reps"]["Sam Rivera"]["suggested"] == 96000
    jobs.forecast_prep(ctx, now=NOW)  # same day reruns replace, not duplicate
    assert len(ctx.store.get_state(eng.SNAP_KEY)) == 1


def test_model_writes_only_the_summary(ctx_for, monkeypatch):
    from gtm_core import writer
    ctx = ctx_for("forecast-prep")
    _seed(ctx)
    seen = {}

    def fake(ctx_, task, facts, fallback, max_words=200):
        seen.update(facts)
        return "- model bullet", "model"
    monkeypatch.setattr(writer, "narrate", fake)
    p = load_module(ctx.manifest, "engine").ae_prep(ctx, "Sam Rivera", NOW)
    assert p["summary"] == "- model bullet" and p["suggested_commit"] == 96000
    assert seen["suggested_commit"] == 96000


def test_no_quota_and_no_deals(ctx_for, monkeypatch):
    from gtm_core import profile
    ctx = ctx_for("forecast-prep")
    monkeypatch.setattr(profile, "company", lambda c: {"team": {"owners": [{"name": "Solo"}]}})
    p = load_module(ctx.manifest, "engine").ae_prep(ctx, "Solo", NOW)
    assert p["quota"] is None and p["coverage"] is None and p["quarter_totals"]["commit"] == 0
    assert "no quota set" in load_module(ctx.manifest, "engine").format_ae(p)
