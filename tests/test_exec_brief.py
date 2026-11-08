import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gtm_core.agents import Manifest, load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 11, 9, 12, 45, tzinfo=timezone.utc)


@pytest.fixture
def manifests():  # only this agent, so the test does not depend on other agents' folders
    return {"exec-brief": Manifest.load("agents/exec-brief")}


def _ctx(ctx_for, monkeypatch, tmp_path):
    monkeypatch.setenv("EXEC_BRIEF_SOURCE", "fixtures")
    monkeypatch.setenv("EXEC_BRIEF_FIXTURES", "data/sample/exec_brief.yaml")
    ctx = ctx_for("exec-brief")
    ctx.settings.data_dir = tmp_path
    sent = []
    ctx.slack.dm = lambda uid, text, blocks=None, **kw: sent.append({"dm": uid, "text": text, "blocks": blocks}) or {}
    ctx.slack.post = lambda text, blocks=None, channel=None, **kw: sent.append({"channel": channel, "text": text,
                                                                              "blocks": blocks}) or {}
    return ctx, sent


def test_sample_run_sends_four_briefs_and_snapshot(ctx_for, monkeypatch, tmp_path):
    ctx, sent = _ctx(ctx_for, monkeypatch, tmp_path)
    monkeypatch.setenv("EXEC_BRIEF_CEO_SLACK_ID", "UCEO")
    monkeypatch.setenv("EXEC_BRIEF_COMPANY_CHANNEL", "CALL")
    r = load_module(ctx.manifest, "jobs").daily_exec_briefs(ctx, now=NOW)
    assert [s.get("dm") for s in sent[:4]] == ["UCEO", None, None, None]  # no id: falls back to the team channel
    assert sent[4]["channel"] == "CALL" and "Company daily snapshot" in sent[4]["text"]
    assert all(len(v["metrics"]) == 5 for k, v in r["sent"].items() if k != "company")
    assert Path(r["command_center"]).read_text().startswith("<!DOCTYPE html>")
    assert all(v["read_source"] == "template" for k, v in r["sent"].items() if k != "company")


def test_second_day_shows_change_and_slips(ctx_for, monkeypatch, tmp_path):
    ctx, sent = _ctx(ctx_for, monkeypatch, tmp_path)
    eng = load_module(ctx.manifest, "engine")
    eng.run(ctx, now=NOW, renderer="python")
    rows = eng.load_rows(ctx)
    victim = next(o for o in rows["opportunities"] if o["status"] == "open" and o["close_date"] < "2026-12-31")
    victim["close_date"] = "2027-02-15"
    monkeypatch.setattr(eng, "load_rows", lambda _ctx, _cfg=None: rows)
    r = eng.run(ctx, now=NOW, roles=("cso",), company=False, renderer="python", dry_run=True)
    assert r["sent"]["cso"]["metrics"]["slipped_out_1d"]["value"] == victim["amount"]
    assert r["sent"]["cso"]["metrics"]["slipped_out_1d"]["status"] == "bad"


def test_tools(ctx_for, monkeypatch, tmp_path):
    ctx, _ = _ctx(ctx_for, monkeypatch, tmp_path)
    tools = bind_tools(ctx)
    assert len(tools["exec_metrics"](role="channel")["metrics"]) == 5
    teams = tools["company_snapshot"]()["teams"]
    assert [t["team"] for t in teams] == ["Sales", "Marketing", "Partners", "Customer Success"]
    assert tools["exec_brief_preview"](role="cmo")["spec"]["root"]
    assert len(tools["command_center"]()["weeks"]) == 8


def test_renderer_falls_back_to_python(ctx_for, monkeypatch, tmp_path):
    ctx, _ = _ctx(ctx_for, monkeypatch, tmp_path)
    eng = load_module(ctx.manifest, "engine")
    monkeypatch.setattr(eng, "_bridge_ready", lambda: True)
    monkeypatch.setattr(eng, "BRIDGE", Path("/nonexistent/render.mjs"))
    spec = {"root": "card-1", "elements": {"card-1": {"type": "Card", "props": {"title": "T"}, "children": []}}}
    blocks, text, used = eng.render(spec, "auto")
    assert used == "python" and blocks[0]["type"] == "header"
    with pytest.raises(RuntimeError):
        eng.render(spec, "chat-sdk")


@pytest.mark.skipif(not (Path("agents/exec-brief/delivery/node_modules/@json-render/chat").exists()),
                    reason="Chat SDK renderer not installed (npm ci in agents/exec-brief/delivery)")
def test_chat_sdk_renderer_makes_native_table(ctx_for, monkeypatch, tmp_path):
    ctx, _ = _ctx(ctx_for, monkeypatch, tmp_path)
    eng = load_module(ctx.manifest, "engine")
    r = eng.run(ctx, now=NOW, roles=("ceo",), renderer="chat-sdk", dry_run=True)
    blocks, _, used = eng.render(r["sent"]["company"]["spec"], "chat-sdk")
    assert used == "chat-sdk" and any(b["type"] == "data_table" for b in blocks)
    bad = {"root": "c", "elements": {"c": {"type": "Card", "props": {}, "children": ["t1", "t2"]},
                                     "t1": {"type": "Table", "props": {"headers": ["a"], "rows": [["1"]]}, "children": []},
                                     "t2": {"type": "Table", "props": {"headers": ["a"], "rows": [["1"]]}, "children": []}}}
    with pytest.raises(RuntimeError):
        eng.render(bad, "chat-sdk")


def test_snowflake_reader_refuses_writes():
    from gtm_core.sources import snowflake
    with pytest.raises(snowflake.SnowflakeError):
        snowflake.query("DELETE FROM SALESFORCE.OPPORTUNITY", conn=object())
    assert snowflake.query_many({"leads": ""}) == {"leads": []}
