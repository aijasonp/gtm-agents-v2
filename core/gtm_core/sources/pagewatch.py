"""Signals from page changes: pricing, careers, trust, leadership, newsroom and script-tag watches.

changedetection.io (self-hosted, Apache-2.0) watches the pages; this module turns each change into dated,
sourced findings with fixed rules. No model call. The watch's tag names the page kind (pricing, careers,
trust, leadership, news, tech); without a tag the URL path decides (`page_changes.page_kinds`).

Two ways in:
  push  a changedetection.io notification to POST /v1/page-changes. Use a JSON notification body, or the
        plain-text template in `NOTIFICATION_TEMPLATE` (works with any Apprise URL, e.g. json:// or posts://).
  poll  `ChangeDetection.changes()` reads watches changed since the last run through the changedetection.io
        API (CHANGEDETECTION_URL, CHANGEDETECTION_API_KEY) and diffs the two newest snapshots itself.

What counts (only lines the change added, unless stated):
  careers     a buyer role from hiring.buyer_roles                 -> hiring_buyer_team (Medium)
  leadership  a buyer or C-suite role from exec_change              -> new_exec_in_buyer_function / new_exec_c_suite
  trust       a certification term (SOC 2, ISO 27001, ...)          -> audit_or_certification (High when certified)
  news        commitment + topic (as in the news tier), launch, or  -> strategic_initiative / new_product_launch /
              partnership terms                                        partnership_announced
  tech        a configured complementary or competitor script domain -> adopted_complementary_tool /
              added; one removed                                       competitor_installed / removed_tool
  pricing     any change                                            -> pricing_change (timing only)
"""
from __future__ import annotations

import difflib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import text as tx
from .model import Finding

NOTIFICATION_TEMPLATE = """watch_url: {{watch_url}}
watch_uuid: {{watch_uuid}}
watch_title: {{watch_title}}
watch_tag: {{watch_tag}}
---added---
{{diff_added}}
---removed---
{{diff_removed}}"""

DEFAULT_KINDS = {"pricing": ["/pricing", "/plans"], "careers": ["/careers", "/jobs", "/join-us"],
                 "trust": ["/trust", "/security", "/compliance"],
                 "leadership": ["/leadership", "/team", "/management", "/about/leadership"],
                 "news": ["/press", "/news", "/newsroom", "/blog"]}
CERTIFIED = re.compile(r"\b(certified|achieved|completed|attained|awarded|now compliant|is compliant)\b", re.I)
DOMAIN = re.compile(r"(?:https?:)?//([a-z0-9.-]+\.[a-z]{2,})", re.I)


def host(url: str | None) -> str:
    if not url:
        return ""
    return (urlparse(url if "//" in url else f"//{url}").hostname or "").lower().removeprefix("www.")


# ---------- parse a notification ----------
_MARK = re.compile(r"^\s*(?:\((?:added|changed|removed|into|from)\)|[+-](?=\s))\s*", re.I)


def _lines(v) -> list[str]:
    """Diff text to clean lines: drops diff markers such as "(added)" or a leading "+ ", and blank lines."""
    if isinstance(v, list):
        v = "\n".join(str(x) for x in v)
    out = []
    for ln in str(v or "").splitlines():
        ln = " ".join(_MARK.sub("", ln).split())
        if ln:
            out.append(ln)
    return out


def parse_notification(body) -> dict:
    """A changedetection.io notification as {url, uuid, title, tags, added, removed, changed_at}.
    Accepts JSON (flat, or Apprise's {"title", "message"} wrapper) or the plain-text template."""
    if isinstance(body, dict) and isinstance(body.get("message"), str) and not body.get("watch_url"):
        msg = body["message"]
        try:
            inner = json.loads(msg)
            if isinstance(inner, dict):
                body = inner
        except json.JSONDecodeError:
            body = msg
    if isinstance(body, str):
        head, _, rest = body.partition("---added---")
        added, _, removed = rest.partition("---removed---")
        kv = {}
        for ln in head.splitlines():
            k, sep, v = ln.partition(":")
            if sep:
                kv[k.strip().lower()] = v.strip()
        body = {**kv, "diff_added": added, "diff_removed": removed}
    if not isinstance(body, dict):
        raise ValueError("page change body must be JSON or the notification template text")
    url = body.get("watch_url") or body.get("url")
    if not url:
        raise ValueError("page change needs watch_url")
    tags = body.get("watch_tag") or body.get("tags") or body.get("tag") or ""
    tags = [t.strip().lower() for t in (tags if isinstance(tags, list) else re.split(r"[,;]", str(tags))) if t.strip()]
    return {"url": url, "uuid": body.get("watch_uuid") or body.get("uuid"), "title": body.get("watch_title") or "",
            "tags": tags, "added": _lines(body.get("diff_added") or body.get("added")),
            "removed": _lines(body.get("diff_removed") or body.get("removed")),
            "changed_at": tx.iso_date(body.get("changed_at") or body.get("timestamp")) or
            datetime.now(timezone.utc).date().isoformat()}


# ---------- what kind of page ----------
def page_kind(change: dict, kinds: dict | None = None) -> str | None:
    kinds = {**DEFAULT_KINDS, **(kinds or {})}
    for t in change.get("tags", []):
        k = t.removeprefix("gtm:")
        if k in kinds or k in ("tech", "pricing", "careers", "trust", "leadership", "news"):
            return k
    path = (urlparse(change["url"]).path or "/").lower().rstrip("/") or "/"
    for k, prefixes in kinds.items():
        if any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes or []):
            return k
    return None


def account_for(store, change: dict):
    """The account by an `account:<domain>` tag, then by the page's domain (subdomains included)."""
    for t in change.get("tags", []):
        if t.startswith("account:"):
            a = store.account_by_domain(t.split(":", 1)[1])
            if a:
                return a
    h = host(change["url"])
    parts = h.split(".")
    for i in range(len(parts) - 1):
        a = store.account_by_domain(".".join(parts[i:]))
        if a:
            return a
    return None


# ---------- classify ----------
def _f(acct, source, st, detail, url, day, conf="Medium", topics=None, meta=None) -> Finding:
    return Finding(account_id=acct["id"], source=source, signal_type=st, detail=tx.truncate(detail, 300), url=url,
                   observed_at=day, confidence=conf, topics=topics or [], meta={"page": "page_change", **(meta or {})})


def classify(change: dict, acct: dict, rules: dict) -> list[Finding]:
    """Findings for one page change. `rules` is config/signals.yaml (page_changes plus the tiers it borrows)."""
    pc = rules.get("page_changes") or {}
    kind = page_kind(change, pc.get("page_kinds"))
    url, day, added, removed = change["url"], change["changed_at"], change["added"], change["removed"]
    meta = {"kind": kind, "watch": change.get("uuid"), "page_title": change.get("title")}
    out: list[Finding] = []
    if kind == "careers":
        pat = tx.term_re((rules.get("hiring") or {}).get("buyer_roles") or [])
        roles = [ln for ln in added if tx.hits(pat, ln)]
        if roles:
            out.append(_f(acct, "page_change", "hiring_buyer_team", f"Careers page added {roles[0]}"
                          + (f" and {len(roles) - 1} more buyer-team roles" if len(roles) > 1 else ""), url, day,
                          "High" if len(roles) >= 3 else "Medium", sorted({h for r in roles for h in tx.hits(pat, r)}),
                          {**meta, "roles": roles[:10]}))
    elif kind == "leadership":
        xc = rules.get("exec_change") or {}
        bp, cp = tx.term_re(xc.get("buyer_roles") or []), tx.term_re(xc.get("csuite_roles") or [])
        for ln in added:
            if tx.hits(bp, ln):
                out.append(_f(acct, "page_change", "new_exec_in_buyer_function", f"Leadership page added: {ln}", url,
                              day, "Medium", tx.hits(bp, ln), meta))
                break
        else:
            for ln in added:
                if tx.hits(cp, ln):
                    out.append(_f(acct, "page_change", "new_exec_c_suite", f"Leadership page added: {ln}", url, day,
                                  "Medium", tx.hits(cp, ln), meta))
                    break
    elif kind == "trust":
        pat = tx.term_re(pc.get("certifications") or ["soc 2", "iso 27001", "hipaa", "fedramp", "pci dss"])
        for ln in added:
            got = tx.hits(pat, ln)
            if got:
                out.append(_f(acct, "page_change", "audit_or_certification", ln, url, day,
                              "High" if CERTIFIED.search(ln) else "Medium", got, meta))
                break
    elif kind == "news":
        nc = rules.get("news") or {}
        commit, topic = tx.term_re(nc.get("initiative_terms") or []), tx.term_re(nc.get("initiative_topics") or [])
        launch = tx.term_re(pc.get("launch_terms") or ["introducing", "now available", "launches", "launched"])
        partner = tx.term_re(pc.get("partnership_terms") or ["partnership", "partners with", "integration with"])
        for ln in added:
            if tx.hits(commit, ln) and tx.hits(topic, ln):
                out.append(_f(acct, "page_change", "strategic_initiative", ln, url, day, "Medium", tx.hits(topic, ln),
                              {**meta, "topic": ln}))
                break
            if tx.hits(launch, ln):
                out.append(_f(acct, "page_change", "new_product_launch", ln, url, day, "Medium", [], meta))
                break
            if tx.hits(partner, ln):
                out.append(_f(acct, "page_change", "partnership_announced", ln, url, day, "Medium", [], meta))
                break
    elif kind == "tech":
        comp = {d.lower() for d in pc.get("complementary_tools") or []}
        rival = {d.lower() for d in pc.get("competitor_tools") or []}

        def doms(lines):
            found = set()
            for ln in lines:
                for m in DOMAIN.finditer(ln):
                    h = m.group(1).lower().removeprefix("www.")
                    for d in comp | rival:
                        if h == d or h.endswith("." + d):
                            found.add(d)
            return found
        for d in sorted(doms(added)):
            st = "competitor_installed" if d in rival else "adopted_complementary_tool"
            out.append(_f(acct, "page_change", st, f"Site now loads {d}", url, day, "Medium", [d], {**meta, "tool": d}))
        for d in sorted(doms(removed) - doms(added)):
            out.append(_f(acct, "page_change", "removed_tool", f"Site no longer loads {d}", url, day, "Medium", [d],
                          {**meta, "tool": d}))
    elif kind == "pricing" and (added or removed):
        out.append(_f(acct, "page_change", "pricing_change", f"Pricing page changed ({len(added)} lines added, "
                      f"{len(removed)} removed)", url, day, "Medium", [], meta))
    return out


# ---------- poll the changedetection.io API ----------
class ChangeDetection:
    """Minimal client for the changedetection.io REST API (x-api-key). Verify the paths against your version:
    GET /api/v1/watch, GET /api/v1/watch/{uuid}/history, GET /api/v1/watch/{uuid}/history/{timestamp}."""

    def __init__(self, base_url: str, api_key: str, client=None):
        import httpx
        self.base = base_url.rstrip("/")
        self.http = client or httpx.Client(timeout=30)
        self.headers = {"x-api-key": api_key}

    @classmethod
    def from_env(cls) -> "ChangeDetection | None":
        url, key = os.environ.get("CHANGEDETECTION_URL"), os.environ.get("CHANGEDETECTION_API_KEY")
        return cls(url, key) if url and key else None

    def _get(self, path: str):
        r = self.http.get(f"{self.base}{path}", headers=self.headers)
        r.raise_for_status()
        return r.json() if "json" in r.headers.get("content-type", "") else r.text

    def changes(self, since_epoch: int) -> list[dict]:
        """Watches changed after `since_epoch`, each diffed between its two newest snapshots."""
        out = []
        watches = self._get("/api/v1/watch") or {}
        for uuid, w in watches.items():
            if int(w.get("last_changed") or 0) <= since_epoch:
                continue
            hist = self._get(f"/api/v1/watch/{uuid}/history") or {}
            stamps = sorted(hist, key=int)
            if len(stamps) < 2:
                continue
            new, old = (self._get(f"/api/v1/watch/{uuid}/history/{t}") for t in (stamps[-1], stamps[-2]))
            diff = list(difflib.ndiff(str(old).splitlines(), str(new).splitlines()))
            tags = w.get("tags") or w.get("tag") or []
            out.append({"url": w.get("url"), "uuid": uuid, "title": w.get("title") or "",
                        "tags": [str(t).lower() for t in (tags if isinstance(tags, list) else [tags]) if t],
                        "added": _lines([d[2:] for d in diff if d.startswith("+ ")]),
                        "removed": _lines([d[2:] for d in diff if d.startswith("- ")]),
                        "changed_at": datetime.fromtimestamp(int(stamps[-1]), timezone.utc).date().isoformat(),
                        "_epoch": int(stamps[-1])})
        return out


def watch_plan(accounts: list[dict], kinds: dict | None = None) -> list[dict]:
    """URLs to watch for each account (one row per page), tagged for import into changedetection.io."""
    kinds = {**DEFAULT_KINDS, **(kinds or {})}
    rows = []
    for a in accounts:
        dom = (a.get("domain") or "").removeprefix("www.")
        if not dom:
            continue
        for k in ("pricing", "careers", "trust", "leadership", "news"):
            first = (kinds.get(k) or [None])[0]
            if first:
                rows.append({"account": a["id"], "url": f"https://{dom}{first}", "tags": f"gtm:{k},account:{dom}"})
        rows.append({"account": a["id"], "url": f"https://{dom}/", "tags": f"gtm:tech,account:{dom}",
                     "note": "use a CSS/XPath filter on script src attributes"})
    return rows
