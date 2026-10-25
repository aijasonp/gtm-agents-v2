"""Lead Triage MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module
from gtm_core.importers import lead_id
from gtm_core.store import now_iso


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _find(ctx, lead: str) -> dict | None:
    return ctx.store.get("leads", lead) or next(iter(ctx.store.select("leads", "LOWER(email)=?", (lead.lower(),),
                                                                       order="received_at DESC")), None)


def triage_lead(ctx, lead: str) -> dict:
    """Qualify, route and draft for one lead (lead id or email). Queues the CRM task and the send for approval."""
    row = _find(ctx, lead)
    if not row:
        return {"error": f"lead '{lead}' not found; add it with add_lead"}
    if row.get("status") != "new":  # never queue a second send for the same lead
        return {**_eng(ctx).evaluate(ctx, row), "already_triaged": True, "status": row.get("status"),
                "note": "Approvals were queued when this lead was first triaged. See `gtm approvals lead-triage list`."}
    return _eng(ctx).process(ctx, row)


def list_leads(ctx, status: str = "new", limit: int = 25) -> dict:
    """Leads by status: new, routed, nurture, disqualified. Newest first."""
    rows = ctx.store.select("leads", "status=?", (status,), order="received_at DESC")[:limit]
    keep = ("id", "name", "email", "company", "title", "source", "received_at", "score", "tier", "owner", "sla_due", "flags")
    return {"count": len(rows), "leads": [{k: r.get(k) for k in keep} for r in rows]}


def add_lead(ctx, email: str, name: str = "", title: str = "", company: str = "", source: str = "manual",
             message: str = "", event: str = "", triage: bool = True) -> dict:
    """Add a lead by hand (or from another tool) and triage it right away."""
    row = {"email": email.lower(), "name": name, "title": title, "company": company, "source": source,
           "message": message, "event": event, "received_at": now_iso(), "status": "new",
           "domain": email.split("@", 1)[-1].lower()}
    row["id"] = lead_id(row)
    if ctx.store.get("leads", row["id"]):
        return {"duplicate": True, "lead_id": row["id"]}
    ctx.store.upsert("leads", row)
    return _eng(ctx).process(ctx, row) if triage else {"added": row["id"]}


def route_lead(ctx, lead: str) -> dict:
    """Preview score, tier, owner and reasons for a lead without writing anything."""
    row = _find(ctx, lead)
    if not row:
        return {"error": f"lead '{lead}' not found"}
    return _eng(ctx).evaluate(ctx, row)


def draft_follow_up(ctx, lead: str) -> dict:
    """Draft the first follow-up for a lead and score it. Nothing is queued or sent."""
    row = _find(ctx, lead)
    if not row:
        return {"error": f"lead '{lead}' not found"}
    eng = _eng(ctx)
    ev = eng.evaluate(ctx, row)
    if ev["active_pipeline"]:
        return {"skipped": "active pipeline: the deal owner should respond", "flags": ev["flags"]}
    return eng.draft(ctx, row, ev).as_dict()


TOOLS = {f.__name__: f for f in [triage_lead, list_leads, add_lead, route_lead, draft_follow_up]}
