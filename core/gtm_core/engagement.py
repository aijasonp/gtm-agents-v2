"""Email engagement tracking: sends, opens, clicks, replies, bounces, tied back to the draft,
the angle and the value prop that produced them.

Events arrive from the sequencer (POST /v1/email-events, or the Lemlist / Smartlead webhook
mapped to the same shape). Each event is matched to the draft that was sent:
by `draft_id` when the sequencer echoes it back, else by the latest sent draft to that email.

Machine opens (privacy proxies and link scanners) inflate open rates. An open flagged
`machine: true`, or arriving within `machine_open_seconds` of the send, is stored but left out
of every rate. Rates use human opens only.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from .pipeline import parse_dt
from .store import now_iso

EVENTS = {"sent", "delivered", "open", "click", "reply", "reply_positive", "reply_negative", "bounce", "unsubscribe"}
ALIASES = {"opened": "open", "email_opened": "open", "clicked": "click", "email_clicked": "click",
           "replied": "reply", "email_replied": "reply", "bounced": "bounce", "email_bounced": "bounce",
           "emailsent": "sent", "email_sent": "sent", "unsubscribed": "unsubscribe", "interested": "reply_positive",
           "not_interested": "reply_negative"}
MACHINE_OPEN_SECONDS = 5


def normalize_event(e: str) -> str | None:
    k = (e or "").strip().lower().replace(" ", "_")
    k = ALIASES.get(k, k)
    return k if k in EVENTS else None


def _match_draft(store, email: str, draft_id, step: str | None) -> dict | None:
    if draft_id:
        rows = store.query("SELECT * FROM drafts WHERE id=?", (int(draft_id),))
        if rows:
            return rows[0]
    # The most recent step actually sent to this person, when the sequencer reported sends.
    sent = store.one("SELECT draft_id FROM email_events WHERE email=? AND event='sent' AND draft_id IS NOT NULL"
                     + (" AND step=?" if step else "") + " ORDER BY occurred_at DESC, id DESC LIMIT 1",
                     (email, step) if step else (email,))
    if sent:
        rows = store.query("SELECT * FROM drafts WHERE id=?", (sent["draft_id"],))
        if rows:
            return rows[0]
    c = store.contact_by_email(email)
    if not c:
        return None
    # Otherwise the requested step, or the first touch: opens and replies mostly land on step one.
    rows = store.query("SELECT * FROM drafts WHERE contact_id=? AND status IN ('sent','queued') AND kind=? "
                       "ORDER BY id DESC LIMIT 1", (c["id"], step or "first_touch"))
    return rows[0] if rows else None


def record(store, email: str, event: str, occurred_at: str | None = None, draft_id=None, step: str | None = None,
           machine: bool = False, source: str = "sequencer", meta: dict | None = None,
           machine_open_seconds: int = MACHINE_OPEN_SECONDS) -> dict:
    """Store one event. Returns {added, duplicate, event_id, ...}; raises ValueError on bad input."""
    ev = normalize_event(event)
    email = (email or "").strip().lower()
    if not ev:
        raise ValueError(f"unknown event {event!r}; valid: {sorted(EVENTS)}")
    if "@" not in email:
        raise ValueError("email required")
    at = parse_dt(occurred_at) if occurred_at else datetime.now(timezone.utc)
    if at is None:
        raise ValueError(f"unreadable occurred_at {occurred_at!r}")
    at_s = at.replace(microsecond=0).isoformat()
    d = _match_draft(store, email, draft_id, step)
    dmeta = json.loads(d["meta"] or "{}") if d else {}
    m = {**dmeta, **(meta or {})}
    step = step or (d["kind"] if d else None)
    if store.one("SELECT id FROM email_events WHERE email=? AND event=? AND occurred_at=?", (email, ev, at_s)):
        return {"added": False, "duplicate": True}
    if ev == "open" and not machine:
        sent = store.one("SELECT occurred_at FROM email_events WHERE email=? AND event='sent' AND COALESCE(step,'')=? "
                         "ORDER BY occurred_at DESC LIMIT 1", (email, step or ""))
        if sent:
            s = parse_dt(sent["occurred_at"])
            if s and 0 <= (at - s).total_seconds() <= machine_open_seconds:
                machine = True
    eid = store.insert(
        "INSERT INTO email_events (email, contact_id, account_id, draft_id, step, angle, value_prop, event, machine, "
        "occurred_at, source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (email, d["contact_id"] if d else None, d["account_id"] if d else m.get("account_id"), d["id"] if d else None,
         step, m.get("angle_key") or m.get("angle"), m.get("value_prop"), ev, int(bool(machine)), at_s, source,
         now_iso()))
    return {"added": True, "duplicate": False, "event_id": eid, "event": ev, "machine": bool(machine),
            "matched_draft": d["id"] if d else None}


def threads(store, since_iso: str | None = None) -> list[dict]:
    """One row per (email, first step thread): sent?, human-opened?, replied?, positive?, plus angle and value prop."""
    sql = "SELECT * FROM email_events" + (" WHERE occurred_at>=?" if since_iso else "") + " ORDER BY occurred_at, id"
    rows = store.query(sql, (since_iso,) if since_iso else ())
    by: dict[str, dict] = {}
    for r in rows:
        t = by.setdefault(r["email"], {"email": r["email"], "account_id": None, "contact_id": None, "angle": None,
                                       "value_prop": None, "sent": False, "opened": False, "clicked": False,
                                       "replied": False, "positive": False, "bounced": False})
        for k in ("account_id", "contact_id", "angle", "value_prop"):
            t[k] = t[k] or r.get(k)
        e = r["event"]
        if e == "sent":
            t["sent"] = True
        elif e == "open" and not r["machine"]:
            t["opened"] = True
        elif e == "click":
            t["clicked"] = True
        elif e in ("reply", "reply_negative"):
            t["replied"] = True
        elif e == "reply_positive":
            t["replied"] = t["positive"] = True
        elif e == "bounce":
            t["bounced"] = True
    out = []
    for t in by.values():
        if t["replied"] or t["clicked"]:
            t["opened"] = True  # a reply or click proves a human open even when the pixel was blocked
        if t["sent"] and not t["bounced"]:
            out.append(t)
    return out


def rates(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"sends": 0, "open_rate": None, "reply_rate": None, "positive_rate": None}
    return {"sends": n, "open_rate": round(sum(r["opened"] for r in rows) / n, 3),
            "reply_rate": round(sum(r["replied"] for r in rows) / n, 3),
            "positive_rate": round(sum(r["positive"] for r in rows) / n, 3)}


def outcome(t: dict, w: dict | None = None) -> float:
    w = w or {"open": 0.4, "reply": 0.6}
    return w.get("open", 0.4) * t["opened"] + w.get("reply", 0.6) * t["replied"]


def breakdown(store, key: str, since_iso: str | None = None) -> dict[str, dict]:
    """Rates grouped by `angle` or `value_prop`."""
    groups: dict[str, list] = {}
    for t in threads(store, since_iso):
        groups.setdefault(t.get(key) or "unknown", []).append(t)
    return {k: rates(v) for k, v in sorted(groups.items())}


def pick(candidates: list[str], stats: dict[str, dict], prior: dict[str, float] | None = None,
         explore: float = 0.15, w: dict | None = None) -> tuple[str | None, dict]:
    """Choose among candidates by smoothed engagement plus a small, deterministic exploration bonus.

    mean = (wins + 1) / (sends + 2) where wins = open_weight x opens + reply_weight x replies;
    bonus = explore x sqrt(ln(total + 1) / (sends + 1)); prior adds to the mean (judged pain, persona default).
    Ties keep the candidates' given order, so with no data the first candidate wins."""
    if not candidates:
        return None, {}
    w = w or {"open": 0.4, "reply": 0.6}
    total = sum((stats.get(c) or {}).get("sends", 0) for c in candidates)
    scored = {}
    for i, c in enumerate(candidates):
        s = stats.get(c) or {}
        n = s.get("sends", 0)
        wins = n * (w["open"] * (s.get("open_rate") or 0) + w["reply"] * (s.get("reply_rate") or 0))
        mean = (wins + 1) / (n + 2)
        bonus = explore * math.sqrt(math.log(total + 1) / (n + 1))
        scored[c] = round(mean + bonus + (prior or {}).get(c, 0.0) - i * 1e-6, 6)
    best = max(candidates, key=lambda c: scored[c])
    return best, scored


def since_days(days: int, now: datetime | None = None) -> str:
    return ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
