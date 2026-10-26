"""Signal sourcing: polite client, EDGAR parsing, job boards, feeds, gates and the agent tools."""
import json
from datetime import date, datetime, timezone

import httpx

from gtm_core.agents import load_module
from gtm_core.mcp_server import bind_tools
from gtm_core.sources import edgar, jobs, news, quality, text
from gtm_core.sources.fixtures import fixture_client
from gtm_core.sources.http import SourceClient

FIX = "agents/signal-sourcing/sample/fixtures"
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def test_client_retries_honors_retry_after_and_identifies_itself():
    calls, sleeps = [], []

    def h(req):
        calls.append(req.headers["user-agent"])
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "2"})
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")
    c = SourceClient("Beacon research@beacon.example", per_host_rps=0, client=httpx.Client(transport=httpx.MockTransport(h)),
                     sleep=sleeps.append)
    r = c.get("https://data.sec.gov/x")
    assert r.ok and r.text == "ok" and calls == ["Beacon research@beacon.example"] * 3 and sleeps[0] == 2.0
    assert c.get("https://data.sec.gov/x").ok and len(calls) == 3  # cached
    dead = SourceClient(per_host_rps=0, retries=1, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))),
                        sleep=lambda s: None)
    r = dead.get("https://blocked.example/")
    assert not r.ok and r.error == "HTTP 403" and dead.log[-1]["status"] == 403


def test_sections_pick_body_not_table_of_contents():
    body = text.html_to_text("<p>Item 1A. Risk Factors</p><p>Item 7. Management's Discussion and Analysis</p>"
                             "<p>Item 1A. Risk Factors</p><p>" + "Our sales productivity depends on hiring. " * 20 + "</p>"
                             "<p>Item 2. Properties</p><p>Offices.</p>")
    secs = dict(edgar.sections(body, "10-K"))
    assert "sales productivity" in secs["risk_factors"] and "Properties" not in secs["risk_factors"]


def test_cik_match_is_exact_never_fuzzy():
    sec = edgar.Edgar(fixture_client(FIX))
    assert sec.cik_for({"name": "Northwind Logistics"}) == ("0009990001", "name")
    assert sec.cik_for({"name": "Northwind"})[0] is None              # first word alone never matches
    assert sec.cik_for({"name": "x", "ticker": "adtm"}) == ("0009990003", "ticker")
    assert sec.cik_for({"name": "x", "cik": "9990002"}) == ("0009990002", "cik")


def test_amounts_dates_and_atom():
    assert text.amount("a $2.5 billion program and a $40 fee") == "$2.5B"
    assert text.amount("costs $40") is None
    assert text.iso_date("Tue, 06 Oct 2026 13:00:00 GMT") == "2026-10-06" and text.iso_date(1790000000000) == "2026-09-21"
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Acme names Jo Park Chief Revenue Officer</title>'
            '<link rel="alternate" href="https://acme.example/n/1"/><published>2026-10-01T10:00:00Z</published></entry></feed>')
    [it] = news.parse_feed(atom)
    assert it["url"] == "https://acme.example/n/1" and it["date"] == "2026-10-01"
    c = news.classify(it, {"name": "Acme"}, {"buyer_roles": ["chief revenue officer"]})
    assert c[1] == "new_exec_in_buyer_function"
    assert news.classify({"title": "Acme exploring options", "summary": ""}, {"name": "Acme"},
                         {"initiative_terms": ["launches"], "initiative_topics": ["ai"]}) is None


def test_provider_news_counts_only_trusted_domains():
    class P:
        def search(self, domain, limit=20):
            return [{"title": "Acme launches AI sales program", "summary": "", "url": "https://randomblog.example/x", "date": "2026-10-01"},
                    {"title": "Acme launches AI sales program", "summary": "", "url": "https://www.reuters.com/acme", "date": "2026-10-02"}]
    got, info = news.news_signals(fixture_client(FIX), {"id": "acme.example", "domain": "acme.example", "name": "Acme"},
                                  {"initiative_terms": ["launches"], "initiative_topics": ["ai"], "trusted_press": ["reuters.com"]},
                                  date(2026, 10, 20), P())
    assert [f.url for f in got] == ["https://www.reuters.com/acme"]


def test_job_board_guess_and_quality_gates():
    assert jobs.guesses({"domain": "www.north-wind.example", "name": "North Wind"}) == ["north-wind", "northwind"]
    assert quality.account_rejection({"domain": "gmail.com", "name": "x"}, {}) .startswith("free mail")
    assert "competitor" in quality.account_rejection({"domain": "acmeintel.example", "name": "Acme Intel"},
                                                     {"excluded_types": {"competitor": ["acme intel"]}})
    assert quality.account_rejection({"domain": "3m.com", "name": "3M"}, {}) is None
    row = {k: "x" * 25 for k in quality.REQUIRED}
    row.update(industry="Technology", signal_url="https://a.example", signal_score="High", company="Acme",
               signal_detail="Our 10-K names sales productivity as a 2027 priority")
    assert "placeholder" in quality.row_rejection(row)
    row["industry"] = "Banking"
    assert quality.row_rejection(row) is None
    row["signal_detail"] = "Acme Official Online Store and more"
    assert "company-specific" in quality.row_rejection(row)


def test_tools_end_to_end(ctx_for):
    ctx = ctx_for("signal-sourcing")
    ctx.sources_client = fixture_client(FIX)
    t = bind_tools(ctx)
    assert t["add_company"](name="HCP Leads", domain="hcpleads.example")["error"]
    a = t["add_company"](name="Northwind Logistics", domain="https://www.northwind.example/", ticker="nwlx",
                         industry="Logistics", employees=600, newsroom_rss="https://northwind.example/newsroom/rss.xml")
    assert a["added"] and a["account"] == "northwind.example"
    ctx.store.upsert_account({**ctx.store.account("northwind.example"), "country": "US", "revenue": 120000000})
    eng = load_module(ctx.manifest, "engine")
    r = eng.scan_account(ctx, ctx.store.account("northwind.example"), NOW)
    assert len(r["stored"]) == 4 and ctx.store.account("northwind.example")["ats"] == {"greenhouse": "northwind"}
    sig = [s for s in ctx.store.signals_for("northwind.example") if s["signal_type"] == "filing_priority_mention"][0]
    assert sig["source"] == "sourcing:filing" and sig["strength"] == 1.0 and sig["payload"]["filing"] == "10-Q"
    assert eng.due_accounts(ctx, NOW) == []  # just scanned
    rep = t["sourcing_report"](days=36500)
    assert rep["by_tier"]["filing"]["signals"] == 1
    out = load_module(ctx.manifest, "jobs").daily_scan(ctx, NOW)
    assert out["dispatch"] == 1 and "Signal Sourcing" in ctx.slack.sent[-1]["text"]
    # Signal Scout picks the sourced signals up in its own score
    sc = ctx_for("signal-scout")
    sc.store = ctx.store
    s = load_module(sc.manifest, "engine").score_one(sc, ctx.store.account("northwind.example"), NOW)
    assert "filings" in s.signals.categories and s.tier in ("A", "B")


def test_weekly_discovery_posts_candidates(ctx_for):
    ctx = ctx_for("signal-sourcing")
    ctx.sources_client = fixture_client(FIX)
    out = load_module(ctx.manifest, "jobs").weekly_discovery(ctx, NOW)
    assert out["candidates"] == 2 and "Litware" in ctx.slack.sent[-1]["text"]  # no accounts yet: Northwind is new too
