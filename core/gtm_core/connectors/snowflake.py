"""Snowflake connector, read only. Used for metrics that live in the warehouse (marketing, partner, CS data).

Settings (env):
  SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA
  SNOWFLAKE_PRIVATE_KEY_PATH (key-pair auth, preferred; SNOWFLAKE_PRIVATE_KEY_PASSPHRASE if encrypted)
  or SNOWFLAKE_PASSWORD

Give the user a role with SELECT only. The connector also refuses anything that is not a single read statement,
so a bad query in config can never change data.
"""
from __future__ import annotations

import os
import re

READ_START = re.compile(r"^\s*(select|with|show|describe|desc)\b", re.I)
WRITE_WORDS = re.compile(r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|copy|put|call|"
                         r"execute|use)\b", re.I)


class ReadOnlyError(ValueError):
    pass


def check_read_only(sql: str) -> str:
    """Return the statement if it is one read query; raise ReadOnlyError otherwise."""
    body = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql or "", flags=re.S).strip().rstrip(";").strip()
    if not body:
        raise ReadOnlyError("empty query")
    if ";" in body:
        raise ReadOnlyError("one statement per query")
    if not READ_START.match(body):
        raise ReadOnlyError("only SELECT, WITH, SHOW or DESCRIBE queries are allowed")
    literal_free = re.sub(r"'(?:[^']|'')*'", "''", body)
    if not body.lower().startswith(("show", "desc")) and WRITE_WORDS.search(literal_free):
        raise ReadOnlyError("query contains a write keyword")
    return body


def configured() -> bool:
    return bool(os.environ.get("SNOWFLAKE_ACCOUNT") and os.environ.get("SNOWFLAKE_USER"))


class Snowflake:
    name = "snowflake"

    def __init__(self, conn=None, max_rows: int = 5000):
        self._conn = conn
        self.max_rows = max_rows

    def _connect(self):  # pragma: no cover - needs a live account
        if self._conn is not None:
            return self._conn
        try:
            import snowflake.connector
        except ImportError:
            raise RuntimeError("pip install 'gtm-agents[snowflake]' (snowflake-connector-python)")
        kw = {k: os.environ.get(f"SNOWFLAKE_{k.upper()}") for k in
              ("account", "user", "role", "warehouse", "database", "schema")}
        kw = {k: v for k, v in kw.items() if v}
        key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
        if key_path:
            from cryptography.hazmat.primitives import serialization
            pw = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
            with open(key_path, "rb") as f:
                pkey = serialization.load_pem_private_key(f.read(), password=pw.encode() if pw else None)
            kw["private_key"] = pkey.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption())
        else:
            kw["password"] = os.environ.get("SNOWFLAKE_PASSWORD")
        self._conn = snowflake.connector.connect(session_parameters={"QUERY_TAG": "gtm-agents"}, **kw)
        return self._conn

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        body = check_read_only(sql)
        cur = self._connect().cursor()
        try:
            cur.execute(body, params or {})
            cols = [c[0].lower() for c in cur.description or []]
            return [dict(zip(cols, r)) for r in cur.fetchmany(self.max_rows)]
        finally:
            cur.close()

    def scalar(self, sql: str, params: dict | None = None) -> dict:
        """First row as {value, prior?}; columns other than value and prior are returned too."""
        rows = self.query(sql, params)
        return rows[0] if rows else {}


def get_warehouse():
    return Snowflake() if configured() else None
