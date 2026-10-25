"""HubSpot CRM connector (private app token on the customer's account).

Scopes needed: crm.objects.companies.read/write, crm.objects.deals.read/write,
crm.objects.contacts.read/write, crm.objects.notes (via companies/deals write) and tasks.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from .base import CRM

API = "https://api.hubapi.com"
PROPS = ["name", "domain", "industry", "numberofemployees", "annualrevenue", "country"]
DEAL_PROPS = ["dealname", "amount", "dealstage", "closedate", "hubspot_owner_id", "createdate", "hs_next_step",
              "notes_last_updated", "hs_lastmodifieddate", "hs_forecast_category", "hs_is_closed", "hs_is_closed_won"]
CONTACT_PROPS = ["email", "firstname", "lastname", "jobtitle", "phone", "hs_linkedin_url"]
# HubSpot-defined association type ids
NOTE_TO_COMPANY, NOTE_TO_DEAL, TASK_TO_COMPANY, TASK_TO_DEAL, CONTACT_TO_COMPANY = 190, 214, 192, 216, 279


def _ms(iso: str | None) -> int:
    if not iso:
        return int(time.time() * 1000)
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


class HubSpot(CRM):
    name = "hubspot"

    def __init__(self, token: str, client: httpx.Client | None = None):
        self.http = client or httpx.Client(timeout=30, headers={"authorization": f"Bearer {token}"})

    def _req(self, method: str, path: str, **kw) -> dict:
        for attempt in range(4):
            r = self.http.request(method, API + path, **kw)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("retry-after", 2 ** attempt)))
                continue
            r.raise_for_status()
            return r.json() if r.content else {}
        r.raise_for_status()
        return {}

    def _page(self, path: str, props: list[str], limit: int, assoc: str | None = None) -> list[dict]:
        out, after = [], None
        while len(out) < limit:
            params = {"limit": min(100, limit - len(out)), "properties": ",".join(props)}
            if assoc:
                params["associations"] = assoc
            if after:
                params["after"] = after
            data = self._req("GET", path, params=params)
            out.extend(data.get("results", []))
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return out

    @staticmethod
    def _first_company(obj: dict) -> str | None:
        res = obj.get("associations", {}).get("companies", {}).get("results", [])
        return res[0]["id"] if res else None

    def list_accounts(self, limit: int = 500) -> list[dict]:
        out = []
        for c in self._page("/crm/v3/objects/companies", PROPS, limit):
            p = c.get("properties", {})
            out.append({
                "id": p.get("domain") or f"hs-{c['id']}", "crm_id": c["id"], "name": p.get("name") or c["id"],
                "domain": p.get("domain"), "industry": p.get("industry"),
                "employees": int(float(p["numberofemployees"])) if p.get("numberofemployees") else None,
                "revenue": float(p["annualrevenue"]) if p.get("annualrevenue") else None,
                "country": p.get("country"),
            })
        return out

    def list_deals(self, limit: int = 500) -> list[dict]:
        out = []
        for d in self._page("/crm/v3/objects/deals", DEAL_PROPS, limit, assoc="companies"):
            p = d.get("properties", {})
            status = "open"
            if p.get("hs_is_closed") == "true":
                status = "won" if p.get("hs_is_closed_won") == "true" else "lost"
            comp = self._first_company(d)
            out.append({
                "id": f"hs-deal-{d['id']}", "crm_id": d["id"], "account_crm_id": comp, "name": p.get("dealname"),
                "owner": p.get("hubspot_owner_id"), "stage": p.get("dealstage"), "status": status,
                "amount": float(p["amount"]) if p.get("amount") else None,
                "close_date": (p.get("closedate") or "")[:10] or None, "created_at": p.get("createdate"),
                "last_activity_at": p.get("notes_last_updated") or p.get("hs_lastmodifieddate"),
                "next_step": p.get("hs_next_step"), "forecast_category": p.get("hs_forecast_category"),
            })
        return out

    def list_contacts(self, limit: int = 2000) -> list[dict]:
        out = []
        for c in self._page("/crm/v3/objects/contacts", CONTACT_PROPS, limit, assoc="companies"):
            p = c.get("properties", {})
            name = " ".join(x for x in [p.get("firstname"), p.get("lastname")] if x)
            out.append({"id": p.get("email") or f"hs-contact-{c['id']}", "crm_id": c["id"],
                        "account_crm_id": self._first_company(c), "name": name or None, "email": p.get("email"),
                        "title": p.get("jobtitle"), "phone": p.get("phone"), "linkedin": p.get("hs_linkedin_url")})
        return out

    def update_account(self, crm_id: str, fields: dict) -> dict:
        return self._req("PATCH", f"/crm/v3/objects/companies/{crm_id}", json={"properties": fields})

    def update_deal(self, crm_id: str, fields: dict) -> dict:
        return self._req("PATCH", f"/crm/v3/objects/deals/{crm_id}", json={"properties": fields})

    def _note(self, to_id: str, type_id: int, body: str) -> dict:
        return self._req("POST", "/crm/v3/objects/notes", json={
            "properties": {"hs_note_body": body, "hs_timestamp": _ms(None)},
            "associations": [{"to": {"id": to_id},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}]}],
        })

    def add_note(self, crm_id: str, body: str) -> dict:
        return self._note(crm_id, NOTE_TO_COMPANY, body)

    def add_deal_note(self, crm_id: str, body: str) -> dict:
        return self._note(crm_id, NOTE_TO_DEAL, body)

    def create_task(self, subject: str, body: str = "", due_at: str | None = None, account_crm_id: str | None = None,
                    deal_crm_id: str | None = None, owner: str | None = None) -> dict:
        props = {"hs_task_subject": subject, "hs_task_body": body, "hs_timestamp": _ms(due_at),
                 "hs_task_status": "NOT_STARTED"}
        if owner and str(owner).isdigit():
            props["hubspot_owner_id"] = owner
        assoc = []
        if deal_crm_id:
            assoc.append({"to": {"id": deal_crm_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                                                "associationTypeId": TASK_TO_DEAL}]})
        if account_crm_id:
            assoc.append({"to": {"id": account_crm_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                                                   "associationTypeId": TASK_TO_COMPANY}]})
        return self._req("POST", "/crm/v3/objects/tasks", json={"properties": props, "associations": assoc})

    def create_contact(self, fields: dict, account_crm_id: str | None = None) -> dict:
        name = (fields.get("name") or "").split(" ", 1)
        props = {"email": fields.get("email"), "firstname": name[0] if name and name[0] else None,
                 "lastname": name[1] if len(name) > 1 else None, "jobtitle": fields.get("title")}
        body = {"properties": {k: v for k, v in props.items() if v}}
        if account_crm_id:
            body["associations"] = [{"to": {"id": account_crm_id}, "types": [
                {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": CONTACT_TO_COMPANY}]}]
        return self._req("POST", "/crm/v3/objects/contacts", json=body)

    def update_contact(self, crm_id: str, fields: dict) -> dict:
        return self._req("PATCH", f"/crm/v3/objects/contacts/{crm_id}", json={"properties": fields})
