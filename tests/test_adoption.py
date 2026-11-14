from datetime import datetime, timezone

from gtm_core import adoption
from gtm_core.api import Api
from gtm_core.store import Store

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
OWNERS = [{"name": "Sam Rivera", "email": "sam@beacon.example", "slack_id": "U1"},
          {"name": "Lee Park", "email": "lee@beacon.example"}]


def _store():
    st = Store("sqlite:///:memory:")
    st.init()
    return st


def test_roster_matches_and_ignores_system():
    r = adoption.Roster(OWNERS)
    assert r.rep("slack:U1") == "Sam Rivera"
    assert r.rep("api:lee@beacon.example") == "Lee Park"
    assert r.rep("LEE PARK") == "Lee Park"
    assert r.rep("autonomy:auto") is None and r.rep("operator") is None and r.rep("slack:U999") is None


def test_record_never_raises_and_skips_system():
    st = _store()
    adoption.record(st, "autonomy:auto", "x")
    adoption.record(st, "", "x")
    adoption.record(st, "slack:U1", "slack_ask", at="2026-11-10T10:00:00+00:00")
    assert len(st.query("SELECT * FROM rep_activity")) == 1
    adoption.record(None, "slack:U1", "slack_ask")  # broken store: swallowed


def test_report_no_deals_no_lift():
    st = _store()
    for d in (1, 2, 3):
        adoption.record(st, "slack:U1", "slack_ask", at=f"2026-11-0{d}T10:00:00+00:00")
    r = adoption.report(st, OWNERS, [], NOW)
    assert r["active"] == 1 and r["adoption"] == 0.5 and r["retention"] is None
    assert r["win_rate_lift_pts"] is None and r["small_sample"]
    assert "1 of 2 reps (50%)" in adoption.format_report(r) and "Not active: Lee Park" in adoption.format_report(r)


def test_api_usage_and_activity(settings):
    settings.agents_dir = "agents"
    st = _store()
    st.upsert_account({"id": "acme.example", "name": "Acme", "domain": "acme.example", "customer": True, "seats": 10})
    api = Api(settings, "secret", store=st)
    code, out = api.route("POST", "/v1/usage", {}, [{"account": "acme.example", "metric": "mau", "value": 9,
                                                     "observed_at": "2026-11-01"},
                                                    {"account": "acme.example", "metric": "vibes", "value": 1}])
    assert code == 200 and out["stored"] == 1 and len(out["errors"]) == 1
    code, out = api.route("POST", "/v1/activity", {}, {"actor": "api:lee@beacon.example", "action": "extension_prequal"})
    assert code == 200 and out["recorded"] == 1
    assert api.route("POST", "/v1/activity", {}, {"actor": "x"})[0] == 400
