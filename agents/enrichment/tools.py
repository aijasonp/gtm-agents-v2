"""Enrichment MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _contact(ctx, ref: str) -> dict | None:
    return ctx.store.get("contacts", ref) or ctx.store.contact_by_email(ref)


def enrich_contact(ctx, contact: str, fields: list[str] | None = None, force: bool = False) -> dict:
    """Run the waterfall for one contact (id or email). Default fields: email, phone, title, linkedin.
    Fills empty fields only (force replaces values from an earlier enrichment, never CRM or manual values).
    CRM writes are queued for approval."""
    c = _contact(ctx, contact)
    if not c:
        return {"error": f"contact '{contact}' not found; import it first"}
    bad = [f for f in (fields or []) if f not in _eng(ctx).PERSON_FIELDS]
    if bad:
        return {"error": f"unknown fields {bad}; use {_eng(ctx).PERSON_FIELDS}"}
    return _eng(ctx).enrich_contact(ctx, c, fields, force=force)


def enrich_account(ctx, account: str) -> dict:
    """Fill missing firmographics for an account and missing email, phone and title for its contacts."""
    a = ctx.store.account(account)
    if not a:
        return {"error": f"account '{account}' not found"}
    return _eng(ctx).enrich_account(ctx, a)


def waterfall_report(ctx, days: int = 30) -> dict:
    """Hit rate, spend and cost per hit by provider and field, with keep or cut recommendations for consolidating
    data tools."""
    return _eng(ctx).waterfall_report(ctx, days)


def coverage_report(ctx) -> dict:
    """Share of target contacts (Signal Scout A/B accounts and routed leads) with a verified email and a valid phone."""
    return _eng(ctx).coverage_report(ctx)


def push_to_clay(ctx, accounts: list[str] | None = None, limit: int = 50) -> dict:
    """Send accounts (ids or domains; default: those missing industry, employees or country) to the Clay table
    webhook for enrichment. Sends firmographic lookups only; results come back through import_clay or /v1/enrichment."""
    from gtm_core.connectors.clay import ClayTable
    clay = getattr(ctx, "clay", None) or ClayTable.from_env()
    if clay is None:
        return {"error": "set GTM_CLAY_WEBHOOK to the Clay table's webhook URL"}
    rows = [ctx.store.account(a) for a in accounts] if accounts else \
        [a for a in ctx.store.accounts() if not (a.get("industry") and a.get("employees") and a.get("country"))]
    rows = [{"domain": a.get("domain") or a["id"], "company_name": a.get("name"), "gtm_account_id": a["id"]}
            for a in rows if a][:limit]
    return {**clay.push(rows), "accounts": [r["domain"] for r in rows]}


def import_clay(ctx, file: str) -> dict:
    """Merge a Clay CSV export into accounts and contacts. Blank Clay cells never overwrite stored values."""
    from gtm_core.connectors.clay import import_csv
    try:
        return import_csv(ctx.store, file)
    except OSError as e:
        return {"error": str(e)}


TOOLS = {f.__name__: f for f in [enrich_contact, enrich_account, waterfall_report, coverage_report, push_to_clay,
                                 import_clay]}
