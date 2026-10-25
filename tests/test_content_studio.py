import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import yaml

from gtm_core.agents import load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
SPEC = yaml.safe_load(Path("agents/content-studio/evals/golden.yaml").read_text())


def _ctx(ctx_for):
    ctx = ctx_for("content-studio")
    spec = importlib.util.spec_from_file_location("cs_eval", "agents/content-studio/evals/evaluator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.setup(ctx, SPEC)
    return ctx


def test_tools_bind(ctx_for):
    ctx = _ctx(ctx_for)
    t = bind_tools(ctx)
    assert set(t) == {"linkedin_post", "publish_post", "video_script", "captions", "frame_qa"}
    assert t["captions"](script_or_draft_id="999")["error"]
    assert t["publish_post"](draft_id=999)["error"]
    assert t["frame_qa"](frames=[])["passed"]


def test_social_post_executor_without_webhook(ctx_for, monkeypatch):
    monkeypatch.delenv("GTM_SOCIAL_WEBHOOK", raising=False)
    ctx = _ctx(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    p = eng.linkedin_post(ctx, "Why forecast calls go sideways", now=NOW)
    rid = eng.publish_post(ctx, p["draft_id"])["queued_for_approval"]
    load_module(ctx.manifest, "jobs").register_executors(ctx)
    ctx.approvals.decide(rid, True)
    [res] = ctx.approvals.execute_approved()
    assert res["result"]["manual"]
    assert ctx.store.query("SELECT status FROM drafts WHERE id=?", (p["draft_id"],))[0]["status"] == "approved_manual"


def test_publish_refuses_failing_or_wrong_kind(ctx_for):
    ctx = _ctx(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    bad = ctx.store.add_draft("content-studio", "linkedin_post", "x", gate_score=10, gate_passed=False)
    assert "Copy QA Gate" in eng.publish_post(ctx, bad)["error"]
    v = eng.video_script(ctx, "Short topic", 30, now=NOW)
    assert "not a post" in eng.publish_post(ctx, v["draft_id"])["error"]


def test_frame_reading_time_uses_next_frame(ctx_for):
    ctx = _ctx(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    frames = [{"t": 0, "text": "one two three four five six", "x": 200, "y": 500, "w": 600, "h": 100},
              {"t": 1, "text": "ok", "x": 200, "y": 500, "w": 600, "h": 100}]
    r = eng.frame_qa(ctx, frames, duration=3)
    assert not r["passed"] and r["failed_frames"] == 1 and "needs 1.8s" in r["issues"][0]
