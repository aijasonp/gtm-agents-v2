"""First-party signals from your website and product, through PostHog (MIT core, self-hosted or cloud).

Two ways in:
  push  a PostHog webhook destination posting events to POST /v1/web-events (one event or a list)
  poll  `PostHogQuery.events(since)` runs a HogQL query through the query API
        (POST {host}/api/projects/{project}/query with a personal API key)

Events are resolved and stored first (`record`, deduplicated), because a webhook sends one event at a time and
repeat visits need history. `roll_up` then reads the stored window. Each event is resolved to an account by the identified person's email domain, or a group property holding the
company domain (`first_party.group_domain_properties`). Anonymous and free-mail traffic is dropped, never
guessed. Stored events roll up per account and day into signals with fixed rules:

  pricing_page_visit     a pageview on a pricing path
  high_intent_page_visit a pageview on a demo, contact-sales or security path
  content_download       a content event, or a pageview on a content path
  trial_signup           a signup or trial event (sayable: the person chose to sign up)
  repeat_site_visits     the account visited on at least `min_days` distinct days in `days`
  product_qualified      at least `min_events` key product events in `days`

Signals carry the people behind them (contact ids when known) so Daily Book and the triggers can act on the person.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse

from . import text as tx

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "proton.me",
             "protonmail.com", "live.com", "msn.com", "me.com", "gmx.com", "yandex.com"}


def _path(url: str | None) -> str:
    if not url:
        return ""
    return (urlparse(url).path or "/").lower()


def normalize(e: dict) -> dict:
    """One PostHog event (webhook or query row) as {event, at, url, path, email, props, distinct_id}."""
    if isinstance(e.get("event"), dict):  # webhook destination default body: {event: {...}, person, groups}
        e = {**e["event"], "person": e.get("person") or e["event"].get("person"), "groups": e.get("groups")}
    props = dict(e.get("properties") or {})
    for g in (e.get("groups") or {}).values():  # group properties (company domain) count as event properties
        for k, v in ((g or {}).get("properties") or {}).items():
            props.setdefault(k, v)
    person = (e.get("person") or {}).get("properties") or {}
    email = (person.get("email") or props.get("email") or props.get("$email") or e.get("email") or "").strip().lower()
    url = props.get("$current_url") or e.get("url") or ""
    return {"event": e.get("event") or "", "at": e.get("timestamp") or e.get("at") or "", "url": url,
            "path": props.get("$pathname") or _path(url), "email": email, "props": props,
            "distinct_id": e.get("distinct_id") or ""}


def resolve(store, ev: dict, group_props: list[str]):
    """(account, contact) for an event, or (None, None). Email domain first, then a company-domain group property."""
    contact = store.contact_by_email(ev["email"]) if ev["email"] else None
    if contact and contact.get("account_id"):
        a = store.account(contact["account_id"])
        if a:
            return a, contact
    dom = ev["email"].split("@", 1)[1] if "@" in ev["email"] else ""
    if dom and dom not in FREE_MAIL:
        a = store.account_by_domain(dom)
        if a:
            return a, contact
    for k in group_props:
        v = str(ev["props"].get(k) or "").lower().removeprefix("www.")
        if v and "." in v and v not in FREE_MAIL:
            a = store.account_by_domain(v)
            if a:
                return a, None
    return None, None


def _starts(path: str, prefixes: list[str]) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) or path.startswith(p.rstrip("/") + "/") for p in prefixes)


SCHEMA = """CREATE TABLE IF NOT EXISTS web_events (
  id TEXT PRIMARY KEY, account_id TEXT, contact_id TEXT, email TEXT, event TEXT, path TEXT, day TEXT, at TEXT,
  asset TEXT, created_at TEXT)"""


def ensure(store) -> None:
    if not getattr(store, "_web_schema", False):
        store.execute(SCHEMA)
        store.execute("CREATE INDEX IF NOT EXISTS web_events_acct ON web_events (account_id, day)")
        store._web_schema = True


def _eid(raw: dict, ev: dict) -> str:
    import hashlib
    inner = raw.get("event") if isinstance(raw.get("event"), dict) else raw
    key = inner.get("uuid") or "|".join([ev["distinct_id"], ev["email"], ev["event"], ev["at"], ev["path"]])
    return hashlib.sha1(str(key).encode()).hexdigest()[:20]


def record(store, events: list[dict], rules: dict) -> dict:
    """Resolve and store raw events. Unmatched (anonymous, free mail, unknown company) are counted, not kept."""
    from ..store import now_iso
    ensure(store)
    fp = rules.get("first_party") or {}
    groups = fp.get("group_domain_properties") or ["company_domain", "domain"]
    kept = dupes = dropped = 0
    accounts = set()
    for raw in events:
        ev = normalize(raw)
        day = tx.iso_date(ev["at"])
        acct, contact = resolve(store, ev, groups) if day else (None, None)
        if not acct:
            dropped += 1
            continue
        eid = _eid(raw, ev)
        if store.one("SELECT id FROM web_events WHERE id=?", (eid,)):
            dupes += 1
            continue
        store.execute("INSERT INTO web_events (id, account_id, contact_id, email, event, path, day, at, asset, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (eid, acct["id"], (contact or {}).get("id"), ev["email"] or None, ev["event"], ev["path"], day,
                       ev["at"], ev["props"].get("asset"), now_iso()))
        kept += 1
        accounts.add(acct["id"])
    return {"kept": kept, "duplicates": dupes, "unmatched": dropped, "accounts": sorted(accounts)}


def classify(e: dict, fp: dict) -> str | None:
    """The per-event signal kind, or None (product events and plain pageviews only count toward thresholds)."""
    if e["event"] in (fp.get("signup_events") or []):
        return "trial_signup"
    if e["event"] in (fp.get("content_events") or []):
        return "content_download"
    if e["event"] == "$pageview":
        path = (e.get("path") or "").lower()
        if _starts(path, fp.get("pricing_paths") or ["/pricing"]):
            return "pricing_page_visit"
        if _starts(path, fp.get("high_intent_paths") or []):
            return "high_intent_page_visit"
        if _starts(path, fp.get("content_paths") or []):
            return "content_download"
    return None


TITLES = {"pricing_page_visit": "Visited the pricing page", "high_intent_page_visit": "Visited {path}",
          "content_download": "Read or downloaded {asset}", "trial_signup": "Signed up for a trial"}


def roll_up(store, rules: dict, now: datetime, accounts: list[str] | None = None) -> list[dict]:
    """Signals (store rows, not yet saved) from stored events in the lookback window: one per account, kind and day,
    plus repeat visits and product-qualified thresholds."""
    ensure(store)
    fp = rules.get("first_party") or {}
    today = now.date()
    since = (today - timedelta(days=int(fp.get("lookback_days", 7)))).isoformat()
    rows = store.query("SELECT * FROM web_events WHERE day>=? ORDER BY day, at, id", (since,))
    per: dict = defaultdict(list)
    for r in rows:
        if accounts is None or r["account_id"] in accounts:
            per[r["account_id"]].append(r)
    rv = fp.get("repeat_visits") or {"days": 7, "min_days": 3}
    pq = fp.get("product_qualified") or {}
    rv_since = (today - timedelta(days=int(rv.get("days", 7)))).isoformat()
    pq_since = (today - timedelta(days=int(pq.get("days", 7)))).isoformat()
    out = []
    for aid in sorted(per):
        evs = per[aid]
        groups: dict = defaultdict(list)
        for e in evs:
            k = classify(e, fp)
            if k:
                groups[(k, e["day"])].append(e)
        for (kind, day), hits in sorted(groups.items()):
            last = hits[-1]
            title = TITLES[kind].format(path=last["path"] or "a key page",
                                        asset=last.get("asset") or last["path"] or "content")
            out.append(_sig(aid, kind, day, title, len(hits), _people(hits), {"asset": last.get("asset"),
                                                                             "paths": sorted({h["path"] for h in hits})}))
        days = sorted({e["day"] for e in evs if e["event"] == "$pageview" and e["day"] >= rv_since})
        if len(days) >= int(rv.get("min_days", 3)):
            seen = [e for e in evs if e["event"] == "$pageview" and e["day"] >= rv_since]
            out.append(_sig(aid, "repeat_site_visits", days[-1], f"Visited on {len(days)} days in {rv.get('days', 7)}",
                            len(days), _people(seen)))
        names = set(pq.get("events") or [])
        prod = [e for e in evs if e["event"] in names and e["day"] >= pq_since]
        if names and len(prod) >= int(pq.get("min_events", 20)):
            out.append(_sig(aid, "product_qualified", max(e["day"] for e in prod),
                            f"{len(prod)} key product events in {pq.get('days', 7)} days", len(prod), _people(prod)))
    return out


def _people(hits: list[dict]) -> list[dict]:
    seen: dict = {}
    for h in hits:
        if h.get("email") and h["email"] not in seen:
            seen[h["email"]] = h.get("contact_id")
    return [{"email": e, "contact_id": c} for e, c in sorted(seen.items())]


def _sig(aid, kind, day, title, count, people, extra=None) -> dict:
    from ..scoring import signal_id
    url = f"posthog://{aid}/{kind}/{day}"
    return {"id": signal_id(aid, kind, url, day), "account_id": aid, "signal_type": kind, "source": "first_party:posthog",
            "url": url, "observed_at": day, "strength": min(1.5, 0.7 + 0.1 * count),
            "payload": {"title": title, "count": count, "people": people[:10],
                        "contact_id": people[0]["contact_id"] if len(people) == 1 else None, "first_party": True,
                        **(extra or {})}}


class PostHogQuery:
    """HogQL over the PostHog query API. Needs a personal API key with query read access."""

    def __init__(self, host: str, project: str, key: str, client=None):
        import httpx
        self.url = f"{host.rstrip('/')}/api/projects/{project}/query/"
        self.key = key
        self.http = client or httpx.Client(timeout=60)

    @classmethod
    def from_env(cls) -> "PostHogQuery | None":
        h, p, k = (os.environ.get(x) for x in ("POSTHOG_HOST", "POSTHOG_PROJECT_ID", "POSTHOG_PERSONAL_API_KEY"))
        return cls(h, p, k) if h and p and k else None

    def events(self, since: datetime, names: list[str], limit: int = 10000) -> list[dict]:
        names_sql = ", ".join("'" + n.replace("'", "") + "'" for n in names)
        q = ("SELECT event, timestamp, properties.$current_url, properties.$pathname, person.properties.email, "
             "properties.company_domain, properties.domain, properties.asset, distinct_id FROM events "
             f"WHERE timestamp >= toDateTime('{since.strftime('%Y-%m-%d %H:%M:%S')}') AND event IN ({names_sql}) "
             f"ORDER BY timestamp LIMIT {int(limit)}")
        r = self.http.post(self.url, json={"query": {"kind": "HogQLQuery", "query": q}},
                           headers={"Authorization": f"Bearer {self.key}"})
        r.raise_for_status()
        out = []
        for row in r.json().get("results") or []:
            ev, ts, url, path, email, cdom, dom, asset, did = (list(row) + [None] * 9)[:9]
            out.append({"event": ev, "timestamp": str(ts), "distinct_id": did, "person": {"properties": {"email": email}},
                        "properties": {"$current_url": url, "$pathname": path, "company_domain": cdom, "domain": dom,
                                       "asset": asset}})
        return out
