from datetime import date

from gtm_core.sources import jobs as jb
from gtm_core.sources.jobsearch import JobSpySearch, provider, same_company


class NoBoards:
    """A source client where no ATS board answers."""
    log: list = []

    def get(self, url, params=None):
        return type("R", (), {"ok": False, "status": 404})()


ACCT = {"id": "contoso.example", "name": "Contoso Corporation", "domain": "contoso.example"}
ROWS = [
    {"site": "indeed", "title": "VP of Sales, Enterprise", "company": "Contoso Corp", "date_posted": "2026-10-12",
     "job_url": "https://jobs.example/1"},
    {"site": "google", "title": "Director of Revenue Operations", "company": "Contoso", "company_url": "https://www.contoso.example",
     "date_posted": "2026-10-15", "job_url": "https://jobs.example/2", "job_url_direct": "https://contoso.example/careers/2"},
    {"site": "indeed", "title": "Head of Sales", "company": "Contoso Labs", "date_posted": "2026-10-14",
     "job_url": "https://jobs.example/3"},                                       # a different company: dropped
    {"site": "indeed", "title": "Revenue Operations Analyst", "company": "Contoso Corporation",
     "date_posted": "2026-08-01", "job_url": "https://jobs.example/4"},          # outside the window
    {"site": "zip_recruiter", "title": "Software Engineer", "company": "Contoso Corp", "date_posted": "2026-10-16",
     "job_url": "https://jobs.example/5"},                                       # not a buyer role
]


def fake_scrape(calls):
    def scrape(**kw):
        calls.append(kw)
        return ROWS
    return scrape


def test_company_match_is_exact_or_domain():
    assert same_company(ACCT, "Contoso Corp") and same_company(ACCT, "CONTOSO, INC.")
    assert same_company(ACCT, "Something else", "https://careers.contoso.example/jobs")
    assert not same_company(ACCT, "Contoso Labs") and not same_company(ACCT, None)


def test_jobspy_fills_hiring_when_no_ats_board():
    calls = []
    search = JobSpySearch(results=20, scrape=fake_scrape(calls))
    f, info = jb.hiring_signal(NoBoards(), ACCT, ["vp of sales", "revenue operations", "head of sales"],
                               date(2026, 10, 20), 30, search)
    assert calls[0]["site_name"] == ["indeed", "google", "zip_recruiter"] and calls[0]["hours_old"] == 720
    assert "linkedin" not in calls[0]["site_name"]
    assert f.signal_type == "hiring_buyer_team" and f.meta["provider"] == "jobspy"
    assert f.meta["roles"] == ["Director of Revenue Operations", "VP of Sales, Enterprise"]
    assert f.url == "https://contoso.example/careers/2"  # the company's own posting link wins
    assert f.meta["sites"] == ["google", "indeed"] and info["search"]["postings"] == 4  # same company; window and role filter after


def test_search_failure_never_blocks_and_off_by_default():
    def boom(**kw):
        raise RuntimeError("blocked")
    f, info = jb.hiring_signal(NoBoards(), ACCT, ["vp of sales"], date(2026, 10, 20), 30, JobSpySearch(scrape=boom))
    assert f is None and "blocked" in info["search_error"]
    assert provider({}) is None and provider({"enabled": False}) is None


def test_dataframe_rows_with_nan_are_read():
    import pytest
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame(ROWS)
    rows = JobSpySearch(scrape=lambda **kw: df).search(ACCT, 30)
    assert {r["title"] for r in rows} == {"VP of Sales, Enterprise", "Director of Revenue Operations",
                                          "Revenue Operations Analyst", "Software Engineer"}
    assert all(r["url"] for r in rows)
