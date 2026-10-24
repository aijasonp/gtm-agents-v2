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


class NullCRM(CRM):
    """Used when no CRM is configured (demo, tests, drop-in edition)."""
    name = "none"

    def __init__(self):
        self.writes: list[dict] = []

    def list_accounts(self, limit: int = 500) -> list[dict]:
        return []

    def update_account(self, crm_id: str, fields: dict) -> dict:
        self.writes.append({"crm_id": crm_id, "fields": fields})
        return {"ok": True, "crm": "none"}

    def add_note(self, crm_id: str, body: str) -> dict:
        self.writes.append({"crm_id": crm_id, "note": body})
        return {"ok": True, "crm": "none"}


def get_crm(settings: Settings) -> CRM:
    if settings.crm == "hubspot" and settings.hubspot_token:
        from .hubspot import HubSpot
        return HubSpot(settings.hubspot_token)
    if settings.crm == "salesforce" and settings.salesforce_token and settings.salesforce_instance_url:
        from .salesforce import Salesforce
        return Salesforce(settings.salesforce_instance_url, settings.salesforce_token)
    return NullCRM()
