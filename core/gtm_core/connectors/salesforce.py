"""Salesforce connector (OAuth access token on the customer's org).

Opportunities: every open, won and lost deal (all history by default), with owner and account names, type, lead
source, probability and any custom fields the org has for loss reason and competitor (found by describing the
Opportunity object, so a field the org lacks is never queried). Stage history comes from OpportunityHistory.

Settings (env):
  SALESFORCE_OPP_SINCE_DAYS   only opportunities created or closed in the last N days (default: all history)
  SALESFORCE_OPP_FIELDS       extra Opportunity fields to pull, comma separated (e.g. Segment__c,ARR__c);
                              unknown names are skipped with a note, never sent to the API
  SALESFORCE_LOSS_REASON_FIELD / SALESFORCE_COMPETITOR_FIELD   override the auto-detected custom fields
"""
from __future__ import annotations

import os
import re

import httpx

from .base import CRM

VERSION = "v61.0"

OPP_FIELDS = ["Id", "Name", "AccountId", "Account.Name", "OwnerId", "Owner.Name", "Owner.Email", "StageName", "Amount",
              "CloseDate", "CreatedDate", "LastActivityDate", "LastModifiedDate", "NextStep", "ForecastCategoryName",
              "IsClosed", "IsWon", "Type", "LeadSource", "Probability"]
LOSS_RE = re.compile(r"(loss|lost).*reason|reason.*(loss|lost)|closed_?lost", re.I)
COMPETITOR_RE = re.compile(r"competitor", re.I)


def _since_clause(days: int | None) -> str:
    if not days:
        return ""
    return f" WHERE (CreatedDate = LAST_N_DAYS:{int(days)} OR CloseDate = LAST_N_DAYS:{int(days)} OR IsClosed = false)"


def _soql_dt(ts: str) -> str:
    """ISO timestamp to a SOQL datetime literal (UTC, no quotes)."""
    ts = ts.replace(" ", "T")
    ts = ts.split("+")[0].rstrip("Z")
    return ts[:19] + "Z"


class Salesforce(CRM):
    name = "salesforce"

    def __init__(self, instance_url: str, token: str, client: httpx.Client | None = None):
        self.base = instance_url.rstrip("/") + f"/services/data/{VERSION}"
        self.http = client or httpx.Client(timeout=60, headers={"authorization": f"Bearer {token}"})
        self._fields: dict[str, set[str]] = {}
        self.notes: list[str] = []

    # ---------- reads ----------
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

    def fields(self, sobject: str) -> set[str]:
        """Field API names on an object (describe, cached per connector)."""
        if sobject not in self._fields:
            r = self.http.get(self.base + f"/sobjects/{sobject}/describe")
            r.raise_for_status()
            self._fields[sobject] = {f["name"] for f in r.json().get("fields", [])}
        return self._fields[sobject]

    def opportunity_extras(self) -> dict[str, str]:
        """Custom Opportunity fields to pull: {store_key: api_name}. Loss reason and competitor are auto-detected."""
        try:
            have = self.fields("Opportunity")
        except httpx.HTTPError as e:
            self.notes.append(f"describe Opportunity failed ({e}); pulling standard fields only")
            return {}
        out: dict[str, str] = {}
        for key, env, rx in (("loss_reason", "SALESFORCE_LOSS_REASON_FIELD", LOSS_RE),
                             ("competitor", "SALESFORCE_COMPETITOR_FIELD", COMPETITOR_RE)):
            pinned = os.environ.get(env, "").strip()
            if pinned:
                if pinned in have:
                    out[key] = pinned
                else:
                    self.notes.append(f"{env}={pinned} is not an Opportunity field; skipped")
                continue
            hits = sorted(f for f in have if f.endswith("__c") and rx.search(f))
            if hits:
                out[key] = hits[0]
        for f in [x.strip() for x in os.environ.get("SALESFORCE_OPP_FIELDS", "").split(",") if x.strip()]:
            if f in have:
                out[f.removesuffix("__c").lower()] = f
            else:
                self.notes.append(f"SALESFORCE_OPP_FIELDS: {f} is not an Opportunity field; skipped")
        return out

    def list_accounts(self, limit: int | None = 500) -> list[dict]:
        lim = f" LIMIT {int(limit)}" if limit else ""
        soql = ("SELECT Id, Name, Website, Industry, NumberOfEmployees, AnnualRevenue, BillingCountry "
                f"FROM Account ORDER BY LastModifiedDate DESC{lim}")
        out = []
        for a in self._query(soql):
            site = (a.get("Website") or "").replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            out.append({"id": site or f"sf-{a['Id']}", "crm_id": a["Id"], "name": a["Name"], "domain": site or None,
                        "industry": a.get("Industry"), "employees": a.get("NumberOfEmployees"),
                        "revenue": a.get("AnnualRevenue"), "country": a.get("BillingCountry")})
        return out

    def list_deals(self, limit: int | None = None, modified_since: str | None = None) -> list[dict]:
        """Every opportunity: open, won and lost. modified_since (ISO) pulls only records changed after it."""
        extras = self.opportunity_extras()
        cols = OPP_FIELDS + sorted(set(extras.values()))
        days = os.environ.get("SALESFORCE_OPP_SINCE_DAYS", "").strip()
        where = _since_clause(int(days) if days.isdigit() else None)
        if modified_since:
            cond = f"LastModifiedDate > {_soql_dt(modified_since)}"
            where = f"{where} AND {cond}" if where else f" WHERE {cond}"
        lim = f" LIMIT {int(limit)}" if limit else ""
        soql = f"SELECT {', '.join(cols)} FROM Opportunity{where} ORDER BY LastModifiedDate DESC{lim}"
        return [self._deal(o, extras) for o in self._query(soql)]

    @staticmethod
    def _deal(o: dict, extras: dict[str, str]) -> dict:
        status = "open" if not o.get("IsClosed") else ("won" if o.get("IsWon") else "lost")
        owner, acct = o.get("Owner") or {}, o.get("Account") or {}
        d = {"id": f"sf-opp-{o['Id']}", "crm_id": o["Id"], "account_crm_id": o.get("AccountId"),
             "name": o.get("Name"), "owner": owner.get("Name") or o.get("OwnerId"), "stage": o.get("StageName"),
             "status": status, "amount": o.get("Amount"), "close_date": o.get("CloseDate"),
             "created_at": o.get("CreatedDate"), "last_activity_at": o.get("LastActivityDate"),
             "next_step": o.get("NextStep"), "forecast_category": o.get("ForecastCategoryName"),
             # extra keys land in the deal's attrs
             "owner_crm_id": o.get("OwnerId"), "owner_email": owner.get("Email"), "account_name": acct.get("Name"),
             "type": o.get("Type"), "lead_source": o.get("LeadSource"), "probability": o.get("Probability"),
             "crm_modified_at": o.get("LastModifiedDate")}
        for key, api in extras.items():
            d[key] = o.get(api)
        return d

    def list_deal_history(self, modified_since: str | None = None) -> list[dict]:
        """Stage, amount and close-date changes from OpportunityHistory, oldest first."""
        where = f" WHERE CreatedDate > {_soql_dt(modified_since)}" if modified_since else ""
        soql = ("SELECT Id, OpportunityId, StageName, Amount, CloseDate, ForecastCategory, Probability, CreatedDate "
                f"FROM OpportunityHistory{where} ORDER BY CreatedDate ASC")
        return [{"id": f"sf-oh-{h['Id']}", "deal_id": f"sf-opp-{h['OpportunityId']}", "stage": h.get("StageName"),
                 "amount": h.get("Amount"), "close_date": h.get("CloseDate"),
                 "forecast_category": h.get("ForecastCategory"), "probability": h.get("Probability"),
                 "changed_at": h.get("CreatedDate")} for h in self._query(soql)]

    def list_contacts(self, limit: int | None = 2000) -> list[dict]:
        lim = f" LIMIT {int(limit)}" if limit else ""
        soql = f"SELECT Id, AccountId, Name, Email, Title, Phone FROM Contact ORDER BY LastModifiedDate DESC{lim}"
        return [{"id": c.get("Email") or f"sf-contact-{c['Id']}", "crm_id": c["Id"], "account_crm_id": c.get("AccountId"),
                 "name": c.get("Name"), "email": c.get("Email"), "title": c.get("Title"), "phone": c.get("Phone")}
                for c in self._query(soql)]

    # ---------- writes (approved actions only) ----------
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
