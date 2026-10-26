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
