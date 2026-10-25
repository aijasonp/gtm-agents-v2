from pathlib import Path

from gtm_core.agents import load_module
from gtm_core.importers import import_accounts, import_outcomes, import_signals
from gtm_core.mcp_server import bind_tools

SAMPLE = Path("data/sample")


def _loaded(ctx):
    import_accounts(ctx, SAMPLE / "accounts.csv")
    import_signals(ctx, SAMPLE / "signals.csv")
    return ctx


def test_daily_sweep_end_to_end(ctx_for):
    ctx = _loaded(ctx_for("signal-scout"))
    res = load_module(ctx.manifest, "jobs").daily_sweep(ctx)
    assert res["accounts"] == 10
    assert res["tiers"]["X"] == 1
    assert ctx.slack.sent and "Northwind Logistics" in ctx.slack.sent[0]["text"]
    assert "{" not in ctx.slack.sent[0]["text"]
    assert res["crm_updates_queued"] >= 3
    assert all(r["status"] == "pending" for r in ctx.approvals.list())


def test_tools_match_manifest(ctx_for):
    ctx = _loaded(ctx_for("signal-scout"))
    tools = bind_tools(ctx)
    assert set(tools) == set(ctx.manifest.tools)
    top = tools["list_priority_accounts"](limit=2)
    assert top["accounts"][0]["name"] == "Northwind Logistics"
    added = tools["add_signal"](account="tailspin.example", signal_type="funding_round", url="https://example.com/t9")
    assert added["added"] and not tools["add_signal"](account="tailspin.example", signal_type="funding_round",
                                                       url="https://example.com/t9")["added"]
    q = tools["push_to_crm"](account="northwind.example")
    assert "queued_for_approval" in q


def test_weekly_reweight_learns(ctx_for):
    ctx = _loaded(ctx_for("signal-scout"))
    for i in range(6):
        aid = f"acct{i}.example"
        ctx.store.upsert_account({"id": aid, "name": aid})
        ctx.store.add_signal({"id": f"s{i}", "account_id": aid, "signal_type": "event_attended", "category": "intent",
                              "observed_at": "2026-10-20T00:00:00+00:00"})
        ctx.store.add_outcome(aid, "meeting" if i < 5 else "no_response")
    for i in range(6, 12):
        aid = f"acct{i}.example"
        ctx.store.upsert_account({"id": aid, "name": aid})
        ctx.store.add_outcome(aid, "no_response")
    res = load_module(ctx.manifest, "jobs").weekly_reweight(ctx)
    ch = res["changes"]["event_attended"]
    assert ch["to"] > ch["from"]
