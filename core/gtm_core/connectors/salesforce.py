"""Salesforce connector (OAuth access token on the customer's org)."""
from __future__ import annotations

import httpx

from .base import CRM

VERSION = "v61.0"


class Salesforce(CRM):
    name = "salesforce"

    def __init__(self, instance_url: str, token: str, client: httpx.Client | None = None):
        self.base = instance_url.rstrip("/") + f"/services/data/{VERSION}"
        self.http = client or httpx.Client(timeout=30, headers={"authorization": f"Bearer {token}"})

    def list_accounts(self, limit: int = 500) -> list[dict]:
        soql = ("SELECT Id, Name, Website, Industry, NumberOfEmployees, AnnualRevenue, BillingCountry "
                f"FROM Account ORDER BY LastModifiedDate DESC LIMIT {int(limit)}")
        r = self.http.get(self.base + "/query", params={"q": soql})
        r.raise_for_status()
        out = []
        for a in r.json().get("records", []):
            site = (a.get("Website") or "").replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            out.append({"id": site or f"sf-{a['Id']}", "crm_id": a["Id"], "name": a["Name"], "domain": site or None,
                        "industry": a.get("Industry"), "employees": a.get("NumberOfEmployees"),
                        "revenue": a.get("AnnualRevenue"), "country": a.get("BillingCountry")})
        return out

    def update_account(self, crm_id: str, fields: dict) -> dict:
        r = self.http.patch(self.base + f"/sobjects/Account/{crm_id}", json=fields)
        r.raise_for_status()
        return {"ok": True}

    def add_note(self, crm_id: str, body: str) -> dict:
        r = self.http.post(self.base + "/sobjects/Note", json={"ParentId": crm_id, "Title": "GTM agent", "Body": body})
        r.raise_for_status()
        return r.json()
