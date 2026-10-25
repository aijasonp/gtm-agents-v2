import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from gtm_core.agents import load_module
from gtm_core.gateway import Gateway
from gtm_core.mcp_server import bind_tools

ROOT = Path("agents/product-marketing")
SPEC = yaml.safe_load((ROOT / "evals/golden.yaml").read_text())
NOW = datetime.fromisoformat(SPEC["now"])


def _seed(ctx):
    spec = importlib.util.spec_from_file_location("pm_eval", ROOT / "evals/evaluator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seed(ctx, SPEC)


def test_tools_are_bound_and_readable(ctx_for):
    ctx = ctx_for("product-marketing")
    _seed(ctx)
    tools = bind_tools(ctx)
    assert set(tools) == {"competitor_intel", "battlecard", "win_loss_report", "objection_library", "messaging_brief",
                          "launch_brief"}
    lib = tools["objection_library"](since_days=3650)
    assert lib["categories"][0]["category"] == "price"
    lb = tools["launch_brief"](feature="Deal inspection alerts", audience="RevOps leaders")
    assert "TODO" in lb["text"] and "Weekly MEDDPICC" in lb["text"]


def test_battlecard_persists_draft_and_insight(ctx_for):
    ctx = ctx_for("product-marketing")
    _seed(ctx)
    card = load_module(ctx.manifest, "engine").battlecard(ctx, "Acme Intel", now=NOW)
    assert card["summary_source"] == "template"
    assert ctx.store.drafts("product-marketing")[0]["kind"] == "battlecard"
    stored = ctx.store.insights("battlecard")[0]
    assert stored["key"] == "Acme Intel" and stored["value"]["lost"] == 1
    assert "—" not in card["text"]
    assert ctx.approvals.list(None) == []  # internal docs: nothing queued for the CRM


def test_jobs_post_to_slack(ctx_for):
    ctx = ctx_for("product-marketing")
    _seed(ctx)
    jobs = load_module(ctx.manifest, "jobs")
    r = jobs.weekly_field_report(ctx, now=NOW)
    assert r["new_objections"] == ["timing"]
    assert "field report" in ctx.slack.sent[-1]["text"]
    r = jobs.battlecard_refresh(ctx, now=NOW)
    assert r["refreshed"] == 3 and r["new_competitors"] == ["Initech"]
    assert "Initech" in ctx.slack.sent[-1]["text"]


def test_model_only_polishes_summary(ctx_for):
    ctx = ctx_for("product-marketing")
    _seed(ctx)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Acme Intel shows up on price."}],
                                         "usage": {"input_tokens": 10, "output_tokens": 5}})
    ctx.settings.anthropic_api_key = "k"; ctx.settings.offline = False
    ctx.gateway = Gateway(ctx.settings, ctx.budgets, ctx.manifest.id,
                          client=httpx.Client(transport=httpx.MockTransport(handler)))
    card = load_module(ctx.manifest, "engine").battlecard(ctx, "Acme Intel", now=NOW)
    assert card["summary"] == "Acme Intel shows up on price." and card["summary_source"] == "model"
    assert card["where_they_win"][0] == "chose Acme Intel on price (1)"  # computed, not model-written
    assert len(seen) == 1


def test_no_evidence_is_honest(ctx_for):
    ctx = ctx_for("product-marketing")
    eng = load_module(ctx.manifest, "engine")
    card = eng.battlecard(ctx, "Globex Signals", now=datetime(2026, 10, 23, tzinfo=timezone.utc), persist=False)
    assert card["win_rate"] is None and "no closed deals yet" in card["text"]
    assert any("Where they win" in v for v in card["to_verify"])
