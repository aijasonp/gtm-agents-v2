"""Event Campaigns scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _contact(lead: dict) -> dict:
    from gtm_core import personas
    return {"contact_id": lead.get("contact_id"), "name": lead.get("name"), "email": lead.get("email"),
            "title": lead.get("title"), "function": personas.function(lead.get("title"))}


def event_reminders(ctx, now: datetime | None = None) -> dict:
    """Daily: for events in the next 7 days, draft one reminder per registrant and queue it for approval."""
    eng = _eng(ctx)
    out = {}
    for ev in eng.upcoming(ctx, now, int(ctx.manifest.config.get("reminder_days", 7))):
        n = 0
        for lead in eng.event_leads(ctx, ev["id"]):
            r = eng.draft_one(ctx, ev, "event_reminder", _contact(lead), lead.get("company") or "", lead.get("account_id"),
                              lead["id"])
            n += 0 if r.get("skipped") else 1
        out[ev["id"]] = n
    if any(out.values()):
        ctx.slack.post("*Event Campaigns*: reminders queued for approval: "
                       + ", ".join(f"{k} {v}" for k, v in out.items() if v))
    return {"reminders": out}


def post_event_followups(ctx, now: datetime | None = None) -> dict:
    """Daily: after an event, draft a thank-you for attendees and a notes offer for registrants who missed it,
    queue them for approval, and post the event report once."""
    eng = _eng(ctx)
    out = {}
    for ev in eng.finished(ctx, now):
        att = missed = 0
        for lead in eng.event_leads(ctx, ev["id"]):
            went = lead.get("attended") in (True, "true", 1)
            kind = "event_followup_attended" if went else "event_followup_missed"
            r = eng.draft_one(ctx, ev, kind, _contact(lead), lead.get("company") or "", lead.get("account_id"), lead["id"])
            if not r.get("skipped"):
                att += went
                missed += not went
        out[ev["id"]] = {"attended": att, "missed": missed}
        key = f"event_report_posted:{ev['id']}"
        if not ctx.store.get_state(key):
            ctx.slack.post(eng.format_report(eng.event_report(ctx, ev["id"])))
            ctx.store.set_state(key, True)
    return {"followups": out}
