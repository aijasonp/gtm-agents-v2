from datetime import datetime, timezone

from gtm_core import engagement
from gtm_core.agents import load_module

NOW = datetime(2026, 10, 23, 7, 30, tzinfo=timezone.utc)


def test_daily_report_counts_funnel(ctx_for):
    ctx = ctx_for("revenue-pulse")
    st = ctx.store
    st.upsert("leads", {"id": "l1", "email": "a@x.example", "source": "webinar", "received_at": "2026-10-22T15:00:00+00:00"})
    st.upsert("leads", {"id": "l2", "email": "b@x.example", "source": "form", "received_at": "2026-10-22T16:00:00+00:00"})
    st.upsert("leads", {"id": "l0", "email": "c@x.example", "source": "form", "received_at": "2026-10-20T16:00:00+00:00"})
    for run, tier, at in (("r1", "B", "2026-10-21T06:00:00+00:00"), ("r2", "A", "2026-10-23T06:00:00+00:00")):
        st.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
                  (run, "signal-scout", "nw.example", 80, tier, at))
    engagement.record(st, "a@nw.example", "sent", "2026-10-22T09:00:00Z")
    engagement.record(st, "a@nw.example", "open", "2026-10-22T09:00:02Z")       # machine (2 s after send)
    engagement.record(st, "a@nw.example", "open", "2026-10-22T11:00:00Z")
    engagement.record(st, "a@nw.example", "interested", "2026-10-22T12:00:00Z")
    st.upsert("deals", {"id": "d1", "name": "NW", "status": "won", "amount": 50000, "close_date": "2026-10-22",
                        "created_at": "2026-09-01"})
    st.upsert("deals", {"id": "d2", "name": "New", "status": "open", "amount": 20000, "created_at": "2026-10-22T10:00:00",
                        "stage": "discovery"})
    r = load_module(ctx.manifest, "engine").daily(ctx, NOW)
    assert r["leads"] == {"count": 2, "by_source": {"form": 1, "webinar": 1}}
    assert r["new_tier_a"] == ["nw.example"]
    o = r["outbound"]
    assert (o["sent"], o["human_opens"], o["machine_opens"], o["replies"], o["positive_replies"]) == (1, 1, 1, 1, 1)
    assert r["deals"]["won"]["amount"] == 50000 and r["deals"]["created"]["count"] == 1
    out = load_module(ctx.manifest, "jobs").daily_gtm_report(ctx, NOW)
    assert "Daily GTM report" in ctx.slack.sent[-1]["text"] and out["meetings_held"] == 0
