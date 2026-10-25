"""One do-not-contact check for every agent and every send.

A person is suppressed when any of these is true:
  * their contact record has do_not_contact, unsubscribed, opted_out or email_invalid set
  * their email or domain is on the runtime suppression list (state key `suppression`)
  * their email or domain is in an agent's do-not-contact YAML (passed in by the caller)

Pickers call `is_suppressed` before drafting; the sequence and dialer executors call it again at
run time, so an opt-out that arrives after a draft was approved still stops the send.
`suppress()` records an opt-out and rejects pending sends to that person.
"""
from __future__ import annotations

import json

from .store import Store, now_iso

FLAGS = ("do_not_contact", "unsubscribed", "opted_out", "email_invalid")
SEND_ACTIONS = ("sequence_enroll", "dialer_enqueue")


def _norm(email: str | None) -> str:
    return (email or "").strip().lower()


def _list(store: Store) -> dict:
    d = store.get_state("suppression", {}) or {}
    return {"emails": d.get("emails", {}), "domains": d.get("domains", {})}


def reason(store: Store, email: str | None = None, contact: dict | None = None,
           extra_emails: set | None = None, extra_domains: set | None = None) -> str | None:
    """Why this person must not be contacted, or None when clear."""
    email = _norm(email or (contact or {}).get("email"))
    c = contact
    if c is None and email:
        c = store.contact_by_email(email)
    for f in FLAGS:
        if c and c.get(f) not in (None, False, "", "false", "0", 0):
            return f"contact flagged {f}"
    if not email:
        return None
    dom = email.split("@")[-1]
    lst = _list(store)
    if email in lst["emails"]:
        return f"on the suppression list ({lst['emails'][email].get('reason', 'opt-out')})"
    if dom in lst["domains"]:
        return f"domain on the suppression list ({lst['domains'][dom].get('reason', '')})"
    if extra_emails and email in {_norm(x) for x in extra_emails}:
        return "on the do-not-contact list"
    if extra_domains and dom in {_norm(x) for x in extra_domains}:
        return "domain on the do-not-contact list"
    return None


def is_suppressed(store: Store, email: str | None = None, contact: dict | None = None, **kw) -> bool:
    return reason(store, email, contact, **kw) is not None


def suppress(store: Store, email: str, why: str = "opt-out", by: str = "system") -> dict:
    """Record an opt-out everywhere and reject pending sends to this person. Takes effect at once."""
    email = _norm(email)
    if not email:
        return {"suppressed": False}
    d = store.get_state("suppression", {}) or {}
    d.setdefault("emails", {})[email] = {"reason": why, "at": now_iso(), "by": by}
    d.setdefault("domains", d.get("domains", {}))
    store.set_state("suppression", d)
    c = store.contact_by_email(email)
    if c:
        store.upsert("contacts", {"id": c["id"], "do_not_contact": True, "do_not_contact_reason": why})
    rejected = []
    for row in store.query("SELECT id, action, payload FROM approvals WHERE status IN ('pending','approved') "
                           "AND action IN (?, ?)", SEND_ACTIONS):
        p = json.loads(row["payload"] or "{}")
        if _norm((p.get("contact") or {}).get("email")) == email:
            n = store.execute("UPDATE approvals SET status='rejected', decided_at=?, decided_by=? "
                              "WHERE id=? AND status IN ('pending','approved')", (now_iso(), f"suppression:{why}", row["id"]))
            if n:
                store.execute("UPDATE drafts SET status='rejected' WHERE approval_id=?", (row["id"],))
                rejected.append(row["id"])
    return {"suppressed": True, "email": email, "rejected_approvals": rejected}
