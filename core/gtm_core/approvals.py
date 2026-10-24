"""Human approval queue. No send and no live CRM write happens without an approved request."""
from __future__ import annotations

import json
from typing import Callable

from .audit import Audit
from .store import Store, now_iso

PENDING, APPROVED, REJECTED, EXECUTED, FAILED = "pending", "approved", "rejected", "executed", "failed"

# action name -> executor(payload) -> result dict
_EXECUTORS: dict[str, Callable[[dict], dict]] = {}


def executor(action: str):
    """Register the function that performs an approved action."""
    def deco(fn: Callable[[dict], dict]):
        _EXECUTORS[action] = fn
        return fn
    return deco


class Approvals:
    def __init__(self, store: Store, agent: str = "core"):
        self.store = store
        self.agent = agent
        self.audit = Audit(store, agent)

    def request(self, action: str, payload: dict) -> int:
        rid = self.store.insert(
            "INSERT INTO approvals (agent, action, payload, status, requested_at) VALUES (?,?,?,?,?)",
            (self.agent, action, json.dumps(payload, default=str), PENDING, now_iso()))
        self.audit.log("approval.requested", id=rid, action=action)
        return rid

    def list(self, status: str | None = PENDING) -> list[dict]:
        if status:
            rows = self.store.query("SELECT * FROM approvals WHERE status=? ORDER BY id", (status,))
        else:
            rows = self.store.query("SELECT * FROM approvals ORDER BY id")
        for r in rows:
            r["payload"] = json.loads(r["payload"] or "{}")
        return rows

    def decide(self, rid: int, approve: bool, by: str = "operator") -> None:
        row = self.store.one("SELECT status FROM approvals WHERE id=?", (rid,))
        if not row:
            raise KeyError(f"approval {rid} not found")
        if row["status"] != PENDING:
            raise ValueError(f"approval {rid} is {row['status']}, not pending")
        status = APPROVED if approve else REJECTED
        self.store.execute("UPDATE approvals SET status=?, decided_at=?, decided_by=? WHERE id=?",
                           (status, now_iso(), by, rid))
        self.audit.log("approval.decided", id=rid, status=status, by=by)

    def execute_approved(self, dry_run: bool = False) -> list[dict]:
        """Run every approved action through its registered executor."""
        results = []
        for row in self.list(APPROVED):
            fn = _EXECUTORS.get(row["action"])
            if fn is None:
                results.append({"id": row["id"], "error": f"no executor for {row['action']}"})
                continue
            if dry_run:
                results.append({"id": row["id"], "dry_run": True, "action": row["action"]})
                continue
            try:
                res = fn(row["payload"])
                self.store.execute("UPDATE approvals SET status=?, result=? WHERE id=?",
                                   (EXECUTED, json.dumps(res, default=str), row["id"]))
                self.audit.log("approval.executed", id=row["id"], action=row["action"])
                results.append({"id": row["id"], "result": res})
            except Exception as e:  # keep going; record the failure
                self.store.execute("UPDATE approvals SET status=?, result=? WHERE id=?",
                                   (FAILED, json.dumps({"error": str(e)}), row["id"]))
                self.audit.log("approval.failed", id=row["id"], error=str(e))
                results.append({"id": row["id"], "error": str(e)})
        return results
