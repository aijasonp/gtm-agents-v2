"""Proposal Builder scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.approvals import executor

_CTX: dict = {}


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def expiring_quotes(ctx, now: datetime | None = None) -> dict:
    """Weekly: list quotes that expire in the next 7 days so the owner can extend or close them."""
    rows = _eng(ctx).expiring(ctx, int(ctx.manifest.config.get("expiry_warning_days", 7)), now)
    if rows:
        ctx.slack.post("*Quotes expiring this week*\n" + "\n".join(
            f"- {q['account']}: {q['quote_id']} ({q['status']}), TCV {q['currency']} {q['total_contract_value']}, "
            f"expires {q['expires']}" for q in rows))
    return {"expiring": len(rows), "quotes": [q["quote_id"] for q in rows]}


def register_executors(ctx):
    _CTX["ctx"] = ctx

    @executor("discount_approval")
    def _discount(payload: dict) -> dict:
        c = _CTX["ctx"]
        _eng(c).ensure_schema(c)
        c.store.execute("UPDATE quotes SET status=? WHERE id=? AND status='pending_approval'", ("ready", payload["quote_id"]))
        return {"ok": True, "quote_id": payload["quote_id"], "status": "ready"}

    @executor("proposal_send")
    def _send(payload: dict) -> dict:
        c = _CTX["ctx"]
        return _eng(c).mark_sent(c, payload)
