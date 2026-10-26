"""Human approval queue. No send and no live CRM write happens without an approved request.

Sends to a buyer (config/approvals.yaml `send_actions`) need a named person on the team, and pipeline emails
need their owner. The check runs when the decision is made and again right before the send executes.
An approver may edit the subject or body before approving; the edit is applied to the payload and kept in
`approval_edits` (before and after), which is what the drafters learn from.
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Callable

from .approval_policy import ApprovalRefused, Policy
from .audit import Audit
from .store import Store, now_iso

EDIT_SCHEMA = """CREATE TABLE IF NOT EXISTS approval_edits (
  id {AUTOID}, approval_id INTEGER, action TEXT, field TEXT, before TEXT, after TEXT, edited_by TEXT, edited_at TEXT)"""
EDITABLE = {"subject", "body", "steps", "script"}

PENDING, APPROVED, REJECTED, EXECUTING, EXECUTED, FAILED = ("pending", "approved", "rejected", "executing",
                                                         "executed", "failed")

# the approval being executed right now (executors that need their own id read it)
CURRENT: ContextVar[int | None] = ContextVar("gtm_current_approval", default=None)

# action name -> executor(payload) -> result dict
_EXECUTORS: dict[str, Callable[[dict], dict]] = {}


def executor(action: str):
    """Register the function that performs an approved action."""
    def deco(fn: Callable[[dict], dict]):
        _EXECUTORS[action] = fn
        return fn
    return deco


class Approvals:
    def __init__(self, store: Store, agent: str = "core", policy: Policy | None = None):
        self.store = store
        self.agent = agent
        self.audit = Audit(store, agent)
        self._policy = policy
        if not getattr(store, "_edit_schema", False):
            autoid = "INTEGER PRIMARY KEY AUTOINCREMENT" if store.kind == "sqlite" else "BIGSERIAL PRIMARY KEY"
            store.execute(EDIT_SCHEMA.replace("{AUTOID}", autoid))
            store._edit_schema = True

    @property
    def policy(self) -> Policy:
        if self._policy is None:
            self._policy = Policy.load()
        return self._policy

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

    def decide(self, rid: int, approve: bool, by: str = "operator", edits: dict | None = None) -> None:
        """Approve or reject. Approving a send checks the policy first (ApprovalRefused: nothing changed).
        `edits` changes subject, body, steps or script before approval and is recorded."""
        row = self.store.one("SELECT status, action, payload FROM approvals WHERE id=?", (rid,))
        if not row:
            raise KeyError(f"approval {rid} not found")
        if row["status"] != PENDING:
            raise ValueError(f"approval {rid} is {row['status']}, not pending")
        payload = json.loads(row["payload"] or "{}")
        if approve:
            why, who = self.policy.check(row["action"], payload, by)
            if why:
                self.audit.log("approval.refused", id=rid, action=row["action"], by=by, why=why)
                raise ApprovalRefused(why)
            by = who
            if edits:
                bad = set(edits) - EDITABLE
                if bad:
                    raise ValueError(f"cannot edit {sorted(bad)}; editable: {sorted(EDITABLE)}")
                for k, v in edits.items():
                    # sequences keep copy in steps: a subject or body edit lands on the first step
                    holder, field = payload, k
                    if k in ("subject", "body") and k not in payload and payload.get("steps"):
                        holder, field = payload["steps"][0], k
                    if holder.get(field) != v:
                        name = f"steps.0.{field}" if holder is not payload else field
                        self.store.insert("INSERT INTO approval_edits (approval_id, action, field, before, after, "
                                          "edited_by, edited_at) VALUES (?,?,?,?,?,?,?)",
                                          (rid, row["action"], name, json.dumps(holder.get(field), default=str),
                                           json.dumps(v, default=str), by, now_iso()))
                        holder[field] = v
                self.store.execute("UPDATE approvals SET payload=? WHERE id=? AND status=?",
                                   (json.dumps(payload, default=str), rid, PENDING))
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
        guard = self.policy.send_guard(row["action"], row.get("decided_by"))
        if guard:
            self.store.execute("UPDATE approvals SET status=?, result=? WHERE id=?",
                               (FAILED, json.dumps({"error": guard}), rid))
            self.audit.log("approval.send_refused", id=rid, action=row["action"])
            return {"id": rid, "error": guard}
        try:
            tok = CURRENT.set(rid)
            try:
                res = fn(json.loads(row["payload"] or "{}")) if fn else {"error": f"no executor for {row['action']}"}
            finally:
                CURRENT.reset(tok)
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
            guard = self.policy.send_guard(row["action"], row.get("decided_by"))
            if guard:
                self.store.execute("UPDATE approvals SET status=?, result=? WHERE id=?",
                                   (FAILED, json.dumps({"error": guard}), row["id"]))
                self.audit.log("approval.send_refused", id=row["id"], action=row["action"])
                results.append({"id": row["id"], "error": guard})
                continue
            try:
                tok = CURRENT.set(row["id"])
                try:
                    res = fn(row["payload"])
                finally:
                    CURRENT.reset(tok)
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
