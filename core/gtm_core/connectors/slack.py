"""Slack delivery: incoming webhook or bot token. Prints to stdout when neither is set.

Direct messages need the bot token: `chat.postMessage` with a user id as the channel opens the app's DM with
that person. With only a webhook, a DM falls back to the team channel so nothing is lost."""
from __future__ import annotations

import httpx

from ..config import Settings


class Slack:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.http = client or httpx.Client(timeout=20)
        self.sent: list[dict] = []

    @property
    def configured(self) -> bool:
        return bool(self.s.slack_webhook_url or self.s.slack_bot_token)

    def post(self, text: str, blocks: list | None = None, channel: str | None = None) -> dict:
        msg = {"text": text, **({"blocks": blocks} if blocks else {})}
        self.sent.append(msg)
        if self.s.slack_webhook_url:
            r = self.http.post(self.s.slack_webhook_url, json=msg)
            r.raise_for_status()
            return {"ok": True}
        if self.s.slack_bot_token:
            r = self.http.post("https://slack.com/api/chat.postMessage",
                               headers={"authorization": f"Bearer {self.s.slack_bot_token}"},
                               json={"channel": channel or self.s.slack_channel, **msg})
            r.raise_for_status()
            return r.json()
        print(text)
        return {"ok": True, "printed": True}

    def lookup_user_id(self, email: str) -> str | None:
        """Slack user id for an email (needs the users:read.email scope). None when unknown or not configured."""
        if not (self.s.slack_bot_token and email):
            return None
        try:
            r = self.http.get("https://slack.com/api/users.lookupByEmail", params={"email": email},
                              headers={"authorization": f"Bearer {self.s.slack_bot_token}"})
            d = r.json()
        except Exception:
            return None
        return (d.get("user") or {}).get("id") if d.get("ok") else None

    def dm(self, user_id: str | None, text: str, blocks: list | None = None, fallback_channel: str | None = None) -> dict:
        """DM one person when a user id and bot token exist; otherwise post to the fallback (or team) channel."""
        if user_id and (self.s.slack_bot_token or not self.configured):
            return {**self.post(text, blocks=blocks, channel=user_id), "dm": user_id}
        return {**self.post(text, blocks=blocks, channel=fallback_channel), "dm": None}


def owner_slack_id(ctx, owner: str) -> str | None:
    """Slack id for a team owner (name or email), from config/company.yaml `team.owners[].slack_id`, else looked up
    by email once and cached in the store."""
    from .. import profile
    o = (owner or "").strip().lower()
    if not o:
        return None
    for t in (profile.company(ctx).get("team") or {}).get("owners") or []:
        if o in ((t.get("name") or "").lower(), (t.get("email") or "").lower()):
            if t.get("slack_id"):
                return str(t["slack_id"])
            email = t.get("email")
            break
    else:
        email = owner if "@" in owner else None
    if not email:
        return None
    key = f"slack_id:{email.lower()}"
    cached = ctx.store.get_state(key)
    if cached:
        return cached
    uid = ctx.slack.lookup_user_id(email) if hasattr(ctx.slack, "lookup_user_id") else None
    if uid:
        ctx.store.set_state(key, uid)
    return uid


def send_to_owner(ctx, owner: str, text: str, blocks: list | None = None) -> dict:
    """Deliver an owner's message to their own DM; falls back to the team channel when no Slack id is known.
    Set GTM_SLACK_DM=0 to keep everything in the team channel."""
    import os
    uid = owner_slack_id(ctx, owner) if os.environ.get("GTM_SLACK_DM", "1") != "0" else None
    if uid and hasattr(ctx.slack, "dm"):
        return ctx.slack.dm(uid, text, blocks=blocks)
    return ctx.slack.post(text, blocks=blocks) or {}
