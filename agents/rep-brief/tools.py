"""Rep Brief MCP tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _owner(ctx, owner: str) -> str | None:
    return _eng(ctx).find_owner(ctx, owner)


def my_brief(ctx, owner: str) -> dict:
    """The rep's brief now: do-next actions, replies, hot leads, top accounts with why-now and contacts, pipeline gaps."""
    name = _owner(ctx, owner)
    if not name:
        return {"error": f"'{owner}' is not on the team in config/company.yaml", "team": _eng(ctx).owner_names(ctx)}
    eng = _eng(ctx)
    b = eng.brief(ctx, name)
    return {**b, "text": eng.format_brief(b)}


def push_button(ctx, account: str, contact: str = "", owner: str = "") -> dict:
    """One call: account research, a gated first-touch draft, and the email, CRM task and dialer call queued for approval."""
    return _eng(ctx).push_button(ctx, account, contact or None, owner or None)


def top_accounts(ctx, owner: str, limit: int = 5) -> dict:
    """The rep's best accounts to work now, with the reason to write now and who to contact."""
    name = _owner(ctx, owner)
    if not name:
        return {"error": f"'{owner}' is not on the team"}
    rows = _eng(ctx).top_accounts(ctx, name, limit)
    return {"owner": name, "count": len(rows), "accounts": rows}


def pipeline_gaps(ctx, owner: str) -> dict:
    """Open pipeline against what is left of quota, plus deals with no next step, quiet deals and flagged deals."""
    name = _owner(ctx, owner)
    if not name:
        return {"error": f"'{owner}' is not on the team"}
    return _eng(ctx).pipeline_gaps(ctx, name)


def whats_new(ctx, owner: str, since_hours: int = 24) -> dict:
    """New signals on the rep's accounts, hot leads and replies in the last N hours."""
    name = _owner(ctx, owner)
    if not name:
        return {"error": f"'{owner}' is not on the team"}
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).replace(microsecond=0).isoformat()
    eng = _eng(ctx)
    return {"owner": name, "since": since, "signals": eng.new_signals(ctx, name, since),
            "hot_leads": eng.hot_leads(ctx, name), "replies": eng.replies_to_handle(ctx, name)}


TOOLS = {f.__name__: f for f in [my_brief, push_button, top_accounts, pipeline_gaps, whats_new]}
