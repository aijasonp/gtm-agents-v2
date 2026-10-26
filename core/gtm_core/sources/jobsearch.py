"""Hiring signals from job search sites, for companies whose roles are not on a public ATS board.

Greenhouse, Lever and Ashby cover many mid-market companies but few large enterprises, which post through
Workday, iCIMS, SuccessFactors and similar. A job search provider fills that gap: it searches aggregators for
the company's open roles and returns them in the same posting shape the hiring tier already scores.

  JobSpySearch   python-jobspy (MIT, pip install python-jobspy). Sites default to indeed, google and
                 zip_recruiter. LinkedIn is off unless listed: scraping it is against LinkedIn's terms.
                 Check each site's terms for your use; these are public listings, fetched without a login.

A posting counts for an account only when its company matches exactly: the normalized company name (legal
suffixes ignored) or the company's URL domain. A near match is dropped, never guessed.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol
from urllib.parse import urlparse

from . import text as tx
from .edgar import norm_name

DEFAULT_SITES = ["indeed", "google", "zip_recruiter"]


class JobSearch(Protocol):
    name: str

    def search(self, acct: dict, max_age_days: int) -> list[dict]:
        """Postings [{title, date, url, location, company, site}] for this account's company."""


def _domain(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url if "//" in url else f"//{url}").hostname or ""
    return host.lower().removeprefix("www.")


def same_company(acct: dict, company: str | None, company_url: str | None = None) -> bool:
    dom = (acct.get("domain") or "").lower().removeprefix("www.")
    if dom and _domain(company_url) and (_domain(company_url) == dom or _domain(company_url).endswith("." + dom)):
        return True
    a, b = norm_name(acct.get("name") or ""), norm_name(company or "")
    return bool(a) and a == b


class JobSpySearch:
    name = "jobspy"

    def __init__(self, sites: list[str] | None = None, results: int = 30, country: str = "usa", scrape=None):
        self.sites = [s for s in (sites or DEFAULT_SITES) if s]
        self.results = int(results)
        self.country = country
        self._scrape = scrape  # injected in tests; otherwise jobspy.scrape_jobs

    @classmethod
    def from_config(cls, cfg: dict) -> "JobSpySearch | None":
        try:
            from jobspy import scrape_jobs
        except ImportError:
            return None
        return cls(cfg.get("sites"), int(cfg.get("results", 30)), str(cfg.get("country", "usa")), scrape_jobs)

    def search(self, acct: dict, max_age_days: int) -> list[dict]:
        name = acct.get("name") or ""
        if not name:
            return []
        df = self._scrape(site_name=self.sites, search_term=f'"{name}"', google_search_term=f"{name} jobs",
                          results_wanted=self.results, hours_old=int(max_age_days) * 24,
                          country_indeed=self.country, verbose=0)
        rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df or [])
        out = []
        for r in rows:
            if not same_company(acct, _s(r.get("company")), _s(r.get("company_url")) or _s(r.get("company_url_direct"))):
                continue
            out.append({"title": _s(r.get("title")), "date": tx.iso_date(r.get("date_posted")),
                        "url": _s(r.get("job_url_direct")) or _s(r.get("job_url")), "location": _s(r.get("location")),
                        "company": _s(r.get("company")), "site": _s(r.get("site"))})
        return [p for p in out if p["title"] and p["url"]]


def _s(v) -> str | None:
    """pandas NaN and None to None, anything else to a stripped string."""
    if v is None:
        return None
    try:
        if v != v:  # NaN
            return None
    except Exception:
        pass
    s = str(v).strip()
    return s or None


def provider(cfg: dict | None) -> JobSearch | None:
    """The configured job search provider (hiring.job_search in config/signals.yaml), or None."""
    cfg = cfg or {}
    if not cfg.get("enabled"):
        return None
    if (cfg.get("provider") or "jobspy") == "jobspy":
        return JobSpySearch.from_config(cfg)
    return None


def today() -> date:
    return date.today()
