"""Hiring signals from public job board APIs (no login, no scraping of job sites).

  greenhouse  https://boards-api.greenhouse.io/v1/boards/{token}/jobs
  lever       https://api.lever.co/v0/postings/{token}?mode=json
  ashby       https://api.ashbyhq.com/posting-api/job-board/{token}

An account can name its board (`ats: {greenhouse: acme}`). Otherwise the board token is guessed
from the domain and company name, and the provider that answers is remembered on the account.
Only roles that match the buyer-team patterns and were posted inside the window count.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import text as tx
from .http import SourceClient
from .model import Finding

PROVIDERS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
    "lever": "https://api.lever.co/v0/postings/{t}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{t}",
}


def guesses(acct: dict) -> list[str]:
    dom = (acct.get("domain") or acct.get("id") or "").lower().removeprefix("www.")
    root = dom.split(".")[0] if dom else ""
    name = re.sub(r"[^a-z0-9]+", "", (acct.get("name") or "").lower())
    out = []
    for g in (root, name, root.replace("-", "")):
        if g and g not in out:
            out.append(g)
    return out


def _postings(provider: str, data) -> list[dict]:
    """Normalize each provider to [{title, date, url, location}]."""
    if provider == "greenhouse":
        return [{"title": j.get("title"), "date": tx.iso_date(j.get("first_published") or j.get("updated_at")),
                 "url": j.get("absolute_url"), "location": (j.get("location") or {}).get("name")}
                for j in (data or {}).get("jobs", [])]
    if provider == "lever":
        return [{"title": j.get("text"), "date": tx.iso_date(j.get("createdAt")), "url": j.get("hostedUrl"),
                 "location": (j.get("categories") or {}).get("location")} for j in (data or [])]
    if provider == "ashby":
        return [{"title": j.get("title"), "date": tx.iso_date(j.get("publishedAt") or j.get("publishedDate")),
                 "url": j.get("jobUrl") or j.get("applyUrl"), "location": j.get("location")}
                for j in (data or {}).get("jobs", [])]
    return []


def fetch_board(client: SourceClient, acct: dict) -> tuple[str | None, str | None, list[dict]]:
    """(provider, token, postings). Tries the account's named board first, then guesses."""
    named = acct.get("ats") or {}
    tries = [(p, t) for p, t in named.items() if p in PROVIDERS and t]
    if not tries:
        tries = [(p, g) for g in guesses(acct) for p in PROVIDERS]
    for p, t in tries:
        r = client.get(PROVIDERS[p].format(t=t), params={"mode": "json"} if p == "lever" else None)
        if not r.ok:
            continue
        try:
            posts = _postings(p, r.json())
        except ValueError:
            continue
        if posts or named:
            return p, t, posts
    return None, None, []


def hiring_signal(client: SourceClient, acct: dict, buyer_roles: list[str], today: date,
                  max_age_days: int = 30) -> tuple[Finding | None, dict]:
    """One hiring finding per account, with every matching role kept in meta (never in copy)."""
    provider, token, posts = fetch_board(client, acct)
    info = {"provider": provider, "token": token, "postings": len(posts)}
    if not provider:
        return None, {**info, "why": "no public job board found (set ats on the account)"}
    pat = tx.term_re(buyer_roles)
    cutoff = (today - timedelta(days=max_age_days)).isoformat()
    match = [p for p in posts if p.get("title") and p.get("date") and p["date"] >= cutoff and tx.hits(pat, p["title"])]
    if not match:
        return None, {**info, "why": f"no buyer-team roles posted since {cutoff}"}
    match.sort(key=lambda p: p["date"], reverse=True)
    newest = match[0]
    conf = "High" if len(match) >= 3 else "Medium"
    return Finding(account_id=acct["id"], source="hiring", signal_type="hiring_buyer_team",
                   detail=f"Hiring for {newest['title']}" + (f" and {len(match) - 1} more buyer-team roles" if len(match) > 1 else ""),
                   url=newest["url"] or "", observed_at=newest["date"], confidence=conf,
                   topics=sorted({h for p in match for h in tx.hits(pat, p["title"])}),
                   meta={"provider": provider, "token": token, "roles": [p["title"] for p in match[:10]],
                         "count": len(match)}), info
