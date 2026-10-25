"""Read-only CRM sync into the customer's store: accounts, contacts, deals.

Deals are snapshotted on every sync so stage age, close-date slips and stage moves can be
computed for any CRM, even one that does not expose stage history.
"""
from __future__ import annotations

from . import personas
from .store import now_iso


def _account_id_for(ctx, account_crm_id: str | None) -> str | None:
    if not account_crm_id:
        return None
    r = ctx.store.one("SELECT id FROM accounts WHERE crm_id=?", (account_crm_id,))
    return r["id"] if r else None


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


def sync_deals(ctx, limit: int = 5000) -> dict:
    rows = ctx.crm.list_deals(limit=limit)
    for d in rows:
        d["account_id"] = d.get("account_id") or _account_id_for(ctx, d.pop("account_crm_id", None))
        upsert_deal(ctx, d)
    return {"deals": len(rows)}


def sync_all(ctx) -> dict:
    out = {"crm": ctx.crm.name}
    for fn in (sync_accounts, sync_contacts, sync_deals):
        try:
            out.update(fn(ctx))
        except NotImplementedError:
            pass
    return out
