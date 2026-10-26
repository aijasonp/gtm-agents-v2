import json
from datetime import datetime, timezone

import httpx

from gtm_core import engagement
from gtm_core.agents import load_module
from gtm_core.api import Api
from gtm_core.sources import posthog as ph
from gtm_core.store import Store

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
RULES = {"first_party": {"pricing_paths": ["/pricing"], "high_intent_paths": ["/demo"], "content_paths": ["/resources/"],
                         "signup_events": ["trial_started"], "content_events": ["file_downloaded"],
                         "repeat_visits": {"days": 7, "min_days": 3},
                         "product_qualified": {"events": ["report_built"], "min_events": 3, "days": 7},
                         "group_domain_properties": ["company_domain"], "lookback_days": 7}}


def store():
    st = Store("sqlite:///:memory:")
    st.init()
    st.upsert_account({"id": "litware.example", "name": "Litware", "domain": "litware.example", "industry": "Software",
                       "employees": 900, "country": "US"})
    st.upsert("contacts", {"id": "c1", "account_id": "litware.example", "name": "Avery Chen",
                           "email": "avery@litware.example", "title": "VP Sales"})
    return st


_N = iter(range(10**6))


def ev(event, day, email=None, path=None, **props):
    p = dict(props)
    if path:
        p["$current_url"] = "https://ours.example" + path
    return {"uuid": f"u{next(_N)}", "event": event, "timestamp": f"2026-10-{day:02d}T15:00:00Z", "distinct_id": email or "anon",
            "person": {"properties": {"email": email} if email else {}}, "properties": p}


def test_normalize_handles_the_webhook_destination_shape_and_group_domains():
    body = {"event": {"uuid": "u1", "event": "$pageview", "timestamp": "2026-10-19T10:00:00Z",
                      "properties": {"$current_url": "https://ours.example/Pricing?x=1"}},
            "person": {"properties": {"email": " Avery@Litware.example "}},
            "groups": {"company": {"properties": {"company_domain": "litware.example"}}}}
    n = ph.normalize(body)
    assert n["email"] == "avery@litware.example" and n["path"] == "/pricing" and n["props"]["company_domain"] == "litware.example"
    assert ph._eid(body, n) == ph._eid(body, ph.normalize(body))


def test_resolution_drops_anonymous_and_free_mail_and_uses_group_domain():
    st = store()
    res = ph.record(st, [ev("$pageview", 19, "avery@litware.example", "/pricing"),
                         ev("$pageview", 19, "me@gmail.com", "/pricing"),
                         ev("$pageview", 19, None, "/pricing"),
                         ev("$pageview", 19, None, "/demo", company_domain="www.litware.example"),
                         ev("$pageview", 19, "new.person@litware.example", "/pricing")], RULES)
    assert res["kept"] == 3 and res["unmatched"] == 2 and res["accounts"] == ["litware.example"]
    rows = st.query("SELECT email, contact_id FROM web_events ORDER BY email")
    assert [(r["email"], r["contact_id"]) for r in rows] == [(None, None), ("avery@litware.example", "c1"),
                                                            ("new.person@litware.example", None)]


def test_roll_up_kinds_thresholds_and_window():
    st = store()
    a = "avery@litware.example"
    ph.record(st, [ev("$pageview", 15, a, "/blog"), ev("$pageview", 17, a, "/resources/guide"),
                   ev("$pageview", 19, a, "/pricing"), ev("$pageview", 19, a, "/pricing"),
                   ev("trial_started", 19, a), ev("file_downloaded", 18, a, asset="AI budget guide"),
                   *[ev("report_built", 19, a) for _ in range(3)], ev("$pageview", 1, a, "/pricing")], RULES)
    sigs = {(s["signal_type"], s["observed_at"]): s for s in ph.roll_up(st, RULES, NOW)}
    assert sorted(sigs) == [("content_download", "2026-10-17"), ("content_download", "2026-10-18"),
                            ("pricing_page_visit", "2026-10-19"), ("product_qualified", "2026-10-19"),
                            ("repeat_site_visits", "2026-10-19"), ("trial_signup", "2026-10-19")]
    pricing = sigs[("pricing_page_visit", "2026-10-19")]
    assert pricing["payload"]["count"] == 2 and pricing["payload"]["contact_id"] == "c1"
    assert sigs[("content_download", "2026-10-18")]["payload"]["title"] == "Read or downloaded AI budget guide"
    assert sigs[("repeat_site_visits", "2026-10-19")]["payload"]["count"] == 3  # Oct 15, 17, 19; Oct 1 is outside the window
    two = [ev("report_built", 19, a) for _ in range(2)]
    st2 = store()
    ph.record(st2, two, RULES)
    assert not [s for s in ph.roll_up(st2, RULES, NOW) if s["signal_type"] == "product_qualified"]


def test_hogql_poll_builds_query_and_maps_rows():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"results": [["$pageview", "2026-10-19T10:00:00Z", "https://ours.example/pricing",
                                                      "/pricing", "avery@litware.example", None, None, None, "d1"]]})

    q = ph.PostHogQuery("https://ph.example/", "42", "phx", httpx.Client(transport=httpx.MockTransport(handler)))
    import pytest
    with pytest.raises(ValueError):
        q.events(datetime(2026, 10, 13, tzinfo=timezone.utc), ["$pageview", "x') OR 1=1 --\\"])
    rows = q.events(datetime(2026, 10, 13, tzinfo=timezone.utc), ["$pageview", "trial_started"])
    assert seen["auth"] == "Bearer phx" and seen["body"]["query"]["kind"] == "HogQLQuery"
    assert "event IN ('$pageview', 'trial_started')" in seen["body"]["query"]["query"]
    assert rows[0]["person"]["properties"]["email"] == "avery@litware.example"
    assert ph.normalize(rows[0])["path"] == "/pricing"


def test_poll_job_uses_a_cursor_and_dedupes(ctx_for):
    ctx = ctx_for("signal-sourcing")
    ctx.store.upsert_account({"id": "litware.example", "name": "Litware", "domain": "litware.example",
                              "industry": "Software", "employees": 900, "country": "US"})
    eng = load_module(ctx.manifest, "engine")

    page = ev("$pageview", 19, "x@litware.example", "/pricing")

    class Fake:
        calls = []

        def events(self, since, names, limit=10000):
            self.calls.append(since)
            return [page]

    f = Fake()
    first = eng.poll_posthog(ctx, NOW, f)
    second = eng.poll_posthog(ctx, NOW, f)
    assert first["stored"] and second["stored"] == [] and second["duplicates"] == 1
    assert f.calls[1] > f.calls[0]
    assert eng.poll_posthog(ctx, NOW)["skipped"].startswith("POSTHOG_HOST")


def test_web_events_route_stores_signals_and_runs_triggers(settings):
    settings.agents_dir = "agents"
    st = store()
    did = st.add_draft("icp-outbound", "first_touch", "Hi", status="sent", account_id="litware.example", contact_id="c1",
                       meta={"owner": "Sam Rivera"})
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    engagement.record(st, "avery@litware.example", "sent", (now - timedelta(hours=3)).isoformat(), did, "first_touch")
    engagement.record(st, "avery@litware.example", "open", now.isoformat())
    api = Api(settings, "secret", store=st)
    body = {"event": {"uuid": "w1", "event": "$pageview", "timestamp": now.isoformat(),
                      "properties": {"$current_url": "https://ours.example/pricing"}},
            "person": {"properties": {"email": "avery@litware.example"}}}
    code, out = api.route("POST", "/v1/web-events", {}, body)
    assert code == 201 and out["kept"] == 1 and len(out["stored"]) == 1
    assert out["triggers"] == [{"email": "avery@litware.example", "rule": "opened_then_key_page", "action": "tee_up"}]
    code, out = api.route("POST", "/v1/web-events", {}, body)
    assert code == 200 and out["duplicates"] == 1 and "triggers" not in out


def test_a_second_person_joins_the_days_signal(ctx_for):
    ctx = ctx_for("signal-sourcing")
    ctx.store.upsert_account({"id": "litware.example", "name": "Litware", "domain": "litware.example",
                              "industry": "Software", "employees": 900, "country": "US"})
    for cid, e in (("c1", "ana@litware.example"), ("c2", "bo@litware.example")):
        ctx.store.upsert("contacts", {"id": cid, "account_id": "litware.example", "name": cid, "email": e})
    eng = load_module(ctx.manifest, "engine")
    first = eng.web_events(ctx, [ev("$pageview", 19, "ana@litware.example", "/pricing")], NOW)
    second = eng.web_events(ctx, [ev("$pageview", 19, "bo@litware.example", "/pricing")], NOW)
    assert first["stored"] and second["stored"] == first["stored"]  # same signal, updated, reported again
    p = ctx.store.signals_for("litware.example")[0]["payload"]
    assert [x["contact_id"] for x in p["people"]] == ["c1", "c2"] and p["count"] == 2 and p["contact_id"] is None


def test_a_full_page_resumes_from_the_newest_event(ctx_for):
    ctx = ctx_for("signal-sourcing")
    eng = load_module(ctx.manifest, "engine")

    class Full:
        def events(self, since, names, limit=10000):
            return [ev("$pageview", 15, None, "/x"), ev("$pageview", 16, None, "/x")]

    fp = eng.rules(ctx).setdefault("first_party", {})
    fp["poll_limit"] = 2
    try:
        res = eng.poll_posthog(ctx, NOW, Full())
    finally:
        fp.pop("poll_limit")
    assert res["more"] and ctx.store.get_state("sourcing:posthog_cursor").startswith("2026-10-16T15:00")
