"""Meeting Intelligence scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from gtm_core.agents import load_module
from gtm_core.guardrails import StepCounter
from gtm_core.importers import import_meetings


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def ingest_inbox(ctx) -> dict:
    """Load transcript files (.txt/.vtt/.srt/.json, optional .meta.json) dropped in the inbox, then archive them."""
    inbox = Path(ctx.manifest.config.get("meeting_inbox", "data/meetings/inbox"))
    if not inbox.exists() or not any(inbox.iterdir()):
        return {"meetings": 0}
    res = import_meetings(ctx, inbox)
    done = inbox.parent / "processed"
    done.mkdir(parents=True, exist_ok=True)
    for f in list(inbox.iterdir()):
        if f.is_file():
            f.rename(done / f.name)
    return res


def process_meetings(ctx, now: datetime | None = None) -> dict:
    """Analyze every meeting that has a transcript and has not been processed; post one digest."""
    ingest = ingest_inbox(ctx)
    eng = _eng(ctx)
    todo = [m for m in ctx.store.select("meetings", "processed_at IS NULL", order="started_at")
            if (m.get("transcript") or "").strip()]
    results, blocks = [], []
    limit = int(ctx.manifest.config.get("max_per_run", 50))
    with StepCounter(limit=max(limit, ctx.settings.max_loop_steps)) as steps:
        for m in todo[:limit]:
            steps.tick(m["id"])
            r = eng.process(ctx, m, now)
            results.append(r)
            acct = ctx.store.account(m["account_id"]) if m.get("account_id") else None
            blocks.append(eng.digest_block(m, r["summary"], (acct or {}).get("name")))
    if blocks:
        ctx.slack.post(f"*Meeting Intelligence: {len(blocks)} call{'s' if len(blocks) != 1 else ''} processed*\n\n"
                       + "\n\n".join(blocks))
    return {"ingested": ingest.get("meetings", 0), "processed": len(results),
            "handoffs": sum(len(r["handoffs"]) for r in results),
            "approvals_queued": sum(len(r["approvals"]) for r in results)}
