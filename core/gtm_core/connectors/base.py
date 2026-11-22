"""CRM interface. Reads are free; every write goes through the approval queue first."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Settings


class CRM(ABC):
    name = "crm"

    @abstractmethod
    def list_accounts(self, limit: int = 500) -> list[dict]:
        """Return accounts as dicts: id, name, domain, crm_id, industry, employees, revenue, country."""

    @abstractmethod
    def update_account(self, crm_id: str, fields: dict) -> dict:
        """Write fields onto the account record. Only called by an approved action."""

    @abstractmethod
    def add_note(self, crm_id: str, body: str) -> dict:
        """Attach a note to the account record. Only called by an approved action."""

    # ---- optional: deals, contacts, tasks. Connectors that lack them return [] / raise. ----
    def list_deals(self, limit: int = 500) -> list[dict]:
        """Open and recently closed deals: id, crm_id, account_id, name, owner, stage, status, amount,
        close_date, created_at, last_activity_at, next_step, forecast_category."""
        return []

    def list_deal_history(self, modified_since: str | None = None) -> list[dict]:
        """CRM stage history, oldest first: id, deal_id, stage, amount, close_date, forecast_category, changed_at.
        CRMs without it return []; the store's own sync snapshots still give stage moves."""
        return []

    def list_contacts(self, limit: int = 2000) -> list[dict]:
        """Contacts: id, crm_id, account_id, name, email, title."""
        return []

    def update_deal(self, crm_id: str, fields: dict) -> dict:
        raise NotImplementedError(f"{self.name}: update_deal not supported")

    def add_deal_note(self, crm_id: str, body: str) -> dict:
        raise NotImplementedError(f"{self.name}: add_deal_note not supported")

    def create_task(self, subject: str, body: str = "", due_at: str | None = None, account_crm_id: str | None = None,
                    deal_crm_id: str | None = None, owner: str | None = None) -> dict:
        raise NotImplementedError(f"{self.name}: create_task not supported")

    def create_contact(self, fields: dict, account_crm_id: str | None = None) -> dict:
        raise NotImplementedError(f"{self.name}: create_contact not supported")

    def update_contact(self, crm_id: str, fields: dict) -> dict:
        raise NotImplementedError(f"{self.name}: update_contact not supported")


class NullCRM(CRM):
    """Used when no CRM is configured (demo, tests, drop-in edition). Records writes in memory."""
    name = "none"

    def __init__(self):
        self.writes: list[dict] = []

    def _w(self, kind: str, **kw) -> dict:
        self.writes.append({"kind": kind, **kw})
        return {"ok": True, "crm": "none", "id": f"null-{len(self.writes)}"}

    def list_accounts(self, limit: int = 500) -> list[dict]:
        return []

    def update_account(self, crm_id: str, fields: dict) -> dict:
        return self._w("account_update", crm_id=crm_id, fields=fields)

    def add_note(self, crm_id: str, body: str) -> dict:
        return self._w("account_note", crm_id=crm_id, note=body)

    def update_deal(self, crm_id: str, fields: dict) -> dict:
        return self._w("deal_update", crm_id=crm_id, fields=fields)

    def add_deal_note(self, crm_id: str, body: str) -> dict:
        return self._w("deal_note", crm_id=crm_id, note=body)

    def create_task(self, subject: str, body: str = "", due_at: str | None = None, account_crm_id: str | None = None,
                    deal_crm_id: str | None = None, owner: str | None = None) -> dict:
        return self._w("task", subject=subject, body=body, due_at=due_at, account=account_crm_id, deal=deal_crm_id,
                       owner=owner)

    def create_contact(self, fields: dict, account_crm_id: str | None = None) -> dict:
        return self._w("contact", fields=fields, account=account_crm_id)

    def update_contact(self, crm_id: str, fields: dict) -> dict:
        return self._w("contact_update", crm_id=crm_id, fields=fields)


def get_crm(settings: Settings) -> CRM:
    if settings.crm == "hubspot" and settings.hubspot_token:
        from .hubspot import HubSpot
        return HubSpot(settings.hubspot_token)
    if settings.crm == "salesforce" and settings.salesforce_token and settings.salesforce_instance_url:
        from .salesforce import Salesforce
        return Salesforce(settings.salesforce_instance_url, settings.salesforce_token)
    return NullCRM()
