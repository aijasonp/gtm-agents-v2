"""Seller Follow-Up MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module
from gtm_core.store import now_iso


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _deal(ctx, deal: str):
    d = ctx.store.get("deals", deal)
    if d:
        return d
    rows = ctx.store.select("deals", "LOWER(name) LIKE ? OR crm_id=?", (f"%{deal.lower()}%", deal))
    return rows[0] if rows else None


def whats_overdue(ctx, owner: str = "") -> dict:
    """Follow-up items for one seller (or everyone), highest priority first, after cooldowns and snoozes."""
    items = _eng(ctx).due_now(ctx, owner=owner or None)
    return {"owners": {k: v for k, v in items.items()}, "count": sum(len(v) for v in items.values())}


def draft_follow_up(ctx, deal: str) -> dict:
    """Draft a follow-up email for a deal from its last call and next step, and queue a send task for approval."""
    d = _deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found"}
    out = _eng(ctx).draft_deal_follow_up(ctx, d)
    if out["gate_passed"]:
        acct = ctx.store.account(d.get("account_id")) if d.get("account_id") else None
        rid = ctx.request_approval("crm_task", {
            "subject": f"Send follow-up to {out['to'] or 'buyer'}: {d.get('name')}",
            "body": f"Draft #{out['draft_id']}\n\nSubject: {out['subject']}\n\n{out['body']}",
            "due_at": now_iso()[:10], "deal_crm_id": d.get("crm_id"), "account_crm_id": (acct or {}).get("crm_id"),
            "owner": d.get("owner")}, summary=f"{d.get('owner')}: follow-up drafted for {d.get('name')}")
        out["approval"] = rid
    return out


def draft_recap(ctx, meeting: str) -> dict:
    """Draft the recap email, CRM note and next-step tasks for a meeting. All queued for approval."""
    return _eng(ctx).build_recap(ctx, meeting)


def log_next_step(ctx, deal: str, text: str, due_at: str = "") -> dict:
    """Record a deal's next step: updates the local record and queues the CRM task and field update for approval."""
    d = _deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found"}
    eng = _eng(ctx)
    from datetime import datetime, timezone
    due = due_at or eng.parse_due(text, datetime.now(timezone.utc), int(ctx.manifest.config.get("default_task_business_days", 2)))
    ctx.store.upsert("deals", {"id": d["id"], "next_step": text, "next_step_date": due})
    acct = ctx.store.account(d.get("account_id")) if d.get("account_id") else None
    ids = [ctx.request_approval("crm_task", {"subject": text[:200], "body": f"Next step on {d.get('name')}",
                                             "due_at": due, "deal_crm_id": d.get("crm_id"),
                                             "account_crm_id": (acct or {}).get("crm_id"), "owner": d.get("owner")})]
    if d.get("crm_id"):
        f = ctx.manifest.config.get("crm_fields", {})
        ids.append(ctx.request_approval("deal_update", {"crm_id": d["crm_id"], "fields": {
            f.get("next_step", "hs_next_step"): text[:250]}}))
    return {"deal": d.get("name"), "next_step": text, "due_at": due, "queued_for_approval": ids}


def snooze(ctx, item_id: str, days: int = 3) -> dict:
    """Hide a follow-up item (item_id from whats_overdue) for a number of days."""
    return {"item_id": item_id, "snoozed_until": _eng(ctx).snooze(ctx, item_id, int(days))}


TOOLS = {f.__name__: f for f in [whats_overdue, draft_follow_up, draft_recap, log_next_step, snooze]}
