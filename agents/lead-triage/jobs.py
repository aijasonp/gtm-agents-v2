"""Lead Triage scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from gtm_core.agents import load_module
from gtm_core.guardrails import StepCounter
from gtm_core.importers import import_leads


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def ingest_inbox(ctx) -> dict:
    """Load lead files (CSV/JSON from forms, events, webhooks) dropped in the inbox, then archive them."""
    inbox = Path(ctx.manifest.config.get("lead_inbox", "data/leads/inbox"))
    if not inbox.exists():
        return {"files": 0, "leads": 0}
    done = inbox.parent / "processed"
    done.mkdir(parents=True, exist_ok=True)
    files = added = 0
    for f in sorted(list(inbox.glob("*.csv")) + list(inbox.glob("*.json"))):
        added += import_leads(ctx, f)["leads"]
        files += 1
        f.rename(done / f.name)
    return {"files": files, "leads": added}


def triage_inbox(ctx, now: datetime | None = None) -> dict:
    """Ingest new leads, triage each one, post the digest."""
    inbox = ingest_inbox(ctx)
    eng = _eng(ctx)
    results = []
    with StepCounter(limit=max(ctx.settings.max_loop_steps, 200)) as steps:
        for lead in ctx.store.select("leads", "status=?", ("new",), order="received_at"):
            steps.tick(lead["id"])
            r = eng.process(ctx, lead, now)
            if not r.get("skipped"):
                results.append(r)
    if results:
        ctx.slack.post(eng.digest(results))
    tiers = {t: sum(1 for r in results if r["tier"] == t) for t in ("hot", "warm", "nurture", "disqualify")}
    return {"inbox": inbox, "triaged": len(results), "tiers": tiers,
            "active_pipeline": sum(1 for r in results if r["active_pipeline"]),
            "approvals_queued": sum(len(r["approvals"]) for r in results)}


def sla_check(ctx, now: datetime | None = None) -> dict:
    """Nudge owners about routed hot and warm leads past their SLA with no executed follow-up."""
    now = now or datetime.now(timezone.utc)
    late = []
    for lead in ctx.store.select("leads", "status=?", ("routed",)):
        due = lead.get("sla_due")
        if not due or lead.get("tier") not in ("hot", "warm") or lead.get("sla_nudged"):
            continue
        if datetime.fromisoformat(due) > now:
            continue
        sent = ctx.store.one("SELECT id FROM drafts WHERE lead_id=? AND status='sent'", (lead["id"],))
        if sent:
            continue
        late.append(lead)
        ctx.store.upsert("leads", {"id": lead["id"], "sla_nudged": now.isoformat()})
    if late:
        ctx.slack.post("*Lead Triage: SLA missed*\n" + "\n".join(
            f"- {l['name']} ({l.get('company')}) | {l['tier']} | {l.get('owner')} | due {l['sla_due'][:16]}" for l in late))
    return {"late": len(late)}
