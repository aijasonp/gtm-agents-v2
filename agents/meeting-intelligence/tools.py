"""Meeting Intelligence MCP tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def analyze_call(ctx, meeting: str) -> dict:
    """Analyze a call: pass a meeting id/title, or paste the raw transcript text. Read-only."""
    eng = _eng(ctx)
    if eng.looks_like_transcript(meeting):
        a = eng.analyze_text(ctx, meeting)
        return {"analysis": a, "summary": eng.summarize(ctx, {"id": "pasted", "transcript": meeting}, a)}
    m = eng.find_meeting(ctx, meeting)
    if not m:
        return {"error": f"meeting '{meeting}' not found; import it or paste the transcript"}
    if not m.get("transcript"):
        return {"error": f"meeting '{m['id']}' has no transcript yet"}
    a = eng.analyze_text(ctx, m["transcript"])
    return {"meeting_id": m["id"], "analysis": a, "summary": eng.summarize(ctx, m, a)}


def meeting_summary(ctx, meeting: str) -> dict:
    """The stored summary for a processed meeting (or a fresh one if not processed yet)."""
    eng = _eng(ctx)
    m = eng.find_meeting(ctx, meeting)
    if not m:
        return {"error": f"meeting '{meeting}' not found"}
    s = m.get("summary")
    if not s and m.get("transcript"):
        s = eng.summarize(ctx, m, eng.analyze_text(ctx, m["transcript"]))
    if not s:
        return {"error": f"meeting '{m['id']}' has no transcript yet"}
    acct = ctx.store.account(m["account_id"]) if m.get("account_id") else None
    return {"meeting_id": m["id"], "processed": bool(m.get("processed_at")), "summary": s,
            "text": eng.digest_block(m, s, (acct or {}).get("name"))}


def list_meetings(ctx, status: str = "unprocessed", limit: int = 25) -> dict:
    """Meetings by status: unprocessed (transcript, not analyzed), processed, upcoming (no transcript yet)."""
    rows = ctx.store.select("meetings", order="started_at IS NULL, started_at DESC")
    if status == "processed":
        rows = [r for r in rows if r.get("processed_at")]
    elif status == "upcoming":
        rows = [r for r in rows if not r.get("transcript")]
    else:
        rows = [r for r in rows if r.get("transcript") and not r.get("processed_at")]
    keep = ("id", "title", "account_id", "deal_id", "started_at", "owner", "processed_at")
    return {"count": len(rows[:limit]), "meetings": [{k: r.get(k) for k in keep} for r in rows[:limit]]}


def coaching_notes(ctx, meeting: str) -> dict:
    """Coaching for the rep on one call: talk ratio, questions, monologues, objections, missed MEDDPICC areas."""
    eng = _eng(ctx)
    m = eng.find_meeting(ctx, meeting)
    if not m or not m.get("transcript"):
        return {"error": f"meeting '{meeting}' not found or has no transcript"}
    return eng.coaching(ctx, m)


def search_mentions(ctx, kind: str = "competitor_mention", key: str = "", days: int = 90) -> dict:
    """Search call insights. kind: competitor_mention, objection, pricing_mention, next_step, call_flag."""
    since = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
    rows = [r for r in ctx.store.insights(kind, since) if not key or (r.get("key") or "").lower() == key.lower()]
    by_key: dict[str, int] = {}
    for r in rows:
        by_key[r["key"]] = by_key.get(r["key"], 0) + 1
    return {"kind": kind, "count": len(rows), "by_key": by_key,
            "mentions": [{"key": r["key"], "evidence": r["evidence"], "account_id": r["account_id"],
                          "deal_id": r["deal_id"], "meeting_id": r["meeting_id"], "observed_at": r["observed_at"]}
                         for r in rows[:25]]}


TOOLS = {f.__name__: f for f in [analyze_call, meeting_summary, list_meetings, coaching_notes, search_mentions]}
