"""ICP Outbound MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _acct(ctx, account: str):
    return ctx.store.account(account)


def build_target_list(ctx, limit: int = 25) -> dict:
    """Ranked outbound targets with why-now and contacts, plus every skipped account and the reason."""
    return _eng(ctx).build_list(ctx, limit=limit)


def why_now(ctx, account: str) -> dict:
    """The reason to reach out now: freshest mentionable signal, timing-only signals, and any conflicts."""
    a = _acct(ctx, account)
    if not a:
        return {"error": f"account '{account}' not found"}
    eng = _eng(ctx)
    return {"account": a["name"], **eng.angle(ctx, a), "conflicts": eng.conflicts(ctx, a)}


def pick_contacts(ctx, account: str) -> dict:
    """Up to 3 buyer or champion contacts at the account, most senior first."""
    a = _acct(ctx, account)
    if not a:
        return {"error": f"account '{account}' not found"}
    picks = _eng(ctx).pick_contacts(ctx, a)
    return {"account": a["name"], "contacts": picks, "flag": None if picks else "no buyer contact found"}


def draft_sequence(ctx, account: str, contact: str = "") -> dict:
    """Draft a 3-step sequence for one contact (email or id; default: top pick) and queue it for approval."""
    a = _acct(ctx, account)
    if not a:
        return {"error": f"account '{account}' not found"}
    eng = _eng(ctx)
    picks = eng.pick_contacts(ctx, a)
    if contact:
        c = next((p for p in picks if contact.lower() in (p["email"], p["contact_id"].lower())), None)
        if c is None:
            row = ctx.store.contact_by_email(contact) or ctx.store.get("contacts", contact)
            if not row or not row.get("email"):
                return {"error": f"contact '{contact}' not found"}
            from gtm_core import personas
            cls = personas.classify(row.get("title"))
            c = {"contact_id": row["id"], "name": row.get("name"), "email": row["email"], "title": row.get("title"),
                 "function": cls["function"], "seniority": cls["seniority"], "role": "manual"}
    elif picks:
        c = picks[0]
    else:
        return {"error": "no buyer contact found at this account"}
    return eng.draft_sequence(ctx, a, c)


def check_conflicts(ctx, account: str) -> dict:
    """Is it safe to prospect this account? Lists open deals, recent touches, ICP and do-not-contact problems."""
    a = _acct(ctx, account)
    if not a:
        return {"error": f"account '{account}' not found"}
    why = _eng(ctx).conflicts(ctx, a)
    return {"account": a["name"], "clear": not why, "reasons": why}


TOOLS = {f.__name__: f for f in [build_target_list, why_now, pick_contacts, draft_sequence, check_conflicts]}
