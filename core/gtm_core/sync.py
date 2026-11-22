"""Read-only CRM sync into the customer's store: accounts, contacts, deals, deal stage history.

Deals are snapshotted on every sync so stage age, close-date slips and stage moves can be
computed for any CRM, even one that does not expose stage history. Where the CRM has stage history
(Salesforce OpportunityHistory) it is stored as well, so win/loss and stage conversion cover all history.

Deal sync is incremental after the first run: the CRM is asked only for records changed since the last
successful sync. `full=True` (or `gtm sync --full`) pulls everything again.
"""
from __future__ import annotations

import inspect

from . import personas
from .store import now_iso

STATE_DEALS = "sync:deals:last"
STATE_HISTORY = "sync:deal_history:last"


def _account_id_for(ctx, account_crm_id: str | None) -> str | None:
    if not account_crm_id:
        return None
    r = ctx.store.one("SELECT id FROM accounts WHERE crm_id=?", (account_crm_id,))
    return r["id"] if r else None


def _accepts(fn, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def sync_accounts(ctx, limit: int = 5000) -> dict:
    accts = ctx.crm.list_accounts(limit=limit)
    for a in accts:
        ctx.store.upsert_account(a)
    return {"accounts": len(accts)}


def sync_contacts(ctx, limit: int = 20000) -> dict:
    rows = ctx.crm.list_contacts(limit=limit)
    for c in rows:
        acct = _account_id_for(ctx, c.pop("account_crm_id", None))
        cls = personas.classify(c.get("title"))
        ctx.store.upsert("contacts", {**c, "account_id": acct, "seniority": cls["seniority"], "function": cls["function"]})
    return {"contacts": len(rows)}


def upsert_deal(ctx, deal: dict, now_iso_str: str | None = None) -> dict:
    """Merge a deal, track when it entered its current stage, and snapshot it."""
    ts = now_iso_str or now_iso()
    old = ctx.store.get("deals", deal["id"])
    if not deal.get("stage_entered_at"):
        if old and old.get("stage") == deal.get("stage") and old.get("stage_entered_at"):
            deal["stage_entered_at"] = old["stage_entered_at"]
        elif old and old.get("stage") != deal.get("stage"):
            deal["stage_entered_at"] = ts
        else:
            deal["stage_entered_at"] = deal.get("created_at") or ts
    deal.setdefault("status", "open")
    ctx.store.upsert("deals", deal)
    merged = ctx.store.get("deals", deal["id"])
    ctx.store.snapshot_deal(merged)
    return merged


def sync_deals(ctx, limit: int | None = None, full: bool = False) -> dict:
    """Every deal the CRM returns (open, won, lost). Incremental after the first full pull."""
    started = now_iso()
    since = None if full else ctx.store.get_state(STATE_DEALS)
    kw = {"limit": limit} if limit else {}
    if since and _accepts(ctx.crm.list_deals, "modified_since"):
        kw["modified_since"] = since
    if not limit and not _accepts(ctx.crm.list_deals, "modified_since"):
        kw["limit"] = 5000  # connectors without incremental sync keep their old cap
    rows = ctx.crm.list_deals(**kw)
    for d in rows:
        d["account_id"] = d.get("account_id") or _account_id_for(ctx, d.pop("account_crm_id", None))
        upsert_deal(ctx, d)
    ctx.store.set_state(STATE_DEALS, started)
    out = {"deals": len(rows), "deals_mode": "incremental" if "modified_since" in kw else "full"}
    out.update(sync_deal_history(ctx, full=full))
    notes = getattr(ctx.crm, "notes", None)
    if notes:
        out["notes"] = list(dict.fromkeys(notes))
    return out


def sync_deal_history(ctx, full: bool = False) -> dict:
    """CRM stage history (stage, amount and close-date changes), deduplicated on the CRM row id."""
    started = now_iso()
    since = None if full else ctx.store.get_state(STATE_HISTORY)
    try:
        rows = ctx.crm.list_deal_history(modified_since=since)
    except (AttributeError, NotImplementedError):
        return {}
    for h in rows:
        ctx.store.upsert("deal_stage_history", h)
    ctx.store.set_state(STATE_HISTORY, started)
    return {"deal_history": len(rows)} if rows else {}


def sync_all(ctx, full: bool = False) -> dict:
    out = {"crm": ctx.crm.name}
    for fn in (sync_accounts, sync_contacts):
        try:
            out.update(fn(ctx))
        except NotImplementedError:
            pass
    try:
        out.update(sync_deals(ctx, full=full))
    except NotImplementedError:
        pass
    return out
