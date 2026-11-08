"""Read-only Snowflake reader for agents that compute from the warehouse.

Credentials come from the environment, never from config files:
  SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_ROLE (use a read-only role),
  SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA (optional),
  and either SNOWFLAKE_PRIVATE_KEY_PATH (key-pair auth, preferred; SNOWFLAKE_PRIVATE_KEY_PASSPHRASE if encrypted)
  or SNOWFLAKE_PASSWORD.
Install with `pip install -e ".[warehouse]"`.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from decimal import Decimal

WRITE_SQL = re.compile(r"^\s*(insert|update|delete|merge|create|drop|alter|truncate|grant|revoke|copy|put|remove)\b",
                       re.IGNORECASE | re.MULTILINE)


class SnowflakeError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("SNOWFLAKE_ACCOUNT") and os.environ.get("SNOWFLAKE_USER"))


def _private_key():
    path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    if not path:
        return None
    from cryptography.hazmat.primitives import serialization
    pw = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=pw.encode() if pw else None)
    return key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def connect():
    if not configured():
        raise SnowflakeError("Snowflake is not configured: set SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER")
    try:
        import snowflake.connector
    except ImportError as e:
        raise SnowflakeError('snowflake-connector-python is not installed: pip install -e ".[warehouse]"') from e
    kw = {k: os.environ[f"SNOWFLAKE_{k.upper()}"] for k in ("account", "user", "warehouse", "role", "database", "schema")
          if os.environ.get(f"SNOWFLAKE_{k.upper()}")}
    pk = _private_key()
    if pk:
        kw["private_key"] = pk
    elif os.environ.get("SNOWFLAKE_PASSWORD"):
        kw["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    else:
        raise SnowflakeError("set SNOWFLAKE_PRIVATE_KEY_PATH or SNOWFLAKE_PASSWORD")
    return snowflake.connector.connect(client_session_keep_alive=False, **kw)


def _clean(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def query(sql: str, params: dict | None = None, conn=None) -> list[dict]:
    """Run one SELECT and return rows as dicts with lowercase keys. Refuses anything that writes."""
    if WRITE_SQL.search(sql or ""):
        raise SnowflakeError("only read queries are allowed")
    own = conn is None
    conn = conn or connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql, params or {})
            cols = [c[0].lower() for c in cur.description]
            return [{k: _clean(v) for k, v in zip(cols, row)} for row in cur.fetchall()]
        finally:
            cur.close()
    finally:
        if own:
            conn.close()


def query_many(queries: dict[str, str]) -> dict[str, list[dict]]:
    """Run several named SELECTs on one connection. Empty queries return no rows."""
    todo = {k: v for k, v in queries.items() if (v or "").strip()}
    out = {k: [] for k in queries}
    if not todo:
        return out
    conn = connect()
    try:
        for name, sql in todo.items():
            out[name] = query(sql, conn=conn)
    finally:
        conn.close()
    return out
