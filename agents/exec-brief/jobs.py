"""Exec Brief scheduled job (persistent edition). Read only: computes, posts to Slack, stores the snapshot."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def daily_exec_briefs(ctx, now: datetime | None = None) -> dict:
    """Five-number brief to each executive's DM, the company snapshot to the shared channel, and the command
    center page refreshed. Stores today's snapshot so tomorrow's run can show slips and changes."""
    r = load_module(ctx.manifest, "engine").run(ctx, now=now)
    return {"as_of": r["as_of"], "command_center": r["command_center"],
            "sent": {k: {kk: vv for kk, vv in v.items() if kk != "spec"} for k, v in r["sent"].items()}}
