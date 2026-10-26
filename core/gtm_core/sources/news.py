"""Initiative, appointment and funding signals from company newsrooms and trusted press.

Sources, in order:
  1. The account's own newsroom feed (`newsroom_rss` on the account: RSS or Atom URL, or a list).
  2. An optional news API provider for accounts with no feed (Context.dev when CONTEXT_DEV_API_KEY
     is set). Provider results only count when they come from the company's own domain or from a
     domain in `trusted_press`.

Never discovers companies from search snippets, and never counts an item without a date and a URL.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import urlparse

from . import text as tx
from .http import SourceClient
from .model import Finding

JUNK = ("wikipedia", "whois", "official online store", "domain for sale", "page not found")
APPOINT = re.compile(r"\b(appoints?|appointed|names?|named|hires?|hired|welcomes?|joins?|promotes?|promoted|"
                     r"elevates?|taps?)\b", re.I)
FUNDING = re.compile(r"\b(raises?|raised|closes?|secures?|secured)\b.{0,60}\b(funding|series [a-h]|round|financing)\b"
                     r"|\bseries [a-h]\b.{0,40}\b(round|funding)\b", re.I)


def parse_feed(raw: str) -> list[dict]:
    """RSS 2.0 or Atom to [{title, summary, url, date}]."""
    try:
        root = ET.fromstring(raw.encode() if isinstance(raw, str) else raw)
    except ET.ParseError:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for it in root.iter("item"):
        out.append({"title": (it.findtext("title") or "").strip(),
                    "summary": tx.html_to_text(it.findtext("description") or ""),
                    "url": (it.findtext("link") or "").strip(),
                    "date": tx.iso_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"))})
    for e in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = e.find("a:link[@rel='alternate']", ns)
        if link is None:
            link = e.find("a:link", ns)
        out.append({"title": (e.findtext("a:title", default="", namespaces=ns) or "").strip(),
                    "summary": tx.html_to_text(e.findtext("a:summary", default="", namespaces=ns)
                                               or e.findtext("a:content", default="", namespaces=ns) or ""),
                    "url": link.get("href", "") if link is not None else "",
                    "date": tx.iso_date(e.findtext("a:published", default="", namespaces=ns)
                                        or e.findtext("a:updated", default="", namespaces=ns))})
    return out


class ContextDevNews:
    """Optional provider. POST /news/search by company domain; recency is filtered locally."""
    URL = "https://api.context.dev/v1/news/search"

    def __init__(self, key: str, http=None):
        import httpx
        self.key = key
        self.http = http or httpx.Client(timeout=30)

    @classmethod
    def from_env(cls):
        k = os.environ.get("CONTEXT_DEV_API_KEY")
        return cls(k) if k else None

    def search(self, domain: str, limit: int = 20) -> list[dict]:
        r = self.http.post(self.URL, headers={"Authorization": f"Bearer {self.key}"},
                           json={"searchBy": {"type": "entity", "entity": {"type": "domain", "domain": domain}},
                                 "limit": limit})
        if r.status_code >= 400:
            return []
        items = r.json()
        items = items.get("results") or items.get("data") or items.get("articles") or [] if isinstance(items, dict) else items
        return [{"title": i.get("title", ""), "summary": i.get("summary") or i.get("description") or "",
                 "url": i.get("url") or i.get("link") or "",
                 "date": tx.iso_date(i.get("published_at") or i.get("publishedAt") or i.get("date"))} for i in items]


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def initiative_phrase(title: str, company: str, verbs: list[str]) -> str | None:
    """"Northwind launches AI sales assistant program with $12M" -> "your AI sales assistant program"."""
    t = re.sub(re.escape(company or ""), "", title or "", flags=re.I).strip(" :-,")
    t = re.sub(r"^(inc\.?|corp\.?|co\.?)\s+", "", t, flags=re.I)
    vp = tx.term_re(verbs)
    m = vp.search(t) if vp else None
    if m and m.start() <= 25:
        t = t[m.end():].strip()
    t = re.split(r"\s+(?:with|to boost|amid|after)\s+|,|;|:", t)[0].strip()
    t = re.sub(r"^(a|an|the|its|new)\s+", "", t, flags=re.I)
    return f"your {t}" if 3 <= len(t) <= 55 else None


def classify(item: dict, acct: dict, rules: dict) -> tuple[str, str, list[str]] | None:
    """(source, signal_type, matched) for a news item, or None. Initiative needs a commitment term and a
    topic term in the same item; appointments need a buyer or C-suite role."""
    t = f"{item.get('title', '')}. {item.get('summary', '')}"
    low = t.lower()
    if any(j in low for j in JUNK) or low.strip(". ") == (acct.get("name") or "").lower():
        return None
    buyer = tx.hits(tx.term_re(rules.get("buyer_roles", [])), t)
    csuite = tx.hits(tx.term_re(rules.get("csuite_roles", [])), t)
    if APPOINT.search(item.get("title", "")) and (buyer or csuite):
        return "exec_change", ("new_exec_in_buyer_function" if buyer else "new_exec_c_suite"), buyer or csuite
    if FUNDING.search(t):
        return "funding", "funding_round", ["funding"]
    commit = tx.hits(tx.term_re(rules.get("initiative_terms", [])), t)
    topic = tx.hits(tx.term_re(rules.get("initiative_topics", [])), t)
    if commit and topic:
        return "initiative", "strategic_initiative", topic
    return None


def news_signals(client: SourceClient, acct: dict, rules: dict, today: date, provider=None) -> tuple[list[Finding], dict]:
    feeds = acct.get("newsroom_rss") or []
    feeds = [feeds] if isinstance(feeds, str) else list(feeds)
    items, used = [], []
    for f in feeds:
        r = client.get(f)
        if r.ok:
            got = parse_feed(r.text)
            for g in got:
                g["trusted"] = True
            items += got
            used.append(f)
    dom = (acct.get("domain") or acct.get("id") or "").lower()
    if not items and provider is not None and dom:
        trusted = {d.lower() for d in rules.get("trusted_press", [])}
        for g in provider.search(dom):
            h = _host(g["url"])
            g["trusted"] = h == dom or h.endswith("." + dom) or h in trusted
            items.append(g)
        used.append("provider")
    windows = {"initiative": int(rules.get("initiative_days", 180)), "exec_change": int(rules.get("exec_days", 180)),
               "funding": int(rules.get("funding_days", 180))}
    best: dict[str, Finding] = {}
    for it in items:
        if not (it.get("url") and it.get("date") and it.get("trusted")):
            continue
        c = classify(it, acct, rules)
        if not c:
            continue
        source, st, matched = c
        if it["date"] < (today - timedelta(days=windows[source])).isoformat() or it["date"] > today.isoformat():
            continue
        amt = tx.amount(f"{it['title']} {it.get('summary', '')}") if source in ("initiative", "funding") else None
        conf = "High" if (source == "initiative" and amt) or source == "funding" else \
            ("High" if source == "exec_change" and st == "new_exec_in_buyer_function" else "Medium")
        f = Finding(account_id=acct["id"], source=source, signal_type=st, detail=tx.truncate(it["title"]),
                    url=it["url"], observed_at=it["date"], confidence=conf, topics=matched, amount=amt,
                    meta={"summary": tx.truncate(it.get("summary", ""), 300),
                          "topic": (initiative_phrase(it["title"], acct.get("name", ""), rules.get("initiative_terms", []))
                                    if source == "initiative" else None) or (matched[0] if matched else ""),
                          "role": matched[0] if source == "exec_change" else None, "feed": _host(it["url"])})
        if source not in best or f.observed_at > best[source].observed_at:
            best[source] = f
    return list(best.values()), {"feeds": used, "items": len(items)}
