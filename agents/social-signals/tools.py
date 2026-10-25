"""Social Signals MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module
from gtm_core.store import now_iso


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def add_engagement(ctx, engager_name: str, engagement_type: str, post_title: str = "", post_url: str = "",
                   platform: str = "linkedin", author: str = "company", engager_title: str = "",
                   engager_company: str = "", engager_profile_url: str = "", comment_text: str = "",
                   engaged_at: str = "") -> dict:
    """Record one engagement (like, comment, share, follow, view) and turn it into a signal if it resolves to an account."""
    row = {"platform": platform, "post_url": post_url, "post_title": post_title, "author": author,
           "engager_name": engager_name, "engager_title": engager_title, "engager_company": engager_company,
           "engager_profile_url": engager_profile_url, "engagement_type": engagement_type, "comment_text": comment_text,
           "engaged_at": engaged_at or now_iso()}
    out = _eng(ctx).ingest(ctx, [row])
    return {"stats": out["stats"], "result": out["results"][0] if out["results"] else None}


def engagement_for(ctx, account: str, days: int = 90) -> dict:
    """Everyone at an account who engaged with tracked content, newest first, with what they engaged with."""
    acct = ctx.store.account(account)
    if not acct:
        return {"error": f"account '{account}' not found"}
    rows = _eng(ctx).engagements(ctx, days, account_id=acct["id"])
    keep = ("name", "title", "type", "post_title", "author", "platform", "observed_at", "contact_id", "intent_terms",
            "competitors", "signal_type")
    return {"account": acct["name"], "count": len(rows), "engagements": [{k: r.get(k) for k in keep} for r in rows]}


def top_engagers(ctx, days: int = 30, limit: int = 20) -> dict:
    """People engaging most with tracked content, ranked by weighted engagement, with account tier and owner."""
    rows = _eng(ctx).top_engagers(ctx, days, limit)
    return {"days": days, "count": len(rows), "people": rows}


def creator_report(ctx, days: int = 7) -> dict:
    """Which creators and posts drive engagement from target accounts."""
    return _eng(ctx).creator_report(ctx, days)


def resolve_person(ctx, name: str = "", company: str = "", profile_url: str = "", email: str = "") -> dict:
    """Show how an engager would be matched to a contact and account, and how sure the match is. No writes."""
    r = _eng(ctx).resolve(ctx, name, company, profile_url, email)
    r.pop("contact", None)
    return r


TOOLS = {f.__name__: f for f in [add_engagement, engagement_for, top_engagers, creator_report, resolve_person]}
