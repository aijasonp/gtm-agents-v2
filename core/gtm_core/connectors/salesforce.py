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

    def _query(self, soql: str) -> list[dict]:
        r = self.http.get(self.base + "/query", params={"q": soql})
        r.raise_for_status()
        data = r.json()
        rows = data.get("records", [])
        while data.get("nextRecordsUrl"):
            r = self.http.get(self.base.split("/services/")[0] + data["nextRecordsUrl"])
            r.raise_for_status()
            data = r.json()
            rows.extend(data.get("records", []))
        return rows

    def list_accounts(self, limit: int = 500) -> list[dict]:
        soql = ("SELECT Id, Name, Website, Industry, NumberOfEmployees, AnnualRevenue, BillingCountry "
                f"FROM Account ORDER BY LastModifiedDate DESC LIMIT {int(limit)}")
        out = []
        for a in self._query(soql):
            site = (a.get("Website") or "").replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            out.append({"id": site or f"sf-{a['Id']}", "crm_id": a["Id"], "name": a["Name"], "domain": site or None,
                        "industry": a.get("Industry"), "employees": a.get("NumberOfEmployees"),
                        "revenue": a.get("AnnualRevenue"), "country": a.get("BillingCountry")})
        return out

    def list_deals(self, limit: int = 500) -> list[dict]:
        soql = ("SELECT Id, Name, AccountId, OwnerId, StageName, Amount, CloseDate, CreatedDate, LastActivityDate, "
                "NextStep, ForecastCategoryName, IsClosed, IsWon FROM Opportunity "
                f"WHERE IsClosed = false OR CloseDate = LAST_N_DAYS:90 ORDER BY LastModifiedDate DESC LIMIT {int(limit)}")
        out = []
        for o in self._query(soql):
            status = "open" if not o.get("IsClosed") else ("won" if o.get("IsWon") else "lost")
            out.append({"id": f"sf-opp-{o['Id']}", "crm_id": o["Id"], "account_crm_id": o.get("AccountId"),
                        "name": o.get("Name"), "owner": o.get("OwnerId"), "stage": o.get("StageName"), "status": status,
                        "amount": o.get("Amount"), "close_date": o.get("CloseDate"), "created_at": o.get("CreatedDate"),
                        "last_activity_at": o.get("LastActivityDate"), "next_step": o.get("NextStep"),
                        "forecast_category": o.get("ForecastCategoryName")})
        return out

    def list_contacts(self, limit: int = 2000) -> list[dict]:
        soql = f"SELECT Id, AccountId, Name, Email, Title, Phone FROM Contact ORDER BY LastModifiedDate DESC LIMIT {int(limit)}"
        return [{"id": c.get("Email") or f"sf-contact-{c['Id']}", "crm_id": c["Id"], "account_crm_id": c.get("AccountId"),
                 "name": c.get("Name"), "email": c.get("Email"), "title": c.get("Title"), "phone": c.get("Phone")}
                for c in self._query(soql)]

    def _patch(self, obj: str, crm_id: str, fields: dict) -> dict:
        r = self.http.patch(self.base + f"/sobjects/{obj}/{crm_id}", json=fields)
        r.raise_for_status()
        return {"ok": True}

    def _create(self, obj: str, fields: dict) -> dict:
        r = self.http.post(self.base + f"/sobjects/{obj}", json={k: v for k, v in fields.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def update_account(self, crm_id: str, fields: dict) -> dict:
        return self._patch("Account", crm_id, fields)

    def update_deal(self, crm_id: str, fields: dict) -> dict:
        return self._patch("Opportunity", crm_id, fields)

    def add_note(self, crm_id: str, body: str) -> dict:
        return self._create("Note", {"ParentId": crm_id, "Title": "GTM agent", "Body": body})

    def add_deal_note(self, crm_id: str, body: str) -> dict:
        return self._create("Note", {"ParentId": crm_id, "Title": "GTM agent", "Body": body})

    def create_task(self, subject: str, body: str = "", due_at: str | None = None, account_crm_id: str | None = None,
                    deal_crm_id: str | None = None, owner: str | None = None) -> dict:
        return self._create("Task", {"Subject": subject[:255], "Description": body,
                                     "ActivityDate": (due_at or "")[:10] or None,
                                     "WhatId": deal_crm_id or account_crm_id,
                                     "OwnerId": owner if owner and len(str(owner)) in (15, 18) else None})

    def create_contact(self, fields: dict, account_crm_id: str | None = None) -> dict:
        name = (fields.get("name") or "").rsplit(" ", 1)
        return self._create("Contact", {"FirstName": name[0] if len(name) > 1 else None,
                                        "LastName": name[-1] or fields.get("email", "Unknown"),
                                        "Email": fields.get("email"), "Title": fields.get("title"),
                                        "AccountId": account_crm_id})

    def update_contact(self, crm_id: str, fields: dict) -> dict:
        return self._patch("Contact", crm_id, fields)
