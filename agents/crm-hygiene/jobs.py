"""CRM Hygiene scheduled jobs and executors."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.approvals import executor


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def weekly_hygiene_report(ctx, now: datetime | None = None) -> dict:
    """Weekly: post counts of duplicates, orphan contacts, bounces and stale deals. Changes nothing."""
    eng = _eng(ctx)
    s = eng.summary(ctx, now)
    ctx.slack.post(eng.format_report(s, int(ctx.manifest.config.get("report_examples", 5))))
    return {k: len(v) for k, v in s.items()}


# ---- executors for approved actions ----
_CTX = {}


def register_executors(ctx):
    _CTX["ctx"] = ctx

    @executor("crm_merge")
    def _merge(payload: dict) -> dict:
        # The CRM connectors have no merge call, so a person merges in the CRM; we record it locally.
        c = _CTX["ctx"]
        s = payload["survivor"]
        losers = ", ".join(f"{l['name']} ({l.get('crm_id') or 'no CRM id'})" for l in payload.get("losers", []))
        c.slack.post(f":broom: Approved merge: in the CRM, merge {losers} into {s['name']} "
                     f"({s.get('crm_id') or 'no CRM id'}). Keep {s['name']}.")
        done = load_module(c.manifest, "engine").mark_merged(c, payload)
        return {"ok": True, "manual": True, "marked_merged": done}
