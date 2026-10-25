"""Event Campaigns MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def list_events(ctx) -> dict:
    """Events from config/events.yaml with date, type, place, capacity and who to invite."""
    evs = _eng(ctx).events(ctx)
    return {"count": len(evs), "events": [{k: str(v) if k == "date" else v for k, v in e.items()} for e in evs]}


def build_invite_list(ctx, event_id: str) -> dict:
    """Ranked accounts and contacts to invite (target tiers, event region, event personas), capped at capacity
    times the invite multiplier, plus every skipped account and why."""
    return _eng(ctx).build_invite_list(ctx, event_id)


def draft_invites(ctx, event_id: str, limit: int = 20) -> dict:
    """Draft invites for the top of the invite list and queue each as a send for approval (campaign = event id)."""
    return _eng(ctx).draft_invites(ctx, event_id, limit)


def import_attendees(ctx, event_id: str, file: str = "", rows: list | None = None) -> dict:
    """Load registrants from a CSV (name,email,company,title,attended) or rows: creates leads tagged with the event
    and adds an event_attended signal for each attendee at a known account."""
    return _eng(ctx).import_attendees(ctx, event_id, file, rows)


def event_report(ctx, event_id: str) -> dict:
    """Invited, registered, attended, no-shows, and meetings, opportunities and new pipeline at attending accounts."""
    return _eng(ctx).event_report(ctx, event_id)


TOOLS = {f.__name__: f for f in [list_events, build_invite_list, draft_invites, import_attendees, event_report]}
