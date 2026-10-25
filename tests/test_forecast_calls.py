from datetime import datetime, timezone

from gtm_core.agents import load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
LAST_Q = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _deal(st, i, owner, amount, close, status="open", cat="commit", stage="negotiation"):
    st.upsert("deals", {"id": i, "name": i, "owner": owner, "amount": amount, "close_date": close, "status": status,
                        "forecast_category": cat, "stage": stage, "created_at": "2026-07-01"})


def test_calls_accuracy_and_board(ctx_for):
    ctx = ctx_for("forecast-prep")
    eng = load_module(ctx.manifest, "engine")
    st = ctx.store
    # last quarter: Sam called 100k and won 80k; Priya called 50k and won 50k
    _deal(st, "s-won", "Sam Rivera", 80000, "2026-09-25", status="won", cat="closed")
    _deal(st, "p-won", "Priya Shah", 50000, "2026-09-28", status="won", cat="closed")
    eng.submit_call(ctx, "Sam Rivera", 100000, now=LAST_Q)
    eng.submit_call(ctx, "Priya Shah", 50000, now=LAST_Q)
    # this quarter
    _deal(st, "s1", "Sam Rivera", 60000, "2026-12-10")
    _deal(st, "s2", "Sam Rivera", 40000, "2026-12-15", cat="best_case")
    _deal(st, "p1", "Priya Shah", 30000, "2026-12-01")
    _deal(st, "n1", "Lee Park", 25000, "2027-02-01", cat="pipeline", stage="discovery")
    r = eng.submit_call(ctx, "Sam Rivera", 90000, best_case=100000, notes="s1 plus half of s2", now=NOW)
    assert r["period"] == "Q4 2026" and r["call_id"]
    acc = eng.accuracy(ctx, now=NOW)
    assert acc["ratio_by_owner"] == {"Sam Rivera": 0.8, "Priya Shah": 1.0}
    b = eng.board_forecast(ctx, NOW)
    sam = next(x for x in b["reps"] if x["owner"] == "Sam Rivera")
    assert sam["call"] == 90000 and sam["adjusted"] == 72000 and sam["called"]
    assert "Priya Shah" in b["no_call_this_quarter"]
    assert b["range"]["call"] == 72000 + 30000  # Priya falls back to CRM commit, scaled 1.0
    assert b["range"]["low"] <= b["range"]["high"] and b["next_quarter_pipeline"] == 25000
    assert "Board forecast" in eng.format_board(b)


def test_tools_validate(ctx_for):
    t = bind_tools(ctx_for("forecast-prep"))
    assert t["submit_forecast_call"](owner="Sam Rivera", commit=100, best_case=50)["error"]
    assert t["submit_forecast_call"](owner="Sam Rivera", commit=-1)["error"]
    ok = t["submit_forecast_call"](owner="Sam Rivera", commit=0)
    assert ok["call_id"]
    assert len(t["forecast_call_history"](owner="Sam Rivera")["calls"]) == 1
    assert "text" in t["board_forecast"]()
