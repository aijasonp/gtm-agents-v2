"""Durable waits: something must happen by a deadline, and if it does not, people hear about it in order.

A wait is "the AE confirms this email by 15:00", "someone touches this contact by Thursday". It lives in
the customer's database, so it survives restarts, deploys and a scheduler that was down for an hour: the
next tick sees every wait whose check time has passed and escalates exactly once per level.

    waits = Waits(store)
    waits.open("approval", "approval:42", deadline, ladder=[{"after_hours": 0, "notify": "owner"},
                                                             {"after_hours": 8, "notify": "manager"}])
    waits.resolve("approval", "approval:42", "approved", by="Sam Rivera")
    for w in waits.due(now):          # claimed atomically: two schedulers never escalate the same level
        notify(w["notify"], w)

Backends (GTM_WORKFLOW_BACKEND):
  builtin  this table plus the scheduler tick. Default, no extra service, works on SQLite and Postgres.
  dbos     each wait also runs as a DBOS durable workflow (pip install dbos) that sleeps on DBOS.recv with a
           timeout per ladder level, so escalations fire on time even between scheduler ticks. The table stays
           the record either way, so tools and reports read the same rows.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

from .store import Store, now_iso

SCHEMA = """CREATE TABLE IF NOT EXISTS workflow_waits (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, owner TEXT, payload TEXT, status TEXT NOT NULL,
  deadline_at TEXT NOT NULL, next_check_at TEXT, level INTEGER, ladder TEXT, created_at TEXT, updated_at TEXT,
  resolved_at TEXT, resolved_by TEXT, outcome TEXT)"""
INDEX = "CREATE INDEX IF NOT EXISTS ix_waits_due ON workflow_waits(status, next_check_at)"

WAITING, DONE, EXHAUSTED, CANCELLED = "waiting", "done", "exhausted", "cancelled"
DEFAULT_LADDER = [{"after_hours": 0, "notify": "owner"}, {"after_hours": 8, "notify": "manager"}]


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def wait_id(kind: str, subject: str) -> str:
    return f"{kind}:{subject}"


class Waits:
    backend = "builtin"

    def __init__(self, store: Store):
        self.store = store
        if not getattr(store, "_waits_schema", False):
            store.execute(SCHEMA)
            store.execute(INDEX)
            store._waits_schema = True

    # ---- lifecycle ----
    def open(self, kind: str, subject: str, deadline: datetime, ladder: list[dict] | None = None,
             owner: str | None = None, payload: dict | None = None) -> dict:
        """Start waiting (idempotent: an open wait for the same kind and subject is returned unchanged)."""
        wid = wait_id(kind, subject)
        old = self.get(kind, subject)
        if old and old["status"] == WAITING:
            return old
        ladder = sorted(ladder or DEFAULT_LADDER, key=lambda s: float(s.get("after_hours", 0)))
        first = deadline + timedelta(hours=float(ladder[0].get("after_hours", 0)))
        row = (wid, kind, subject, owner, json.dumps(payload or {}, default=str), WAITING, _iso(deadline), _iso(first),
               0, json.dumps(ladder), now_iso(), now_iso())
        if old:  # re-open a finished wait (a new deadline for the same subject)
            self.store.execute("UPDATE workflow_waits SET owner=?, payload=?, status=?, deadline_at=?, next_check_at=?, "
                               "level=?, ladder=?, updated_at=?, resolved_at=NULL, resolved_by=NULL, outcome=NULL "
                               "WHERE id=?", (*row[3:10], row[11], wid))
        else:
            self.store.execute("INSERT INTO workflow_waits (id, kind, subject, owner, payload, status, deadline_at, "
                               "next_check_at, level, ladder, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
        return self.get(kind, subject)

    def resolve(self, kind: str, subject: str, outcome: str = "done", by: str = "system") -> bool:
        n = self.store.execute("UPDATE workflow_waits SET status=?, resolved_at=?, resolved_by=?, outcome=?, updated_at=? "
                               "WHERE id=? AND status=?", (DONE, now_iso(), by, outcome, now_iso(), wait_id(kind, subject),
                                                          WAITING))
        return bool(n)

    def cancel(self, kind: str, subject: str, why: str = "") -> bool:
        n = self.store.execute("UPDATE workflow_waits SET status=?, outcome=?, updated_at=? WHERE id=? AND status=?",
                               (CANCELLED, why, now_iso(), wait_id(kind, subject), WAITING))
        return bool(n)

    # ---- reads ----
    def get(self, kind: str, subject: str) -> dict | None:
        r = self.store.one("SELECT * FROM workflow_waits WHERE id=?", (wait_id(kind, subject),))
        return self._decode(r) if r else None

    def list(self, kind: str | None = None, status: str | None = WAITING, owner: str | None = None) -> list[dict]:
        sql, p = "SELECT * FROM workflow_waits WHERE 1=1", []
        for col, v in (("kind", kind), ("status", status), ("owner", owner)):
            if v:
                sql += f" AND {col}=?"
                p.append(v)
        return [self._decode(r) for r in self.store.query(sql + " ORDER BY deadline_at", p)]

    @staticmethod
    def _decode(r: dict) -> dict:
        r = dict(r)
        r["payload"] = json.loads(r.get("payload") or "{}")
        r["ladder"] = json.loads(r.get("ladder") or "[]")
        return r

    # ---- the tick ----
    def due(self, now: datetime | None = None, skip_kinds: set | None = None) -> list[dict]:
        """Claim every wait whose next escalation time has passed. Each returned item is one ladder level,
        handed out once: the claim moves next_check_at forward (or marks the ladder exhausted) atomically."""
        now = now or datetime.now(timezone.utc)
        out = []
        for _ in range(20):  # catch up every overdue level (a scheduler that was down for a day)
            got = self._claim(now, skip_kinds or set())
            if not got:
                break
            out += got
        return out

    def _claim(self, now: datetime, skip_kinds: set = frozenset()) -> list[dict]:
        out = []
        rows = self.store.query("SELECT * FROM workflow_waits WHERE status=? AND next_check_at<=? ORDER BY next_check_at",
                                (WAITING, _iso(now)))
        for r in rows:
            if r["kind"] in skip_kinds:
                continue
            w = self._decode(r)
            lvl = int(w["level"] or 0)
            ladder = w["ladder"]
            if lvl >= len(ladder):
                continue
            nxt = lvl + 1
            if nxt < len(ladder):
                nxt_at = _iso(_dt(w["deadline_at"]) + timedelta(hours=float(ladder[nxt].get("after_hours", 0))))
                claimed = self.store.execute("UPDATE workflow_waits SET level=?, next_check_at=?, updated_at=? WHERE id=? "
                                             "AND level=? AND status=?", (nxt, nxt_at, now_iso(), w["id"], lvl, WAITING))
            else:
                claimed = self.store.execute("UPDATE workflow_waits SET level=?, next_check_at=NULL, status=?, updated_at=? "
                                             "WHERE id=? AND level=? AND status=?",
                                             (nxt, EXHAUSTED, now_iso(), w["id"], lvl, WAITING))
            if claimed:
                out.append({**w, "escalation_level": lvl, "notify": ladder[lvl].get("notify", "owner"),
                            "step": ladder[lvl]})
        return out


# ---------- DBOS backend ----------
_HANDLERS: dict[str, Callable[[dict], None]] = {}


def on_escalation(kind: str):
    """Register what happens when a wait of this kind escalates (used by the DBOS backend; the builtin tick
    hands the same dicts back from due())."""
    def deco(fn):
        _HANDLERS[kind] = fn
        return fn
    return deco


class DbosWaits(Waits):
    """Waits that also run as DBOS durable workflows. Requires `pip install dbos` and DBOS.launch() at startup
    (gtm schedule does it when GTM_WORKFLOW_BACKEND=dbos). The table is still written, so every tool and
    report works the same; due() returns nothing because DBOS drives the ladder."""
    backend = "dbos"

    def __init__(self, store: Store):
        super().__init__(store)
        _dbos_workflow()  # registers the workflow once

    def open(self, kind, subject, deadline, ladder=None, owner=None, payload=None) -> dict:
        w = super().open(kind, subject, deadline, ladder, owner, payload)
        from dbos import DBOS, SetWorkflowID
        wf = _dbos_workflow()
        with SetWorkflowID(f"gtm-wait:{w['id']}:{w['deadline_at']}"):
            DBOS.start_workflow(wf, w["id"])
        return w

    def resolve(self, kind, subject, outcome="done", by="system") -> bool:
        w = self.get(kind, subject)
        ok = super().resolve(kind, subject, outcome, by)
        if ok and w:
            from dbos import DBOS
            DBOS.send(f"gtm-wait:{w['id']}:{w['deadline_at']}", {"outcome": outcome, "by": by}, topic="resolve")
        return ok

    def due(self, now=None) -> list[dict]:
        """Kinds with a registered on_escalation handler are escalated by the DBOS workflow; every other kind is
        claimed here by the regular sweep, so nothing is dropped when no handler is registered."""
        return super().due(now, set(_HANDLERS))


_WF = {}


def _dbos_workflow():
    if "wf" in _WF:
        return _WF["wf"]
    from dbos import DBOS

    @DBOS.step()
    def escalate(wid: str, level: int) -> bool:
        st = _WF["store"]
        r = st.one("SELECT * FROM workflow_waits WHERE id=?", (wid,))
        if not r or r["status"] != WAITING or int(r["level"] or 0) != level:
            return False
        w = Waits._decode(r)
        fn = _HANDLERS.get(w["kind"])
        if fn is None:
            return False  # no handler: the sweep claims this level through Waits.due()
        last = level + 1 >= len(w["ladder"])
        if not st.execute("UPDATE workflow_waits SET level=?, status=?, updated_at=? WHERE id=? AND level=? AND status=?",
                          (level + 1, EXHAUSTED if last else WAITING, now_iso(), wid, level, WAITING)):
            return False  # claimed elsewhere
        fn({**w, "escalation_level": level, "notify": w["ladder"][level].get("notify", "owner"),
            "step": w["ladder"][level]})
        return True

    @DBOS.workflow()
    def gtm_wait(wid: str) -> str:
        st = _WF["store"]
        w = Waits._decode(st.one("SELECT * FROM workflow_waits WHERE id=?", (wid,)))
        deadline = _dt(w["deadline_at"])
        for level, step in enumerate(w["ladder"]):
            at = deadline + timedelta(hours=float(step.get("after_hours", 0)))
            # recv's result is recorded by DBOS, so a replay after a crash resumes here without re-sleeping
            secs = max(0.0, (at - datetime.now(timezone.utc)).total_seconds())
            msg = DBOS.recv(topic="resolve", timeout_seconds=secs)
            if msg is not None:
                return "resolved"
            escalate(wid, level)
        return "exhausted"

    _WF["wf"] = gtm_wait
    return gtm_wait


def get_waits(store: Store) -> Waits:
    """The configured backend. dbos falls back to builtin (with a note in the audit log) when not installed."""
    if (os.environ.get("GTM_WORKFLOW_BACKEND") or "builtin").lower() == "dbos":
        try:
            import dbos  # noqa: F401
            _WF["store"] = store
            return DbosWaits(store)
        except ImportError:
            from .audit import Audit
            Audit(store, "core").log("workflows.fallback", reason="GTM_WORKFLOW_BACKEND=dbos but dbos is not installed")
    return Waits(store)


def launch_backend(settings) -> str:
    """Start the workflow backend for a long-running process (gtm schedule). Returns the backend in use."""
    if (os.environ.get("GTM_WORKFLOW_BACKEND") or "builtin").lower() != "dbos":
        return "builtin"
    try:
        from dbos import DBOS
    except ImportError:
        return "builtin"
    url = os.environ.get("GTM_DBOS_DATABASE_URL") or settings.database_url
    DBOS(config={"name": "gtm-agents", "system_database_url": url})
    _WF["store"] = Store(settings.database_url)
    _WF["store"].init()
    _dbos_workflow()
    DBOS.launch()
    return "dbos"
