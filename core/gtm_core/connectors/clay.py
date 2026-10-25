"""Clay: push rows into a Clay table, and read Clay results back.

Clay has no synchronous lookup API, so the loop is:
  1. `ClayTable.push(rows)` posts accounts or contacts to a Clay table's webhook source
     (GTM_CLAY_WEBHOOK, optional GTM_CLAY_SECRET sent as x-clay-webhook-auth).
  2. The Clay table enriches them, then an HTTP action column posts each finished row to
     POST /v1/enrichment on the runtime API, or the customer exports a CSV.
  3. `apply_rows(store, rows)` maps Clay columns onto accounts and contacts. Unknown columns
     are kept in attrs. Values Clay left blank never overwrite stored values.
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

import httpx

ACCOUNT_MAP = {"domain": "domain", "company_domain": "domain", "website": "domain", "company_name": "name",
               "company": "name", "name": "name", "industry": "industry", "employee_count": "employees",
               "employees": "employees", "headcount": "employees", "annual_revenue": "revenue", "revenue": "revenue",
               "country": "country", "hq_country": "country", "technologies": "tech", "tech_stack": "tech",
               "description": "description", "company_description": "description", "linkedin_url": "linkedin",
               "funding_stage": "funding_stage", "keywords": "keywords"}
CONTACT_MAP = {"email": "email", "work_email": "email", "full_name": "name", "person_name": "name",
               "job_title": "title", "title": "title", "linkedin_profile": "linkedin", "person_linkedin": "linkedin",
               "phone": "phone", "mobile_phone": "phone", "seniority": "seniority"}


def _key(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (k or "").strip().lower()).strip("_")


def _domain(v: str) -> str:
    v = (v or "").strip().lower()
    v = re.sub(r"^https?://", "", v).split("/")[0]
    return v.removeprefix("www.")


def _num(v):
    if v in (None, ""):
        return None
    s = re.sub(r"[,$\s]", "", str(v)).lower()
    mult = 1
    if s.endswith(("k", "m", "b")):
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1]]
        s = s[:-1]
    m = re.match(r"^(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?\+?$", s)
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    return (lo + hi) / 2 * mult  # a range like "201-500" becomes its midpoint


class ClayTable:
    def __init__(self, webhook: str, secret: str | None = None, client: httpx.Client | None = None):
        self.url = webhook
        self.headers = {"x-clay-webhook-auth": secret} if secret else {}
        self.http = client or httpx.Client(timeout=30)

    @classmethod
    def from_env(cls) -> "ClayTable | None":
        url = os.environ.get("GTM_CLAY_WEBHOOK")
        return cls(url, os.environ.get("GTM_CLAY_SECRET")) if url else None

    def push(self, rows: list[dict]) -> dict:
        sent = 0
        for r in rows:  # Clay webhook sources take one row per request
            self.http.post(self.url, json=r, headers=self.headers).raise_for_status()
            sent += 1
        return {"ok": True, "sent": sent}


def apply_rows(store, rows: list[dict]) -> dict:
    """Merge Clay rows into accounts and contacts. A row with an email also updates or creates the contact."""
    accounts = contacts = skipped = 0
    for raw in rows:
        r = {_key(k): v for k, v in raw.items() if v not in (None, "")}
        acct = {}
        for k, v in r.items():
            if k in ACCOUNT_MAP and ACCOUNT_MAP[k] not in acct:
                acct[ACCOUNT_MAP[k]] = v
        dom = _domain(acct.get("domain") or (r.get("email", "").split("@")[-1] if "@" in str(r.get("email", "")) else ""))
        if not dom:
            skipped += 1
            continue
        existing = store.account(dom) or {}
        if "name" in acct and "email" in r and "company_name" not in r and "company" not in r:
            acct.pop("name")  # a contact row's "name" is the person, not the company
        merged = {**existing, "id": existing.get("id") or dom, "domain": dom,
                  "name": acct.get("name") or existing.get("name") or dom}
        for f in ("industry", "country", "description", "linkedin", "funding_stage", "keywords"):
            if acct.get(f):
                merged[f] = acct[f]
        for f in ("employees", "revenue"):
            n = _num(acct.get(f))
            if n is not None:
                merged[f] = int(n) if f == "employees" else n
        if acct.get("tech"):
            t = acct["tech"]
            merged["tech"] = [x.strip().lower() for x in (t if isinstance(t, list) else str(t).split(",")) if x.strip()]
        merged["enriched_by"] = "clay"
        store.upsert_account(merged)
        accounts += 1
        email = str(r.get("email") or r.get("work_email") or "").strip().lower()
        if "@" in email:
            c = {CONTACT_MAP[k]: v for k, v in r.items() if k in CONTACT_MAP}
            if "name" not in c and r.get("name") and ("company_name" in r or "company" in r):
                c["name"] = r["name"]
            old = store.contact_by_email(email)
            store.upsert("contacts", {**c, "id": old["id"] if old else email, "email": email,
                                      "account_id": merged["id"], "enriched_by": "clay"})
            contacts += 1
    return {"accounts": accounts, "contacts": contacts, "skipped_no_domain": skipped}


def import_csv(store, path: str | Path) -> dict:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return apply_rows(store, list(csv.DictReader(f)))
