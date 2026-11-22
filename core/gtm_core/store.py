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
CREATE TABLE IF NOT EXISTS contacts (
  id TEXT PRIMARY KEY,
  account_id TEXT,
  crm_id TEXT,
  name TEXT,
  email TEXT,
  title TEXT,
  seniority TEXT,
  function TEXT,
  phone TEXT,
  linkedin TEXT,
  attrs TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_contacts_account ON contacts(account_id);
CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,
  email TEXT,
  name TEXT,
  company TEXT,
  domain TEXT,
  title TEXT,
  source TEXT,
  event TEXT,
  message TEXT,
  received_at TEXT,
  account_id TEXT,
  contact_id TEXT,
  status TEXT,
  score REAL,
  tier TEXT,
  owner TEXT,
  attrs TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_leads_status ON leads(status, received_at);
CREATE TABLE IF NOT EXISTS deals (
  id TEXT PRIMARY KEY,
  crm_id TEXT,
  account_id TEXT,
  name TEXT,
  owner TEXT,
  stage TEXT,
  status TEXT,
  amount REAL,
  close_date TEXT,
  created_at TEXT,
  stage_entered_at TEXT,
  last_activity_at TEXT,
  next_step TEXT,
  next_step_date TEXT,
  forecast_category TEXT,
  meddpicc TEXT,
  attrs TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_deals_account ON deals(account_id);
CREATE TABLE IF NOT EXISTS deal_history (
  id {AUTOID},
  deal_id TEXT NOT NULL,
  snapshot_at TEXT,
  stage TEXT,
  status TEXT,
  amount REAL,
  close_date TEXT,
  forecast_category TEXT
);
CREATE INDEX IF NOT EXISTS ix_deal_history ON deal_history(deal_id, snapshot_at);
CREATE TABLE IF NOT EXISTS deal_stage_history (
  id TEXT PRIMARY KEY,
  deal_id TEXT NOT NULL,
  stage TEXT,
  amount REAL,
  close_date TEXT,
  forecast_category TEXT,
  probability REAL,
  changed_at TEXT,
  attrs TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_deal_stage_history ON deal_stage_history(deal_id, changed_at);
CREATE TABLE IF NOT EXISTS meetings (
  id TEXT PRIMARY KEY,
  account_id TEXT,
  deal_id TEXT,
  title TEXT,
  started_at TEXT,
  owner TEXT,
  attendees TEXT,
  transcript TEXT,
  summary TEXT,
  source TEXT,
  processed_at TEXT,
  attrs TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_meetings_account ON meetings(account_id, started_at);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  owner TEXT,
  account_id TEXT,
  deal_id TEXT,
  contact_id TEXT,
  title TEXT,
  due_at TEXT,
  status TEXT,
  source TEXT,
  attrs TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_due ON tasks(status, due_at);
CREATE TABLE IF NOT EXISTS drafts (
  id {AUTOID},
  agent TEXT,
  kind TEXT,
  account_id TEXT,
  deal_id TEXT,
  contact_id TEXT,
  lead_id TEXT,
  subject TEXT,
  body TEXT,
  gate_score INTEGER,
  gate_passed INTEGER,
  source TEXT,
  status TEXT,
  approval_id INTEGER,
  meta TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS insights (
  id {AUTOID},
  agent TEXT,
  kind TEXT,
  account_id TEXT,
  deal_id TEXT,
  meeting_id TEXT,
  key TEXT,
  value TEXT,
  evidence TEXT,
  observed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_insights_kind ON insights(kind, key);
CREATE TABLE IF NOT EXISTS handoffs (
  id {AUTOID},
  from_agent TEXT,
  to_agent TEXT,
  kind TEXT,
  ref TEXT,
  payload TEXT,
  status TEXT,
  created_at TEXT,
  consumed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_handoffs_to ON handoffs(to_agent, status);
CREATE TABLE IF NOT EXISTS decisions (
  id {AUTOID},
  model TEXT NOT NULL,
  subject TEXT NOT NULL,
  state_hash TEXT,
  fingerprint TEXT,
  backend TEXT,
  answers TEXT,
  score REAL,
  coverage REAL,
  shadow TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_decisions_subject ON decisions(model, subject, created_at);
CREATE TABLE IF NOT EXISTS email_events (
  id {AUTOID},
  email TEXT NOT NULL,
  contact_id TEXT,
  account_id TEXT,
  draft_id INTEGER,
  step TEXT,
  angle TEXT,
  value_prop TEXT,
  event TEXT NOT NULL,
  machine INTEGER,
  occurred_at TEXT,
  source TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_email_events ON email_events(email, event, occurred_at);
CREATE TABLE IF NOT EXISTS forecast_calls (
  id {AUTOID},
  period TEXT NOT NULL,
  owner TEXT NOT NULL,
  commit_amount REAL,
  best_case REAL,
  pipeline REAL,
  closed REAL,
  notes TEXT,
  deals TEXT,
  submitted_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_forecast_calls ON forecast_calls(period, owner, submitted_at);
"""

# Record tables with a JSON `attrs` column for anything that is not a named column.
RECORD_TABLES = {
    "contacts": ["id", "account_id", "crm_id", "name", "email", "title", "seniority", "function", "phone", "linkedin"],
    "leads": ["id", "email", "name", "company", "domain", "title", "source", "event", "message", "received_at",
              "account_id", "contact_id", "status", "score", "tier", "owner"],
    "deals": ["id", "crm_id", "account_id", "name", "owner", "stage", "status", "amount", "close_date", "created_at",
              "stage_entered_at", "last_activity_at", "next_step", "next_step_date", "forecast_category", "meddpicc"],
    "meetings": ["id", "account_id", "deal_id", "title", "started_at", "owner", "attendees", "transcript", "summary",
                 "source", "processed_at"],
    "tasks": ["id", "owner", "account_id", "deal_id", "contact_id", "title", "due_at", "status", "source"],
    # CRM stage history (Salesforce OpportunityHistory): one row per change, keyed by the CRM row id
    "deal_stage_history": ["id", "deal_id", "stage", "amount", "close_date", "forecast_category", "probability", "changed_at"],
}
JSON_COLUMNS = {"meddpicc", "attendees", "summary"}

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
        if self.kind == "postgres":  # REAL is 4-byte on Postgres; money and scores need 8
            ddl = ddl.replace(" REAL", " DOUBLE PRECISION")
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

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run a statement; returns the number of rows changed (used for atomic claims)."""
        with self._lock:
            if self.kind == "sqlite":
                cur = self.conn.execute(sql, tuple(params))
                self.conn.commit()
                return cur.rowcount
            with self.conn.cursor() as cur:
                cur.execute(self._sql(sql), tuple(params))
                return cur.rowcount

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
        """Insert a signal; returns False when it is a duplicate (same id).
        observed_at is normalized to ISO 8601 UTC; an unparseable date raises ValueError."""
        from .pipeline import parse_dt
        d = parse_dt(sig.get("observed_at"))
        if d is None:
            raise ValueError(f"signal for {sig.get('account_id')}: unreadable observed_at {sig.get('observed_at')!r}")
        sig = {**sig, "observed_at": d.replace(microsecond=0).isoformat()}
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

    # ---------- generic records (contacts, leads, deals, meetings, tasks) ----------
    def upsert(self, table: str, row: dict) -> None:
        """Insert or merge a record. Unknown keys go to `attrs`; existing attrs are kept and updated.
        Keys left out keep their stored value; a key passed as None clears it."""
        cols = RECORD_TABLES[table]
        if not row.get("id"):
            raise ValueError(f"{table} record needs an id")
        old = self.get(table, row["id"]) or {}
        merged = {**old, **row}
        values = []
        for c in cols:
            v = merged.get(c)
            values.append(json.dumps(v, default=str) if c in JSON_COLUMNS and v is not None else v)
        attrs = {k: v for k, v in merged.items() if k not in cols and k not in ("attrs", "updated_at") and v is not None}
        all_cols = cols + ["attrs", "updated_at"]
        placeholders = ",".join("?" * len(all_cols))
        updates = ", ".join(f"{c}=excluded.{c}" for c in all_cols if c != "id")
        self.execute(f"INSERT INTO {table} ({', '.join(all_cols)}) VALUES ({placeholders}) "
                     f"ON CONFLICT(id) DO UPDATE SET {updates}",
                     (*values, json.dumps(attrs, default=str), now_iso()))

    def _decode(self, row: dict) -> dict:
        for c in JSON_COLUMNS:
            if c in row and isinstance(row[c], str):
                try:
                    row[c] = json.loads(row[c])
                except json.JSONDecodeError:
                    pass
        if "attrs" in row:
            row.update(json.loads(row.pop("attrs") or "{}"))
        return row

    def get(self, table: str, record_id: str) -> dict | None:
        if table not in RECORD_TABLES:
            raise KeyError(table)
        r = self.one(f"SELECT * FROM {table} WHERE id=?", (record_id,))
        return self._decode(r) if r else None

    def select(self, table: str, where: str = "", params: Iterable[Any] = (), order: str = "") -> list[dict]:
        if table not in RECORD_TABLES:
            raise KeyError(table)
        sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + (f" ORDER BY {order}" if order else "")
        return [self._decode(r) for r in self.query(sql, params)]

    def contact_by_email(self, email: str) -> dict | None:
        rows = self.select("contacts", "LOWER(email)=?", ((email or "").lower(),))
        return rows[0] if rows else None

    def account_by_domain(self, domain: str) -> dict | None:
        d = (domain or "").lower().removeprefix("www.")
        if not d:
            return None
        r = self.one("SELECT * FROM accounts WHERE LOWER(domain)=? OR id=?", (d, d))
        if r:
            r.update(json.loads(r.pop("attrs") or "{}"))
        return r

    def snapshot_deal(self, deal: dict) -> None:
        self.insert("INSERT INTO deal_history (deal_id, snapshot_at, stage, status, amount, close_date, forecast_category) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (deal["id"], now_iso(), deal.get("stage"), deal.get("status"), deal.get("amount"),
                     deal.get("close_date"), deal.get("forecast_category")))

    def deal_history(self, deal_id: str) -> list[dict]:
        return self.query("SELECT * FROM deal_history WHERE deal_id=? ORDER BY snapshot_at, id", (deal_id,))

    # ---------- drafts and insights ----------
    def add_draft(self, agent: str, kind: str, body: str, subject: str = "", gate_score: int | None = None,
                  gate_passed: bool | None = None, source: str = "model", status: str = "draft", **refs) -> int:
        meta = refs.pop("meta", {})
        return self.insert(
            "INSERT INTO drafts (agent, kind, account_id, deal_id, contact_id, lead_id, subject, body, gate_score, "
            "gate_passed, source, status, approval_id, meta, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (agent, kind, refs.get("account_id"), refs.get("deal_id"), refs.get("contact_id"), refs.get("lead_id"),
             subject, body, gate_score, None if gate_passed is None else int(bool(gate_passed)), source, status,
             refs.get("approval_id"), json.dumps(meta, default=str), now_iso()))

    def drafts(self, agent: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        sql, params = "SELECT * FROM drafts WHERE 1=1", []
        if agent:
            sql += " AND agent=?"; params.append(agent)
        if status:
            sql += " AND status=?"; params.append(status)
        rows = self.query(sql + " ORDER BY id DESC LIMIT ?", (*params, limit))
        for r in rows:
            r["meta"] = json.loads(r.get("meta") or "{}")
        return rows

    def add_insight(self, agent: str, kind: str, key: str, value: Any = None, evidence: str = "",
                    observed_at: str | None = None, **refs) -> int:
        return self.insert(
            "INSERT INTO insights (agent, kind, account_id, deal_id, meeting_id, key, value, evidence, observed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (agent, kind, refs.get("account_id"), refs.get("deal_id"), refs.get("meeting_id"), key,
             json.dumps(value, default=str), evidence[:2000], observed_at or now_iso()))

    def insights(self, kind: str | None = None, since_iso: str | None = None, **refs) -> list[dict]:
        sql, params = "SELECT * FROM insights WHERE 1=1", []
        if kind:
            sql += " AND kind=?"; params.append(kind)
        if since_iso:
            sql += " AND observed_at>=?"; params.append(since_iso)
        for k in ("account_id", "deal_id", "meeting_id"):
            if refs.get(k):
                sql += f" AND {k}=?"; params.append(refs[k])
        rows = self.query(sql + " ORDER BY observed_at DESC, id DESC", params)
        for r in rows:
            r["value"] = json.loads(r["value"]) if r.get("value") else None
        return rows

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
