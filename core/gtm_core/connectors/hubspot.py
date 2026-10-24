"""HubSpot CRM connector (private app token on the customer's account)."""
from __future__ import annotations

import time

import httpx

from .base import CRM

API = "https://api.hubapi.com"
PROPS = ["name", "domain", "industry", "numberofemployees", "annualrevenue", "country"]


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

    def list_accounts(self, limit: int = 500) -> list[dict]:
        out, after = [], None
        while len(out) < limit:
            params = {"limit": min(100, limit - len(out)), "properties": ",".join(PROPS)}
            if after:
                params["after"] = after
            data = self._req("GET", "/crm/v3/objects/companies", params=params)
            for c in data.get("results", []):
                p = c.get("properties", {})
                out.append({
                    "id": p.get("domain") or f"hs-{c['id']}", "crm_id": c["id"], "name": p.get("name") or c["id"],
                    "domain": p.get("domain"), "industry": p.get("industry"),
                    "employees": int(float(p["numberofemployees"])) if p.get("numberofemployees") else None,
                    "revenue": float(p["annualrevenue"]) if p.get("annualrevenue") else None,
                    "country": p.get("country"),
                })
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return out

    def update_account(self, crm_id: str, fields: dict) -> dict:
        return self._req("PATCH", f"/crm/v3/objects/companies/{crm_id}", json={"properties": fields})

    def add_note(self, crm_id: str, body: str) -> dict:
        return self._req("POST", "/crm/v3/objects/notes", json={
            "properties": {"hs_note_body": body, "hs_timestamp": int(time.time() * 1000)},
            "associations": [{"to": {"id": crm_id},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 190}]}],
        })
