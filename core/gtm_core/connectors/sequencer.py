"""Outbound delivery after approval: push an approved contact + copy into the customer's sequencer.

The agents never send email themselves. An approved `sequence_enroll` action hands the
contact and the approved copy to one of:

  webhook   -> POST JSON to GTM_SEQUENCER_WEBHOOK (Clay, n8n, Make, Zapier, Outreach or
               Apollo via their automation layer; the customer maps fields once)
  smartlead -> Smartlead campaign API (copy goes in custom fields the campaign template uses)
  lemlist   -> Lemlist campaign API (copy goes in lead variables gtm_subject_N / gtm_body_N)
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

    def send_one(self, contact: dict, step: dict, meta: dict | None = None) -> dict:
        """One approved email, now: a pipeline follow-up the AE confirmed, or one held sequence step.
        Campaign-based sequencers send it through a one-step campaign (GTM_SEQUENCER_SINGLE_CAMPAIGN) whose
        template uses {{gtm_subject_1}} and {{gtm_body_1}}."""
        camp = (meta or {}).get("campaign") or os.environ.get("GTM_SEQUENCER_SINGLE_CAMPAIGN")
        return self.enroll(contact, [step], camp, {**(meta or {}), "single": True})


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

    def send_one(self, contact: dict, step: dict, meta: dict | None = None) -> dict:
        body = {"event": "send_one", "contact": contact, "step": step, "meta": meta or {}}
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


class LemlistSequencer(Sequencer):
    """Lemlist: HTTP Basic auth with an empty login and the API key as password.
    The campaign's email steps reference {{gtm_subject_1}}, {{gtm_body_1}} ... so the approved copy is
    what goes out. Engagement comes back through a Lemlist webhook pointed at POST /v1/email-events
    (Lemlist event names such as emailsOpened map automatically)."""
    name = "lemlist"
    API = "https://api.lemlist.com/api"

    def __init__(self, api_key: str, default_campaign: str | None = None, client: httpx.Client | None = None):
        super().__init__()
        self.auth = ("", api_key)
        self.default_campaign = default_campaign
        self.http = client or httpx.Client(timeout=30)

    def _campaign(self, campaign: str | None, meta: dict | None) -> str:
        cid = campaign or (meta or {}).get("campaign") or self.default_campaign
        if not cid:
            raise ValueError("Lemlist campaign id missing: set LEMLIST_CAMPAIGN_ID or pass campaign")
        return cid

    def enroll(self, contact: dict, steps: list[dict], campaign: str | None = None, meta: dict | None = None) -> dict:
        cid = self._campaign(campaign, meta)
        name = (contact.get("name") or "").split(" ", 1)
        body = {"firstName": name[0] if name else "", "lastName": name[1] if len(name) > 1 else "",
                "companyName": contact.get("company", "")}
        for i, s in enumerate(steps, 1):
            body[f"gtm_subject_{i}"] = s.get("subject", "")
            body[f"gtm_body_{i}"] = s.get("body", "")
        for k in ("draft_ids", "value_prop", "angle_key"):
            if (meta or {}).get(k) is not None:
                body[f"gtm_{k}"] = ",".join(map(str, meta[k])) if isinstance(meta[k], list) else str(meta[k])
        r = self.http.post(f"{self.API}/campaigns/{cid}/leads/{contact['email']}", json=body, auth=self.auth,
                           params={"deduplicate": "true"})
        r.raise_for_status()
        return {"ok": True, "sequencer": self.name, "campaign": cid, "response": r.json() if r.content else {}}

    def stop(self, email: str, reason: str = "", meta: dict | None = None) -> dict:
        try:
            cid = self._campaign(None, meta)
        except ValueError:
            return {"ok": False, "sequencer": self.name, "manual": True,
                    "note": f"Stop {email} in Lemlist (reason: {reason}); no campaign id to stop it in"}
        r = self.http.delete(f"{self.API}/campaigns/{cid}/leads/{email}", auth=self.auth)
        r.raise_for_status()
        return {"ok": True, "sequencer": self.name, "campaign": cid, "status": r.status_code}


def get_sequencer() -> Sequencer:
    kind = os.environ.get("GTM_SEQUENCER", "none").lower()
    if kind == "webhook" and os.environ.get("GTM_SEQUENCER_WEBHOOK"):
        return WebhookSequencer(os.environ["GTM_SEQUENCER_WEBHOOK"], os.environ.get("GTM_SEQUENCER_SECRET"))
    if kind == "lemlist" and os.environ.get("LEMLIST_API_KEY"):
        return LemlistSequencer(os.environ["LEMLIST_API_KEY"], os.environ.get("LEMLIST_CAMPAIGN_ID"))
    if kind == "smartlead" and os.environ.get("SMARTLEAD_API_KEY"):
        return SmartleadSequencer(os.environ["SMARTLEAD_API_KEY"], os.environ.get("SMARTLEAD_CAMPAIGN_ID"))
    return Sequencer()
