"""CRM Hygiene MCP tools. Read only, except propose_fix, which queues approvals."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def find_duplicate_accounts(ctx) -> dict:
    """Duplicate account groups: same normalized domain, or same name once Inc, LLC, Ltd and Corp are stripped.
    Each group names the survivor a merge would keep."""
    g = _eng(ctx).duplicate_accounts(ctx)
    return {"groups": len(g), "duplicates": g}


def find_duplicate_contacts(ctx) -> dict:
    """Duplicate contact groups: same email (any case), or same name at the same account."""
    g = _eng(ctx).duplicate_contacts(ctx)
    return {"groups": len(g), "duplicates": g}


def contacts_missing_account(ctx) -> dict:
    """Contacts with no account, and the account their work email domain matches. Personal email domains never match."""
    rows = _eng(ctx).missing_account(ctx)
    return {"count": len(rows), "matchable": sum(1 for r in rows if r.get("match")), "contacts": rows}


def bounced_contacts(ctx, request_reenrichment: bool = False) -> dict:
    """Contacts whose email bounced. request_reenrichment=True asks the Enrichment agent to find a new email
    (an internal handoff, not a CRM write)."""
    eng = _eng(ctx)
    if request_reenrichment:
        return eng.request_reenrichment(ctx)
    rows = eng.bounced(ctx)
    return {"count": len(rows), "contacts": rows}


def stale_stages(ctx) -> dict:
    """Open deals with a past close date, or no activity longer than the stage limit, with the proposed revision."""
    rows = _eng(ctx).stale(ctx)
    return {"count": len(rows), "deals": rows}


def propose_fix(ctx, kind: str, ids: list[str]) -> dict:
    """Queue fixes for human approval. kind: merge_accounts or merge_contacts (ids = the group),
    link_contact (contact ids), revise_deal (deal ids). Nothing changes until approved."""
    return _eng(ctx).propose_fix(ctx, kind, ids)


TOOLS = {f.__name__: f for f in [find_duplicate_accounts, find_duplicate_contacts, contacts_missing_account,
                                 bounced_contacts, stale_stages, propose_fix]}
