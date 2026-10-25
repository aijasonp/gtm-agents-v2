"""Rep Brief scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime, timezone

from gtm_core.agents import load_module
from gtm_core.store import now_iso


def daily_briefs(ctx, now: datetime | None = None) -> dict:
    """One Slack brief per rep. Reps with nothing new since their last brief are skipped."""
    eng = load_module(ctx.manifest, "engine")
    now = now or datetime.now(timezone.utc)
    sent, skipped = [], []
    failed = []
    for owner in eng.owner_names(ctx):
        try:
            b = eng.brief(ctx, owner, now)
        except Exception as e:  # one rep's bad data never blocks everyone else's brief
            ctx.audit.log("rep_brief.error", owner=owner, error=str(e)[:300])
            failed.append(owner)
            continue
        if not b["has_news"]:
            skipped.append(owner)
            continue
        ctx.slack.post(eng.format_brief(b))
        ctx.store.set_state(f"rep_brief_last:{owner}", now_iso())  # wall clock: when the brief actually went out
        sent.append(owner)
    return {"sent": len(sent), "skipped": len(skipped), "reps": sent, "failed": failed}
