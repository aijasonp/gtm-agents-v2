from datetime import datetime, timezone
from pathlib import Path

import yaml

from gtm_core.agents import Manifest, load_module
from gtm_core.executors import register_core_executors
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
SPEC = yaml.safe_load(Path("agents/event-campaigns/evals/golden.yaml").read_text())


def _ctx(ctx_for):
    ctx = ctx_for("event-campaigns")
    import importlib.util
    spec = importlib.util.spec_from_file_location("ec_eval", "agents/event-campaigns/evals/evaluator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.setup(ctx, SPEC)
    return ctx


def test_tools_bind_and_errors(ctx_for):
    ctx = _ctx(ctx_for)
    t = bind_tools(ctx)
    assert set(t) == {"list_events", "build_invite_list", "draft_invites", "import_attendees", "event_report"}
    assert t["list_events"]()["count"] == 3
    assert t["build_invite_list"](event_id="nope")["error"]
    assert t["event_report"](event_id="nope")["error"]
    assert t["import_attendees"](event_id="chi-revenue-dinner", file="/missing.csv")["error"]


def test_webinar_has_no_region(ctx_for):
    ctx = _ctx(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    lst = eng.build_invite_list(ctx, "forecast-webinar", NOW)
    ids = [a["account_id"] for a in lst["accounts"]]
    assert "fabrikam.example" in ids  # Canada is fine for a webinar
    assert "contoso.example" not in ids  # open deal still blocks


def test_invite_sends_through_sequencer_after_approval(ctx_for, tmp_path):
    ctx = _ctx(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    eng.draft_invites(ctx, "chi-revenue-dinner", 1, NOW)
    [appr] = ctx.approvals.list()
    register_core_executors(ctx)
    ctx.approvals.decide(appr["id"], True, by="Sam Rivera")
    ctx.approvals.execute_approved()
    sent = ctx.sequencer.sent[0]
    assert sent["campaign"] == "chi-revenue-dinner" and sent["contact"]["email"] == "dana@northwind.example"
    assert sent["meta"]["step"] == "event_invite"
    f = tmp_path / "reg.csv"
    f.write_text("Name,Email,Company,Title,Attended\nDana Cole,dana@northwind.example,Northwind,VP of Sales,Yes\n")
    r = eng.import_attendees(ctx, "chi-revenue-dinner", file=str(f), now=NOW)
    assert r["added"] == 1 and r["signals_added"] == 1
