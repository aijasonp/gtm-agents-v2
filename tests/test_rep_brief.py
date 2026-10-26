from datetime import datetime, timezone

import yaml

from gtm_core.agents import load_module
from gtm_core.executors import register_core_executors
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 9, tzinfo=timezone.utc)


def _seeded(ctx_for):
    ctx = ctx_for("rep-brief")
    spec = yaml.safe_load(open("agents/rep-brief/evals/golden.yaml"))
    import importlib.util
    s = importlib.util.spec_from_file_location("rb_eval", "agents/rep-brief/evals/evaluator.py")
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    mod.seed(ctx, spec, load_module(ctx.manifest, "engine"))
    return ctx


def test_tools_and_unknown_owner(ctx_for):
    ctx = _seeded(ctx_for)
    t = bind_tools(ctx)
    b = t["my_brief"](owner="sam")
    assert b["owner"] == "Sam Rivera" and "Your brief, Sam Rivera" in b["text"] and "Do next" in b["text"]
    assert "error" in t["my_brief"](owner="Nobody Here")
    assert t["top_accounts"](owner="Sam Rivera", limit=2)["count"] == 2
    assert t["pipeline_gaps"](owner="Sam Rivera")["open_deals"] == 2
    assert "signals" in t["whats_new"](owner="Sam Rivera", since_hours=1000000)


def test_push_button_executes_through_approvals(ctx_for):
    ctx = _seeded(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    r = eng.push_button(ctx, "fourthcoffee.example", "rosa@fourthcoffee.example", now=NOW)
    assert not r["refused"] and len(r["approvals"]) == 3 and r["call_script"].count("\n") == 2
    register_core_executors(ctx)
    for a in ctx.approvals.list():
        ctx.approvals.decide(a["id"], True, by="Sam Rivera")
    res = ctx.approvals.execute_approved()
    assert all("result" in x for x in res), res
    assert ctx.sequencer.sent[0]["contact"]["email"] == "rosa@fourthcoffee.example"
    assert ctx.dialer.queued[0]["contact"]["phone"] == "+1 555 0100"
    assert ctx.crm.writes[-1]["kind"] == "task"


def test_gate_failure_queues_nothing(ctx_for, monkeypatch):
    from gtm_core import writer
    ctx = _seeded(ctx_for)
    monkeypatch.setattr(writer, "write", lambda *a, **k: writer.Draft("s", "slop!!!", 10, False, "model", 3, ["banned"]))
    r = load_module(ctx.manifest, "engine").push_button(ctx, "fourthcoffee.example", "rosa@fourthcoffee.example", now=NOW)
    assert r["needs_rewrite"] and r["approvals"] == [] and ctx.approvals.list() == []
    assert ctx.store.drafts()[0]["status"] == "needs_rewrite"


def test_opted_out_contact_is_never_pushed_or_suggested(ctx_for):
    from gtm_core import suppression
    ctx = _seeded(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    suppression.suppress(ctx.store, "rosa@fourthcoffee.example", "opt-out: remove me")
    r = eng.push_button(ctx, "fourthcoffee.example", "rosa@fourthcoffee.example", now=NOW)
    assert r["refused"] and not r.get("approvals") and not ctx.approvals.list()
    assert any("must not be contacted" in w or "no reachable" in w for w in r["reasons"])
    acct = ctx.store.account("fourthcoffee.example")
    assert all(p["email"] != "rosa@fourthcoffee.example" for p in eng.pick_contacts(ctx, acct, NOW))


def test_bad_amounts_never_stop_the_brief(ctx_for):
    ctx = _seeded(ctx_for)
    eng = load_module(ctx.manifest, "engine")
    assert eng.amount("12,000") == 12000 and eng.amount("$12k") == 12000 and eng.amount("1.5m") == 1500000
    assert eng.amount("call me") == 0
    ctx.store.execute("UPDATE deals SET amount=NULL")
    ctx.store.upsert("deals", {"id": "weird", "owner": "Sam Rivera", "status": "open", "stage": "Evaluation",
                               "name": "Weird", "last_activity_at": "not a date"})
    res = load_module(ctx.manifest, "jobs").daily_briefs(ctx, now=NOW)
    assert "Sam Rivera" in res["reps"] and not res["failed"]
