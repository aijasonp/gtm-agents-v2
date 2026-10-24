"""Append-only local audit log. Secrets are masked before anything is written."""
from __future__ import annotations

import json
import re

from .store import Store, now_iso

_SECRET_KEYS = re.compile(r"(?i)(token|secret|password|api[_-]?key|authorization)")
_SECRET_VALUES = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|xox[abposr]-[A-Za-z0-9-]+|pat-[a-z0-9-]{8,}|Bearer\s+\S+)")


def mask(obj):
    if isinstance(obj, dict):
        return {k: ("***" if _SECRET_KEYS.search(str(k)) else mask(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    if isinstance(obj, str):
        return _SECRET_VALUES.sub("***", obj)
    return obj


class Audit:
    def __init__(self, store: Store, agent: str = "core"):
        self.store = store
        self.agent = agent

    def log(self, event: str, **detail) -> None:
        self.store.insert("INSERT INTO audit_log (ts, agent, event, detail) VALUES (?,?,?,?)",
                          (now_iso(), self.agent, event, json.dumps(mask(detail), default=str)))

    def tail(self, n: int = 50) -> list[dict]:
        rows = self.store.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (n,))
        for r in rows:
            r["detail"] = json.loads(r["detail"] or "{}")
        return rows
