"""Follow-Through scheduled jobs."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def evaluate_triggers(ctx, now: datetime | None = None) -> dict:
    """Every 10 minutes: run the engagement triggers for everyone with new opens, clicks or replies.
    The HTTP intake also runs them on each event, so this sweep is the safety net."""
    res = _eng(ctx).evaluate_recent(ctx, now)
    return {"checked": res["checked"], "teed_up": res["teed_up"], "notified": res["notified"]}


def _cad(ctx):
    return load_module(ctx.manifest, "cadence")


def sweep_cadence(ctx, now: datetime | None = None) -> dict:
    """Every 15 minutes: start new motions, stop finished ones, advance on evidence, draft gaps for the AE to
    confirm, and escalate anything missed."""
    from gtm_core.executors import register_core_executors
    register_core_executors(ctx)
    res = _cad(ctx).sweep(ctx, now)
    return {**{k: v for k, v in res.items() if k != "escalated"}, "escalated": len(res["escalated"])}


def coverage_report(ctx, now: datetime | None = None) -> dict:
    """Weekdays 8:00: post the no-gaps check. Silent when there are no gaps."""
    res = _cad(ctx).coverage(ctx, now)
    if res["gaps"]:
        lines = [f"*Follow-up gaps*: {len(res['gaps'])} ({res['live']} live cadences, {res['awaiting_ae']} waiting on AEs)"]
        for g in res["gaps"][:15]:
            who = g.get("deal") or g.get("email")
            lines.append(f"- {g['type'].replace('_', ' ')}: {who} (owner {g.get('owner') or 'unassigned'}): {g['fix']}")
        ctx.slack.post("\n".join(lines))
    return {"gaps": len(res["gaps"]), "live": res["live"], "awaiting_ae": res["awaiting_ae"]}
