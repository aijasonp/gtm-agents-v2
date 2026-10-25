from datetime import datetime, timedelta, timezone

import yaml

from gtm_core.agents import load_module
from gtm_core.mcp_server import bind_tools

SPEC = yaml.safe_load(open("agents/quality-monitor/evals/golden.yaml"))


def _seed(ctx, now):
    for d in SPEC["drafts"]:
        for n in d["days_ago"]:
            ctx.store.insert("INSERT INTO drafts (agent, kind, subject, body, gate_score, gate_passed, status, meta, created_at) "
                             "VALUES (?,?,?,?,?,?,?,?,?)",
                             (d["agent"], d.get("kind", "first_touch"), "s", SPEC[d["body"]], 36, 1, "sent", "{}",
                              (now - timedelta(days=n)).replace(microsecond=0).isoformat()))
    # an ungated internal draft never counts
    ctx.store.insert("INSERT INTO drafts (agent, kind, body, created_at) VALUES (?,?,?,?)",
                     ("rep-brief", "brief", "x!", now.isoformat()))


def test_tools(ctx_for):
    ctx = ctx_for("quality-monitor")
    now = datetime.now(timezone.utc)
    _seed(ctx, now)
    t = bind_tools(ctx)
    s = t["sample_drafts"](days=7, per_agent=2)
    assert {a: len(v) for a, v in s["agents"].items()} == {"icp-outbound": 2, "lead-triage": 2, "reply-desk": 2}
    rep = t["quality_report"]()
    assert rep["agents"]["reply-desk"]["pass_rate"] == 0.0 and rep["agents"]["reply-desk"]["unsourced_claims"] >= 2
    assert rep["agents"]["icp-outbound"]["pass_rate"] == 100.0
    assert [r["agent"] for r in t["regression_check"]()["regressions"]] == ["reply-desk"]
    worst = rep["agents"]["reply-desk"]["worst"]
    card = t["draft_scorecard"](draft_id=worst)
    assert not card["passed"] and any("banned_phrases" in f for f in card["failures"])
    assert t["draft_scorecard"](draft_id=99999)["error"]


def test_no_drafts_no_alert(ctx_for):
    ctx = ctx_for("quality-monitor")
    out = load_module(ctx.manifest, "jobs").daily_quality(ctx)
    assert out == {"sampled": 0, "agents": 0, "alerts": 0, "regressed": []}
    assert not ctx.slack.sent
