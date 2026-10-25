"""Reply Desk MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module
from gtm_core.store import now_iso


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def classify_reply(ctx, text: str, subject: str = "", from_email: str = "") -> dict:
    """Classify a reply without acting on it: class, category, confidence, the rule that fired, follow-up date."""
    c = _eng(ctx).classify(text, subject, from_email)
    return {k: v for k, v in c.items() if k != "clean_body"} | {"cleaned_text": c["clean_body"][:500]}


def add_reply(ctx, from_email: str, body: str, subject: str = "", from_name: str = "", received_at: str = "",
              campaign: str = "", thread_id: str = "", handle: bool = True) -> dict:
    """Store a reply (from a sequencer webhook, inbox or by hand) and handle it right away."""
    eng = _eng(ctx)
    rid = eng.ingest_row(ctx, {"from_email": from_email, "from_name": from_name, "body": body, "subject": subject,
                               "received_at": received_at or now_iso(), "campaign": campaign, "thread_id": thread_id})
    if rid is None:
        return {"duplicate_or_invalid": True}
    return eng.handle(ctx, rid) if handle else {"added": rid}


def handle_reply(ctx, reply_id: str) -> dict:
    """Classify and act on a stored reply. Safe to call twice: the second call does nothing."""
    if not _eng(ctx).get(ctx, reply_id):
        return {"error": f"reply '{reply_id}' not found"}
    return _eng(ctx).handle(ctx, reply_id)


def replies_needing_action(ctx, owner: str = "", days: int = 7) -> dict:
    """Interested buyers, objections, questions, referrals and unclear replies from the last N days."""
    eng = _eng(ctx)
    rows = [r for r in eng.select(ctx, "class IN ('positive','objection','question','referral','neutral','not_now')")
            if (not owner or (r.get("owner") or "").lower() == owner.lower())]
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = [r for r in rows if (r.get("received_at") or "") >= since]
    rows.sort(key=lambda r: (eng.ORDER.get(r["class"], 9), r.get("received_at") or ""))
    keep = ("id", "from_name", "from_email", "owner", "class", "category", "reason", "follow_up_at", "received_at", "status")
    return {"count": len(rows), "replies": [{k: r.get(k) for k in keep} | {"text": (r.get("clean_body") or "")[:300]} for r in rows]}


def opt_out(ctx, email: str, reason: str = "requested by hand") -> dict:
    """Opt a person out now: local do-not-contact immediately, sequence stop and CRM opt-out queued for approval."""
    eng = _eng(ctx)
    email = email.strip().lower()
    res = eng.resolve(ctx, email)
    c = res["contact"]
    stamp = now_iso()
    ctx.store.upsert("contacts", ({"id": c["id"]} if c else {"id": email, "email": email,
                                                           "account_id": (res["account"] or {}).get("id")})
                     | {"do_not_contact": True, "do_not_contact_at": stamp, "do_not_contact_reason": reason})
    approvals = [ctx.request_approval("sequence_stop", {"email": email, "reason": f"opt-out: {reason}"})]
    if c and c.get("crm_id"):
        f = ctx.manifest.config.get("crm_fields", {}).get("opt_out", "gtm_do_not_contact")
        approvals.append(ctx.request_approval("contact_update", {"crm_id": c["crm_id"], "fields": {f: True}}))
    return {"email": email, "do_not_contact": True, "approvals": approvals}


TOOLS = {f.__name__: f for f in [classify_reply, add_reply, handle_reply, replies_needing_action, opt_out]}
