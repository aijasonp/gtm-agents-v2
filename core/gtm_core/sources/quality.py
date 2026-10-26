"""Who never gets sourced or dispatched, and what a dispatchable row must contain.

Rules (all from config, defaults below):
  - corporate domain only: no free mail, parked or placeholder domains, no lead-gen or list domains
  - excluded company types by name or industry: investors, staffing, agencies, consultancies, law firms,
    and any vendor or partner categories the customer lists (competitors are never prospected)
  - industry must be a real industry, never a generic placeholder such as "Technology"
  - a signal row must have every required field, a date and a source URL, and a detail that is a
    company-specific fact (not a homepage title, not the company name, not a directory page)
"""
from __future__ import annotations

import re

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "proton.me",
             "protonmail.com", "gmx.com", "mail.com", "yandex.com", "zoho.com"}
DEFAULT_DOMAIN_PATTERNS = [r"leads?\.", r"leads?[a-z]*\.", r"expo\.", r"^lists?\.", r"\d{3,}", r"parked",
                           r"forsale", r"^(mail|email|eml)[a-z0-9]*\.", r"^[a-z0-9-]+\.\d[a-z]+\d*\."]
DEFAULT_EXCLUDED_TYPES = {
    "investor": ["capital", "ventures", "venture partners", "private equity", "asset management", "investments llc",
                 "holdings fund", "partners fund"],
    "staffing": ["staffing", "recruiting", "talent solutions", "recruitment"],
    "agency": ["agency", "marketing group", "digital marketing", "media group"],
    "consultancy": ["consulting", "consultants", "advisors", "advisory group"],
    "law_firm": ["law firm", "llp attorneys", "legal group", "attorneys at law"],
}
PLACEHOLDER_INDUSTRIES = {"technology", "tech", "information technology", "internet", "other", "unknown", "n/a",
                          "business services", "services", ""}
JUNK_DETAIL = ("wikipedia", "whois", "official online store", "official site", "home page", "homepage",
               "domain for sale", "page not found", "linkedin", "crunchbase profile")
REQUIRED = ("domain", "company", "industry", "signal_source", "signal_detail", "signal_url", "signal_date",
            "signal_score", "target_personas")


def clean_domain(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://", "", v).split("/")[0].split("?")[0]
    return v.removeprefix("www.")


def account_rejection(acct: dict, cfg: dict) -> str | None:
    """Why this account must never be sourced or dispatched, or None."""
    dom = clean_domain(acct.get("domain") or acct.get("id") or "")
    if not dom or "." not in dom:
        return "no corporate domain"
    if dom in FREE_MAIL:
        return f"free mail domain ({dom})"
    if dom in {clean_domain(d) for d in cfg.get("suppression", [])}:
        return "on the suppression list"
    for p in cfg.get("domain_patterns", DEFAULT_DOMAIN_PATTERNS):
        if re.search(p, dom):
            return f"domain looks like a list, lead-gen or placeholder site ({dom})"
    tld = dom.rsplit(".", 1)[-1]
    if tld in set(cfg.get("thin_tlds", ["dev", "tech", "ai", "io", "app", "xyz", "me"])) and \
            not (acct.get("employees") or acct.get("cik") or acct.get("ticker")):
        return f"micro-startup risk: .{tld} domain with no headcount or listing"
    name = (acct.get("name") or "").lower()
    industry = (acct.get("industry") or "").lower()
    types = {**DEFAULT_EXCLUDED_TYPES, **(cfg.get("excluded_types") or {})}
    for kind, terms in types.items():
        for t in terms or []:
            t = t.lower()
            if re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", name) or \
                    re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", industry):
                return f"excluded company type: {kind.replace('_', ' ')} ('{t}')"
    min_emp = cfg.get("min_employees")
    if min_emp and acct.get("employees") and int(acct["employees"]) < int(min_emp) and not acct.get("ticker"):
        return f"below {min_emp} employees and not public"
    return None


def industry_ok(industry: str | None) -> bool:
    return (industry or "").strip().lower() not in PLACEHOLDER_INDUSTRIES


def detail_ok(detail: str, company: str) -> bool:
    d = (detail or "").strip().lower()
    if len(d) < 20 or d == (company or "").strip().lower():
        return False
    return not any(j in d for j in JUNK_DETAIL)


def row_rejection(row: dict) -> str | None:
    missing = [k for k in REQUIRED if not row.get(k)]
    if missing:
        return "missing " + ", ".join(missing)
    if not industry_ok(row["industry"]):
        return f"industry is a placeholder ('{row['industry']}'); set the real industry"
    if not detail_ok(row["signal_detail"], row["company"]):
        return "signal detail is not a company-specific fact"
    if not str(row["signal_url"]).startswith(("http://", "https://")):
        return "signal URL is not a link"
    if row["signal_score"] not in ("High", "Medium"):
        return "signal score must be High or Medium"
    return None
