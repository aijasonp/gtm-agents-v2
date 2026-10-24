"""Slack delivery: incoming webhook or bot token. Prints to stdout when neither is set."""
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
