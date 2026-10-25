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


def pull_transcripts(ctx, now: datetime | None = None, pullers: list | None = None) -> dict:
    """Pull new call transcripts from Gong, Fireflies or Fathom (whichever keys are set) into meetings.
    Starts from the last successful pull, or `pull_lookback_days` ago on the first run."""
    from datetime import timedelta, timezone

    from gtm_core.connectors import notetakers
    from gtm_core.pipeline import parse_dt
    now = now or datetime.now(timezone.utc)
    pullers = notetakers.from_env() if pullers is None else pullers
    if not pullers:
        return {"skipped": "no notetaker keys set (GONG_ACCESS_KEY, FIREFLIES_API_KEY or FATHOM_API_KEY)"}
    out = {}
    for p in pullers:
        key = f"notetaker_last_pull:{p.source}"
        since = parse_dt(ctx.store.get_state(key)) or now - timedelta(days=int(ctx.manifest.config.get("pull_lookback_days", 3)))
        try:
            res = notetakers.store_meetings(ctx.store, p.pull(since, now))
        except Exception as e:  # one vendor failing must not stop the others
            ctx.audit.log("notetaker.error", source=p.source, error=str(e)[:300])
            out[p.source] = {"error": str(e)[:200]}
            continue
        ctx.store.set_state(key, now.isoformat())
        out[p.source] = res
    return out
