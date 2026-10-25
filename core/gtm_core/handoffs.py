"""Agent-to-agent handoffs through the customer's own database.

One agent finishes a piece of work and leaves a handoff for another, for example
Meeting Intelligence -> Seller Follow-Up ("draft the recap for meeting m-42").
The receiving agent's scheduled job picks up its pending handoffs, does the work
and marks them consumed. No message bus, nothing leaves the customer's environment.
"""
from __future__ import annotations

import json

from .store import Store, now_iso

PENDING, PROCESSING, CONSUMED, FAILED = "pending", "processing", "consumed", "failed"
MAX_ATTEMPTS = 3


class Handoffs:
    def __init__(self, store: Store, agent: str):
        self.store = store
        self.agent = agent

    def send(self, to_agent: str, kind: str, ref: str, payload: dict | None = None) -> int | None:
        """Leave work for another agent. Skips a duplicate that is still pending (same target, kind, ref)."""
        dup = self.store.one("SELECT id FROM handoffs WHERE to_agent=? AND kind=? AND ref=? AND status=?",
                             (to_agent, kind, ref, PENDING))
        if dup:
            return None
        return self.store.insert(
            "INSERT INTO handoffs (from_agent, to_agent, kind, ref, payload, status, created_at) VALUES (?,?,?,?,?,?,?)",
            (self.agent, to_agent, kind, ref, json.dumps(payload or {}, default=str), PENDING, now_iso()))

    def pending(self, kind: str | None = None, limit: int = 100) -> list[dict]:
        sql, params = "SELECT * FROM handoffs WHERE to_agent=? AND status=?", [self.agent, PENDING]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        rows = self.store.query(sql + " ORDER BY id LIMIT ?", (*params, limit))
        for r in rows:
            r["payload"] = json.loads(r["payload"] or "{}")
        return rows

    def consume(self, handoff_id: int) -> None:
        self.store.execute("UPDATE handoffs SET status=?, consumed_at=? WHERE id=?", (CONSUMED, now_iso(), handoff_id))

    def claim(self, handoff_id: int) -> bool:
        """Atomically take a pending handoff. False if another runner already has it."""
        return bool(self.store.execute("UPDATE handoffs SET status=? WHERE id=? AND status=?",
                                       (PROCESSING, handoff_id, PENDING)))

    def fail(self, handoff_id: int, error: str) -> str:
        """Record a failure. Back to pending for a retry, or failed after MAX_ATTEMPTS."""
        row = self.store.one("SELECT payload FROM handoffs WHERE id=?", (handoff_id,))
        payload = json.loads((row or {}).get("payload") or "{}")
        attempts = int(payload.get("_attempts", 0)) + 1
        payload.update({"_attempts": attempts, "_error": error[:300]})
        status = FAILED if attempts >= MAX_ATTEMPTS else PENDING
        self.store.execute("UPDATE handoffs SET status=?, payload=? WHERE id=?",
                           (status, json.dumps(payload, default=str), handoff_id))
        return status

    def process(self, kind: str, fn, limit: int = 100) -> dict:
        """Claim, handle and consume each pending handoff of `kind`. One bad item never blocks the rest."""
        done, failed, results = 0, 0, []
        for h in self.pending(kind, limit):
            if not self.claim(h["id"]):
                continue
            try:
                results.append(fn(h))
                self.consume(h["id"])
                done += 1
            except Exception as e:
                failed += 1
                self.fail(h["id"], f"{type(e).__name__}: {e}")
        return {"processed": done, "failed": failed, "results": results}

    def all(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.store.query("SELECT * FROM handoffs WHERE status=? ORDER BY id", (status,))
        else:
            rows = self.store.query("SELECT * FROM handoffs ORDER BY id")
        for r in rows:
            r["payload"] = json.loads(r["payload"] or "{}")
        return rows
