from datetime import datetime, timezone

import pytest

from gtm_core import engagement, rules
from gtm_core.api import Api
from gtm_core.store import Store
from gtm_core.worktime import add_business_days, add_business_hours, business_days_between


def table(rows, **kw):
    return rules.parse_table("t", {"rules": rows, **kw})


def test_cells_canonical_and_matching():
    assert rules.canonical("post_meeting") == '"post_meeting"'
    assert rules.canonical(3) == "3" and rules.canonical(True) == "true" and rules.canonical("-") == ""
    assert rules.canonical(">=3") == ">= 3" and rules.canonical(["a", "b"]) == '"a", "b"'
    m = lambda c, v: rules.cell_matches(rules.canonical(c), v, "builtin")
    assert m(">= 3", 3) and not m(">= 3", 2) and not m(">= 3", "3") and not m(">= 3", None)
    assert m("[1..3]", 1) and m("[1..3]", 3) and not m("(1..3)", 3) and m("(1..3]", 3)
    assert m("a, b", "b") and not m("a, b", "c") and not m("a", "A")
    assert m("true", True) and not m("true", 1) and m("null", None) and m("!= lost", "won")
    assert m("", None) and m("-", 7)


def test_first_collect_default_and_errors():
    t = table([{"id": "hot", "when": {"opens": ">= 3"}, "then": {"action": "tee_up"}},
               {"id": "warm", "when": {"opens": ">= 1"}, "then": {"action": "watch"}}], default={"action": "none"})
    assert rules.evaluate(t, {"opens": 4}, "builtin").output == {"action": "tee_up", "rule": "hot"}
    assert rules.evaluate(t, {"opens": 0}, "builtin").output["rule"] == "default"
    c = table(t and [{"id": "a", "when": {"x": ">= 1"}, "then": {"k": 1}}, {"id": "b", "when": {"x": ">= 2"}, "then": {"k": 2}}],
              hit_policy="collect")
    assert rules.evaluate(c, {"x": 5}, "builtin").matched == ["a", "b"]
    for bad in ({"rules": []}, {"rules": [{"when": {"x": "[1..3"}, "then": {}}]}, {"hit_policy": "any", "rules": [{"then": {}}]},
                {"rules": [{"id": "a", "then": {}}, {"id": "a", "then": {}}]}):
        with pytest.raises(rules.RuleError):
            rules.parse_table("bad", bad)


@pytest.mark.skipif(not rules.zen_available(), reason="zen-engine not installed")
def test_builtin_matches_zen_on_every_cell_form():
    cells = [">= 3", "< 3", "> 2.5", "== 3", "!= 3", "[1..3]", "(1..3)", "[1..3)", "true", "false", "null", "3",
             "post_meeting", "a, b", "!= lost", "1, 2, 5", "", "!= null", ">= 3, == 0"]
    vals = [None, 0, 1, 2, 2.5, 3, 4, -1, True, False, "a", "b", "post_meeting", "lost", "3"]
    for c in cells:
        cc = rules.canonical(c)
        for v in vals:
            assert rules.cell_matches(cc, v, "builtin") == rules.cell_matches(cc, v, "zen"), (c, v)


def test_worktime():
    tue = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)  # 10:00 in Chicago
    assert add_business_hours(tue, 4, "America/Chicago").isoformat() == "2026-10-20T19:00:00+00:00"
    assert add_business_hours(tue, 8, "America/Chicago").isoformat() == "2026-10-21T15:00:00+00:00"
    assert add_business_hours(datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc), 1, "America/Chicago").isoformat() \
        == "2026-10-23T22:00:00+00:00"  # 16:00 local Friday: fits before close
    fri = datetime(2026, 10, 23, 23, 0, tzinfo=timezone.utc)  # 18:00 local Friday, after close
    assert add_business_hours(fri, 1, "America/Chicago").isoformat() == "2026-10-26T15:00:00+00:00"
    assert add_business_days(fri, 1, "America/Chicago").date().isoformat() == "2026-10-26"
    assert business_days_between(tue, fri) == 3


def test_email_event_intake_runs_triggers_at_once(settings):
    settings.agents_dir = "agents"
    st = Store("sqlite:///:memory:"); st.init()
    st.upsert_account({"id": "contoso.example", "name": "Contoso", "domain": "contoso.example", "industry": "Software",
                       "employees": 400, "country": "US"})
    st.upsert("contacts", {"id": "c1", "account_id": "contoso.example", "name": "Ben Ito", "email": "ben@contoso.example",
                           "title": "VP Sales"})
    did = st.add_draft("icp-outbound", "first_touch", "Hi", status="sent", account_id="contoso.example", contact_id="c1",
                       meta={"owner": "Sam Rivera"})
    engagement.record(st, "ben@contoso.example", "sent", "2026-10-19T14:00:00+00:00", did, "first_touch")
    api = Api(settings, "secret", store=st)
    code, out = api.route("POST", "/v1/email-events", {}, [{"email": "ben@contoso.example", "event": "click"}])
    assert code == 201 and out["triggers"] == [{"email": "ben@contoso.example", "rule": "clicked", "action": "tee_up"}]
    code, out = api.route("POST", "/v1/email-events", {}, [{"email": "ben@contoso.example", "event": "open"}])
    assert out["triggers"][0]["rule"] == "already_teed_up"
