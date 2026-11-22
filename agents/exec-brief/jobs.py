"""Exec Brief scheduled jobs: snapshot, per-leader DMs, company snapshot, command center. Read only."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.connectors.slack import owner_slack_id
from gtm_core.connectors.snowflake import get_warehouse


def daily_briefs(ctx, now: datetime | None = None) -> dict:
    """Store today's snapshot, DM each leader their five numbers, post the company snapshot and command center."""
    eng = load_module(ctx.manifest, "engine")
    wh = get_warehouse()
    eng.save_snapshot(ctx, now, wh)
    cfg = eng.config(ctx)
    sent = []
    for role, r in (cfg.get("roles") or {}).items():
        b = eng.role_brief(ctx, role, now, wh)
        p = r.get("person") or {}
        uid = p.get("slack_id") or owner_slack_id(ctx, p.get("email") or p.get("name") or "")
        if uid:
            ctx.slack.dm(uid, eng.format_role(b), fallback_channel=cfg.get("channel") or None)
            sent.append(role)
    ctx.slack.post(eng.format_snapshot(eng.company_snapshot(ctx, now, wh)) + "\n\n" +
                   eng.format_heat(eng.heat_map(ctx, at=now)), channel=cfg.get("channel") or None)
    return {"briefs_sent": sent, "roles_without_recipient": [r for r in (cfg.get("roles") or {}) if r not in sent]}


def snapshot_only(ctx, now: datetime | None = None) -> dict:
    """Weekend snapshot so Monday's week-over-week has the same weekday to compare with."""
    eng = load_module(ctx.manifest, "engine")
    return {"saved": len(eng.save_snapshot(ctx, now, get_warehouse()))}
