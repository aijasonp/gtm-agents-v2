"""Held sequence steps: release an outbound sequence one approved email at a time.

With `sequence_release: per_step` in config/approvals.yaml, an approved sequence_enroll sends only its
first step. The later steps are held here with a due date. When a held step falls due, Follow-Through checks
the person is still fair game (no reply, no opt-out, not with an AE) and queues that one email as a
`sequence_step` approval for its owner. With `sequence_release: all` (the default) nothing is held.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .store import Store, now_iso
from .worktime import add_business_days

SCHEMA = """CREATE TABLE IF NOT EXISTS held_steps (
  id TEXT PRIMARY KEY, enroll_approval INTEGER, email TEXT, contact TEXT, step_index INTEGER, subject TEXT, body TEXT,
  draft_id INTEGER, owner TEXT, due_at TEXT, status TEXT, approval_id INTEGER, reason TEXT, meta TEXT, created_at TEXT,
  updated_at TEXT)"""
HELD, QUEUED, SENT, CANCELLED = "held", "queued", "sent", "cancelled"


def ensure(store: Store) -> None:
    if not getattr(store, "_held_schema", False):
        store.execute(SCHEMA)
        store._held_schema = True


def hold(store: Store, enroll_approval: int | None, contact: dict, steps: list[dict], draft_ids: list, owner: str | None,
         gap_days: int, tz: str = "UTC", meta: dict | None = None, now: datetime | None = None) -> list[str]:
    """Hold steps 2..n with due dates `gap_days` business days apart, starting from now."""
    ensure(store)
    now = now or datetime.now(timezone.utc)
    out = []
    due = now
    for i, s in enumerate(steps[1:], start=1):
        due = add_business_days(due, gap_days, tz)
        hid = f"{enroll_approval or 'x'}:{contact['email'].lower()}:{i}"
        did = draft_ids[i] if i < len(draft_ids) else None
        store.execute("INSERT INTO held_steps (id, enroll_approval, email, contact, step_index, subject, body, draft_id, "
                      "owner, due_at, status, meta, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(id) DO NOTHING",
                      (hid, enroll_approval, contact["email"].lower(), json.dumps(contact), i, s.get("subject", ""),
                       s.get("body", ""), did, owner, due.isoformat(), HELD, json.dumps(meta or {}, default=str),
                       now_iso(), now_iso()))
        out.append(hid)
    return out


def due(store: Store, now: datetime | None = None) -> list[dict]:
    ensure(store)
    now = now or datetime.now(timezone.utc)
    rows = store.query("SELECT * FROM held_steps WHERE status=? AND due_at<=? ORDER BY due_at", (HELD, now.isoformat()))
    for r in rows:
        r["contact"] = json.loads(r["contact"] or "{}")
        r["meta"] = json.loads(r["meta"] or "{}")
    return rows


def mark(store: Store, hid: str, status: str, reason: str = "", approval_id: int | None = None) -> None:
    ensure(store)
    store.execute("UPDATE held_steps SET status=?, reason=?, approval_id=COALESCE(?, approval_id), updated_at=? WHERE id=?",
                  (status, reason, approval_id, now_iso(), hid))


def cancel_for(store: Store, email: str, reason: str) -> int:
    """Cancel every held or queued step for a person (reply, opt-out, handed to an AE). A queued step's pending
    approval is closed too; one already approved is refused at send time because its step is cancelled."""
    ensure(store)
    rows = store.query("SELECT id, approval_id FROM held_steps WHERE email=? AND status IN (?,?)",
                       (email.lower(), HELD, QUEUED))
    for r in rows:
        store.execute("UPDATE held_steps SET status=?, reason=?, updated_at=? WHERE id=? AND status IN (?,?)",
                      (CANCELLED, reason, now_iso(), r["id"], HELD, QUEUED))
        if r["approval_id"]:
            store.execute("UPDATE approvals SET status='rejected', decided_at=?, decided_by=? WHERE id=? AND status='pending'",
                          (now_iso(), "auto:sequence_stopped", r["approval_id"]))
    return len(rows)
