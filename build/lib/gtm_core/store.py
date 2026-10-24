"""Storage: SQLite for development and tests, Postgres (with pgvector) in production.

The customer owns this database. Nothing in it leaves their environment.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT,
  crm_id TEXT,
  industry TEXT,
  employees INTEGER,
  revenue REAL,
  country TEXT,
  attrs TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS signals (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  category TEXT NOT NULL,
  source TEXT,
  url TEXT,
  observed_at TEXT NOT NULL,
  strength REAL,
  payload TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_signals_account ON signals(account_id, observed_at);
CREATE TABLE IF NOT EXISTS scores (
  id {AUTOID},
  run_id TEXT,
  agent TEXT,
  account_id TEXT NOT NULL,
  score REAL,
  icp REAL,
  signal_score REAL,
  tier TEXT,
  reasons TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_scores_run ON scores(run_id, score);
CREATE TABLE IF NOT EXISTS weights (
  key TEXT PRIMARY KEY,
  value REAL NOT NULL,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS outcomes (
  id {AUTOID},
  account_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  value REAL,
  observed_at TEXT,
  source TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
  id {AUTOID},
  agent TEXT,
  action TEXT NOT NULL,
  payload TEXT,
  status TEXT NOT NULL,
  requested_at TEXT,
  decided_at TEXT,
  decided_by TEXT,
  result TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  id {AUTOID},
  ts TEXT,
  agent TEXT,
  event TEXT,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS token_usage (
  id {AUTOID},
  ts TEXT,
  agent TEXT,
  model TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  usd REAL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  agent TEXT,
  job TEXT,
  started_at TEXT,
  finished_at TEXT,
  status TEXT,
  stats TEXT
);
CREATE TABLE IF NOT EXISTS state (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""

PG_EXTRA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS memories (
  id BIGSERIAL PRIMARY KEY,
  agent TEXT,
  account_id TEXT,
  kind TEXT,
  content TEXT,
  embedding vector(1536),
  created_at TIMESTAMPTZ DEFAULT now()
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    """Thin DB wrapper. SQL is written with `?` placeholders and translated for Postgres."""

    def __init__(self, url: str = "sqlite:///gtm.db"):
        self.url = url
        self._lock = threading.RLock()
        if url.startswith("sqlite"):
            path = url.split("sqlite:///", 1)[-1] or ":memory:"
            self.kind = "sqlite"
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL") if path != ":memory:" else None
        elif url.startswith(("postgres://", "postgresql://")):
            import psycopg  # optional dependency
            from psycopg.rows import dict_row

            self.kind = "postgres"
            self.conn = psycopg.connect(url, row_factory=dict_row, autocommit=True)
        else:
            raise ValueError(f"Unsupported DATABASE_URL: {url}")

    # ---------- schema ----------
    def init(self) -> None:
        autoid = "INTEGER PRIMARY KEY AUTOINCREMENT" if self.kind == "sqlite" else "BIGSERIAL PRIMARY KEY"
        ddl = SCHEMA.replace("{AUTOID}", autoid)
        with self._lock:
            if self.kind == "sqlite":
                self.conn.executescript(ddl)
                self.conn.commit()
            else:
                with self.conn.cursor() as cur:
                    for stmt in [s for s in ddl.split(";") if s.strip()]:
                        cur.execute(stmt)
                    try:
                        for stmt in [s for s in PG_EXTRA.split(";") if s.strip()]:
                            cur.execute(stmt)
                    except Exception:  # pgvector not installed: memory search disabled
                        pass

    # ---------- primitives ----------
    def _sql(self, sql: str) -> str:
        return sql if self.kind == "sqlite" else sql.replace("?", "%s")

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            if self.kind == "sqlite":
                self.conn.execute(sql, tuple(params))
                self.conn.commit()
            else:
                with self.conn.cursor() as cur:
                    cur.execute(self._sql(sql), tuple(params))

    def insert(self, sql: str, params: Iterable[Any] = ()) -> int | None:
        with self._lock:
            if self.kind == "sqlite":
                cur = self.conn.execute(sql, tuple(params))
                self.conn.commit()
                return cur.lastrowid
            with self.conn.cursor() as cur:
                cur.execute(self._sql(sql) + " RETURNING id", tuple(params))
                row = cur.fetchone()
                return row["id"] if row else None

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            if self.kind == "sqlite":
                return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]
            with self.conn.cursor() as cur:
                cur.execute(self._sql(sql), tuple(params))
                return list(cur.fetchall())

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---------- accounts ----------
    def upsert_account(self, acct: dict) -> None:
        attrs = {k: v for k, v in acct.items()
                 if k not in {"id", "name", "domain", "crm_id", "industry", "employees", "revenue", "country"}}
        self.execute(
            """INSERT INTO accounts (id, name, domain, crm_id, industry, employees, revenue, country, attrs, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, domain=excluded.domain, crm_id=excluded.crm_id,
                 industry=excluded.industry, employees=excluded.employees, revenue=excluded.revenue,
                 country=excluded.country, attrs=excluded.attrs, updated_at=excluded.updated_at""",
            (acct["id"], acct["name"], acct.get("domain"), acct.get("crm_id"), acct.get("industry"),
             acct.get("employees"), acct.get("revenue"), acct.get("country"), json.dumps(attrs), now_iso()),
        )

    def accounts(self) -> list[dict]:
        rows = self.query("SELECT * FROM accounts ORDER BY name")
        for r in rows:
            r.update(json.loads(r.pop("attrs") or "{}"))
        return rows

    def account(self, account_id: str) -> dict | None:
        r = self.one("SELECT * FROM accounts WHERE id=? OR domain=? OR crm_id=?", (account_id, account_id, account_id))
        if r:
            r.update(json.loads(r.pop("attrs") or "{}"))
        return r

    # ---------- signals ----------
    def add_signal(self, sig: dict) -> bool:
        """Insert a signal; returns False when it is a duplicate (same id)."""
        if self.one("SELECT id FROM signals WHERE id=?", (sig["id"],)):
            return False
        self.execute(
            """INSERT INTO signals (id, account_id, signal_type, category, source, url, observed_at, strength, payload, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sig["id"], sig["account_id"], sig["signal_type"], sig["category"], sig.get("source"), sig.get("url"),
             sig["observed_at"], sig.get("strength"), json.dumps(sig.get("payload", {})), now_iso()),
        )
        return True

    def signals_for(self, account_id: str, since_iso: str | None = None) -> list[dict]:
        if since_iso:
            rows = self.query("SELECT * FROM signals WHERE account_id=? AND observed_at>=? ORDER BY observed_at DESC",
                              (account_id, since_iso))
        else:
            rows = self.query("SELECT * FROM signals WHERE account_id=? ORDER BY observed_at DESC", (account_id,))
        for r in rows:
            r["payload"] = json.loads(r.get("payload") or "{}")
        return rows

    # ---------- weights ----------
    def get_weights(self) -> dict[str, float]:
        return {r["key"]: r["value"] for r in self.query("SELECT key, value FROM weights")}

    def set_weight(self, key: str, value: float) -> None:
        self.execute(
            """INSERT INTO weights (key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, now_iso()),
        )

    # ---------- outcomes ----------
    def add_outcome(self, account_id: str, outcome: str, value: float = 1.0, source: str = "manual",
                    observed_at: str | None = None) -> None:
        self.insert("INSERT INTO outcomes (account_id, outcome, value, observed_at, source) VALUES (?,?,?,?,?)",
                    (account_id, outcome, value, observed_at or now_iso(), source))

    # ---------- key/value state ----------
    def get_state(self, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM state WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def set_state(self, key: str, value: Any) -> None:
        self.execute("""INSERT INTO state (key, value) VALUES (?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, json.dumps(value)))

    @contextmanager
    def run(self, run_id: str, agent: str, job: str):
        self.execute("INSERT INTO runs (id, agent, job, started_at, status) VALUES (?,?,?,?,?)",
                     (run_id, agent, job, now_iso(), "running"))
        stats: dict = {}
        try:
            yield stats
            self.execute("UPDATE runs SET finished_at=?, status=?, stats=? WHERE id=?",
                         (now_iso(), "ok", json.dumps(stats), run_id))
        except Exception as e:
            stats["error"] = str(e)
            self.execute("UPDATE runs SET finished_at=?, status=?, stats=? WHERE id=?",
                         (now_iso(), "failed", json.dumps(stats), run_id))
            raise
