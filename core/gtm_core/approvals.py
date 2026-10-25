"""Human approval queue. No send and no live CRM write happens without an approved request."""
from __future__ import annotations

import json
from typing import Callable

from .audit import Audit
from .store import Store, now_iso

PENDING, APPROVED, REJECTED, EXECUTING, EXECUTED, FAILED = ("pending", "approved", "rejected", "executing",
                                                         "executed", "failed")

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

    def list(self, status: str | None = PENDING, all_agents: bool = False) -> list[dict]:
        sql, params = "SELECT * FROM approvals WHERE 1=1", []
        if status:
            sql += " AND status=?"; params.append(status)
        if not all_agents and self.agent != "core":
            sql += " AND agent=?"; params.append(self.agent)
        rows = self.store.query(sql + " ORDER BY id", params)
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
        n = self.store.execute("UPDATE approvals SET status=?, decided_at=?, decided_by=? WHERE id=? AND status=?",
                               (status, now_iso(), by, rid, PENDING))
        if not n:  # someone else decided it in the meantime
            raise ValueError(f"approval {rid} is no longer pending")
        if not approve:  # drafts waiting on this approval will never go out
            self.store.execute("UPDATE drafts SET status=? WHERE approval_id=? AND status IN ('queued','draft')",
                               (REJECTED, rid))
        self.audit.log("approval.decided", id=rid, status=status, by=by)

    def execute_one(self, rid: int) -> dict:
        """Execute a single approved action now (used for safety actions that only reduce contact)."""
        row = self.store.one("SELECT * FROM approvals WHERE id=? AND status=?", (rid, APPROVED))
        if not row or not self.store.execute("UPDATE approvals SET status=? WHERE id=? AND status=?",
                                             (EXECUTING, rid, APPROVED)):
            return {"id": rid, "skipped": "not approved or already taken"}
        fn = _EXECUTORS.get(row["action"])
        try:
            res = fn(json.loads(row["payload"] or "{}")) if fn else {"error": f"no executor for {row['action']}"}
            self.store.execute("UPDATE approvals SET status=?, result=? WHERE id=?",
                               (EXECUTED, json.dumps(res, default=str), rid))
            return {"id": rid, "result": res}
        except Exception as e:
            self.store.execute("UPDATE approvals SET status=?, result=? WHERE id=?",
                               (FAILED, json.dumps({"error": str(e)}), rid))
            return {"id": rid, "error": str(e)}

    def execute_approved(self, dry_run: bool = False) -> list[dict]:
        """Run every approved action through its registered executor."""
        results = []
        for row in self.list(APPROVED, all_agents=True):
            fn = _EXECUTORS.get(row["action"])
            if fn is None:
                results.append({"id": row["id"], "error": f"no executor for {row['action']}"})
                continue
            if dry_run:
                results.append({"id": row["id"], "dry_run": True, "action": row["action"]})
                continue
            # Claim the row first so two runners (CLI, API, scheduler) never execute the same action.
            # A crash after the claim leaves it 'executing' for a human to check; it is never re-sent.
            if not self.store.execute("UPDATE approvals SET status=? WHERE id=? AND status=?",
                                      (EXECUTING, row["id"], APPROVED)):
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
