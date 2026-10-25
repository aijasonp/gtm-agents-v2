"""Dialer delivery after approval: queue a call task for a rep (Nooks, Orum, Aircall, Outreach calls...).

  webhook -> POST JSON to GTM_DIALER_WEBHOOK; the customer maps it into their dialer once
  none    -> recorded only (demo, tests)
"""
from __future__ import annotations

import os

import httpx


class Dialer:
    name = "none"

    def __init__(self):
        self.queued: list[dict] = []

    def enqueue(self, contact: dict, owner: str | None = None, script: str = "", meta: dict | None = None) -> dict:
        self.queued.append({"contact": contact, "owner": owner, "script": script, "meta": meta or {}})
        return {"ok": True, "dialer": self.name, "recorded": True}


class WebhookDialer(Dialer):
    name = "webhook"

    def __init__(self, url: str, secret: str | None = None, client: httpx.Client | None = None):
        super().__init__()
        self.url = url
        self.headers = {"x-gtm-secret": secret} if secret else {}
        self.http = client or httpx.Client(timeout=30)

    def enqueue(self, contact: dict, owner: str | None = None, script: str = "", meta: dict | None = None) -> dict:
        r = self.http.post(self.url, headers=self.headers, json={"event": "dialer_enqueue", "contact": contact,
                                                                 "owner": owner, "script": script, "meta": meta or {}})
        r.raise_for_status()
        return {"ok": True, "dialer": self.name, "status": r.status_code}


def get_dialer() -> Dialer:
    if os.environ.get("GTM_DIALER", "none").lower() == "webhook" and os.environ.get("GTM_DIALER_WEBHOOK"):
        return WebhookDialer(os.environ["GTM_DIALER_WEBHOOK"], os.environ.get("GTM_DIALER_SECRET"))
    return Dialer()
