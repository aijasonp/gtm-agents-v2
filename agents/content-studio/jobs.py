"""Content Studio scheduled jobs and the social_post executor (persistent edition)."""
from __future__ import annotations

import os
from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.approvals import executor

_CTX: dict = {}


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def weekly_content_ideas(ctx, now: datetime | None = None) -> dict:
    """Monday: post the 5 most mentioned themes from the last 7 days of call and deal insights as post topics."""
    ideas = _eng(ctx).content_ideas(ctx, now)
    if ideas:
        ctx.slack.post("*Content Studio: 5 post ideas from this week's calls*\n" + "\n".join(
            f"{i}. {x['topic']} ({x['mentions']} mentions)" for i, x in enumerate(ideas, 1))
            + "\nDraft one: ask for a LinkedIn post on the topic.")
    return {"ideas": ideas}


def register_executors(ctx):
    """social_post: send the approved post to GTM_SOCIAL_WEBHOOK (Buffer, Zapier, Make) or hand it back for manual posting."""
    _CTX["ctx"] = ctx

    @executor("social_post")
    def _social_post(payload: dict) -> dict:
        c = _CTX["ctx"]
        url = os.environ.get("GTM_SOCIAL_WEBHOOK")
        status = "sent"
        if url:
            import httpx
            r = httpx.post(url, json={"event": "social_post", **payload}, timeout=30)
            r.raise_for_status()
            res = {"ok": True, "status": r.status_code}
        else:
            status = "approved_manual"
            res = {"ok": True, "manual": True, "note": "No GTM_SOCIAL_WEBHOOK set; post the approved text by hand."}
        if payload.get("draft_id"):
            c.store.execute("UPDATE drafts SET status=? WHERE id=?", (status, payload["draft_id"]))
        return res
