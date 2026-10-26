"""Floqer sheet connector: push rows to a Floqer workflow sheet, run only those rows, read the results back.

Floqer's REST API (https://api.floqer.com/api/v1, bearer key):
  POST /workflows/{workflow}/sheets/{sheet}/rows        {"rows": [...], "run_after_add": "none"} -> data.row_ids
  POST /workflows/{workflow}/sheets/{sheet}/run         {"row_ids": [...]}  (only these rows, never run-all)
  POST /workflows/{workflow}/sheets/{sheet}/rows/list   {"page_size": 200, "page_no": n} -> data.rows
A row carries row_id, row_status (complete, has_failures, ...), inputs, and per-action results under
`outputs` or `cells.<action>.outputs`. Action ids differ per sheet, so the output map lives in config:

    outputs:
      phone: person_enrich_by_floqer_01lq.phone_number | personal_phone_waterfall_01gg.phone_number
      email: person_enrich_by_floqer_01lq.professional_email

`a | b` tries each path in order. Push is idempotent on the key input (email or domain), and every call is a
Floqer credit, so the connector pushes and runs only rows that are not already in the sheet.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

API = "https://api.floqer.com/api/v1"
DONE = {"complete", "completed", "has_failures", "failed"}


class FloqerError(RuntimeError):
    pass


def _dig(d: Any, path: str) -> Any:
    cur = d
    for p in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def pick(row: dict, spec: str) -> Any:
    """First non-empty value among `a.b | c.d` paths, looked up in outputs, then cells.<action>.outputs."""
    for path in [p.strip() for p in str(spec).split("|") if p.strip()]:
        head, _, rest = path.partition(".")
        for base in ((row.get("outputs") or {}).get(head), ((row.get("cells") or {}).get(head) or {}).get("outputs"),
                     (row.get("cells") or {}).get(head)):
            v = _dig(base, rest) if rest else base
            if v not in (None, "", [], {}):
                return v
    return None


class FloqerSheet:
    def __init__(self, api_key: str, workflow: str, sheet: str, client: httpx.Client | None = None):
        if not (api_key and workflow and sheet):
            raise FloqerError("Floqer needs an API key, a workflow id and a sheet id")
        self.key, self.wf, self.sheet = api_key, workflow, sheet
        self.http = client or httpx.Client(timeout=60)

    @classmethod
    def from_env(cls, cfg: dict | None = None, client=None) -> "FloqerSheet | None":
        cfg = cfg or {}
        key = os.environ.get(cfg.get("key_env", "FLOQER_API_KEY"))
        wf = os.environ.get(cfg.get("workflow_env", "FLOQER_WORKFLOW_ID")) or cfg.get("workflow")
        sheet = os.environ.get(cfg.get("sheet_env", "FLOQER_SHEET_ID")) or cfg.get("sheet")
        return cls(key, wf, sheet, client) if key and wf and sheet else None

    def _post(self, path: str, body: dict) -> dict:
        r = self.http.post(f"{API}/workflows/{self.wf}/sheets/{self.sheet}{path}", json=body,
                           headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code >= 400:
            raise FloqerError(f"Floqer {path} returned {r.status_code}: {r.text[:200]}")
        data = r.json() if r.content else {}
        if isinstance(data, dict) and data.get("status") not in (None, 200, 201):
            raise FloqerError(f"Floqer {path}: {str(data)[:200]}")
        return data

    def rows(self, page_size: int = 200, max_pages: int = 50) -> list[dict]:
        out = []
        for page in range(1, max_pages + 1):
            got = ((self._post("/rows/list", {"page_size": page_size, "page_no": page}).get("data") or {}).get("rows")) or []
            out += got
            if len(got) < page_size:
                break
        return out

    def push(self, rows: list[dict], key: str = "email", run: bool = True) -> dict:
        """Add rows not already in the sheet (matched on the `key` input) and run only those."""
        have = {str((r.get("inputs") or {}).get(key) or "").lower() for r in self.rows()}
        new = [r for r in rows if r.get(key) and str(r[key]).lower() not in have]
        ids: list = []
        if new:
            res = self._post("/rows", {"rows": new, "run_after_add": "none"})
            ids = (res.get("data") or {}).get("row_ids") or res.get("row_ids") or []
        if run and ids:
            self._post("/run", {"row_ids": ids})
        return {"pushed": len(new), "already_in_sheet": len(rows) - len(new), "row_ids": ids, "ran": bool(run and ids)}

    def results(self, row_ids: list, outputs: dict, key: str = "email") -> dict:
        """{done: [{key, status, fields...}], pending: [row_id, ...]} for these rows."""
        want = set(row_ids)
        done, pending = [], []
        for r in self.rows():
            if r.get("row_id") not in want:
                continue
            if (r.get("row_status") or "").lower() not in DONE:
                pending.append(r["row_id"])
                continue
            fields = {f: v for f, spec in outputs.items() if (v := pick(r, spec)) is not None}
            done.append({key: (r.get("inputs") or {}).get(key), "status": r.get("row_status"), **fields})
        return {"done": done, "pending": pending}
