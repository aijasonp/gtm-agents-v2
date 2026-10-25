"""Outbound delivery after approval: push an approved contact + copy into the customer's sequencer.

The agents never send email themselves. An approved `sequence_enroll` action hands the
contact and the approved copy to one of:

  webhook   -> POST JSON to GTM_SEQUENCER_WEBHOOK (Clay, n8n, Make, Zapier, Outreach or
               Apollo via their automation layer; the customer maps fields once)
  smartlead -> Smartlead campaign API (copy goes in custom fields the campaign template uses)
  none      -> recorded only (demo, tests, drop-in edition)
"""
from __future__ import annotations

import os

import httpx


class Sequencer:
    name = "none"

    def __init__(self):
        self.sent: list[dict] = []
        self.stopped: list[dict] = []

    def enroll(self, contact: dict, steps: list[dict], campaign: str | None = None, meta: dict | None = None) -> dict:
        self.sent.append({"contact": contact, "steps": steps, "campaign": campaign, "meta": meta or {}})
        return {"ok": True, "sequencer": self.name, "recorded": True}

    def stop(self, email: str, reason: str = "", meta: dict | None = None) -> dict:
        """Stop every active sequence for this person (reply, unsubscribe, bounce, meeting booked)."""
        self.stopped.append({"email": email, "reason": reason, "meta": meta or {}})
        return {"ok": True, "sequencer": self.name, "recorded": True}


class WebhookSequencer(Sequencer):
    name = "webhook"

    def __init__(self, url: str, secret: str | None = None, client: httpx.Client | None = None):
        super().__init__()
        self.url = url
        self.headers = {"x-gtm-secret": secret} if secret else {}
        self.http = client or httpx.Client(timeout=30)

    def enroll(self, contact: dict, steps: list[dict], campaign: str | None = None, meta: dict | None = None) -> dict:
        body = {"event": "sequence_enroll", "campaign": campaign, "contact": contact, "steps": steps, "meta": meta or {}}
        r = self.http.post(self.url, json=body, headers=self.headers)
        r.raise_for_status()
        return {"ok": True, "sequencer": self.name, "status": r.status_code}

    def stop(self, email: str, reason: str = "", meta: dict | None = None) -> dict:
        body = {"event": "sequence_stop", "email": email, "reason": reason, "meta": meta or {}}
        r = self.http.post(self.url, json=body, headers=self.headers)
        r.raise_for_status()
        return {"ok": True, "sequencer": self.name, "status": r.status_code}


class SmartleadSequencer(Sequencer):
    name = "smartlead"
    API = "https://server.smartlead.ai/api/v1"

    def __init__(self, api_key: str, default_campaign: str | None = None, client: httpx.Client | None = None):
        super().__init__()
        self.key = api_key
        self.default_campaign = default_campaign
        self.http = client or httpx.Client(timeout=30)

    def enroll(self, contact: dict, steps: list[dict], campaign: str | None = None, meta: dict | None = None) -> dict:
        cid = campaign or self.default_campaign
        if not cid:
            raise ValueError("Smartlead campaign id missing: set SMARTLEAD_CAMPAIGN_ID or pass campaign")
        name = (contact.get("name") or "").split(" ", 1)
        custom = {}
        for i, s in enumerate(steps, 1):
            custom[f"gtm_subject_{i}"] = s.get("subject", "")
            custom[f"gtm_body_{i}"] = s.get("body", "")
        lead = {"email": contact["email"], "first_name": name[0] if name else "",
                "last_name": name[1] if len(name) > 1 else "", "company_name": contact.get("company", ""),
                "custom_fields": custom}
        r = self.http.post(f"{self.API}/campaigns/{cid}/leads", params={"api_key": self.key},
                           json={"lead_list": [lead], "settings": {"ignore_global_block_list": False,
                                                                    "ignore_duplicate_leads_in_other_campaign": False}})
        r.raise_for_status()
        return {"ok": True, "sequencer": self.name, "campaign": cid, "response": r.json() if r.content else {}}


    def stop(self, email: str, reason: str = "", meta: dict | None = None) -> dict:
        # Smartlead stops a lead's sequence by lead id inside each campaign; without that id, do not guess.
        return {"ok": False, "sequencer": self.name, "manual": True,
                "note": f"Stop {email} in Smartlead (reason: {reason}); auto-stop needs the webhook sequencer"}


def get_sequencer() -> Sequencer:
    kind = os.environ.get("GTM_SEQUENCER", "none").lower()
    if kind == "webhook" and os.environ.get("GTM_SEQUENCER_WEBHOOK"):
        return WebhookSequencer(os.environ["GTM_SEQUENCER_WEBHOOK"], os.environ.get("GTM_SEQUENCER_SECRET"))
    if kind == "smartlead" and os.environ.get("SMARTLEAD_API_KEY"):
        return SmartleadSequencer(os.environ["SMARTLEAD_API_KEY"], os.environ.get("SMARTLEAD_CAMPAIGN_ID"))
    return Sequencer()
