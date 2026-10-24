from datetime import datetime, timezone

from gtm_core.scoring import IcpProfile, decay, icp_fit, load_taxonomy, score_signals, signal_id

TAX = load_taxonomy("agents/signal-scout/skill/references/signal-taxonomy.yaml")
NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def test_decay_half_life():
    assert abs(decay("2026-09-23", 30, NOW) - 0.5) < 0.01
    assert decay("2026-10-23", 30, NOW) == 1.0


def test_signal_id_dedups_url_variants():
    a = signal_id("acme", "funding_round", "https://www.acme.com/news/?utm=x", "2026-10-01T10:00:00")
    b = signal_id("acme", "funding_round", "acme.com/news", "2026-10-01")
    assert a == b


def test_repeats_get_diminishing_credit():
    one = score_signals([{"signal_type": "pricing_page_visit", "observed_at": "2026-10-23"}], TAX, now=NOW)
    three = score_signals([{"signal_type": "pricing_page_visit", "observed_at": "2026-10-23"}] * 3, TAX, now=NOW)
    assert three.raw < one.raw * 2


def test_stacking_rule_requires_categories():
    s = score_signals([{"signal_type": "funding_round", "observed_at": "2026-10-20"},
                       {"signal_type": "hiring_buyer_team", "observed_at": "2026-10-20"}], TAX, now=NOW)
    assert s.rule == "money_plus_hiring"


def test_unknown_signal_ignored():
    assert score_signals([{"signal_type": "made_up", "observed_at": "2026-10-20"}], TAX, now=NOW).score == 0


def test_icp_excluded_industry_is_zero():
    fit, _ = icp_fit({"industry": "Government agency", "employees": 500}, IcpProfile(exclude_industries=["government"]))
    assert fit == 0


def test_icp_neutral_without_data():
    fit, _ = icp_fit({}, IcpProfile())
    assert fit == 50.0
