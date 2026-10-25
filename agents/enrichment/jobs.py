"""Enrichment scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _from_request(ctx, payload: dict) -> dict | None:
    """Find or create the local contact an `enrich_request` handoff is about."""
    c = None
    if payload.get("contact_id"):
        c = ctx.store.get("contacts", payload["contact_id"])
    if not c and payload.get("email"):
        c = ctx.store.contact_by_email(payload["email"])
        if not c:
            ctx.store.upsert("contacts", {"id": payload["email"].lower(), "email": payload["email"].lower(),
                                          "name": payload.get("name"), "account_id": payload.get("account_id")})
            c = ctx.store.get("contacts", payload["email"].lower())
    if not c and payload.get("name") and (payload.get("domain") or payload.get("account_id")):
        domain = payload.get("domain") or (ctx.store.account(payload["account_id"]) or {}).get("domain")
        cid = f"{payload['name'].strip().lower().replace(' ', '.')}@{domain}" if domain else None
        if cid:
            c = ctx.store.get("contacts", cid)
            if not c:
                ctx.store.upsert("contacts", {"id": cid, "name": payload["name"], "domain": domain,
                                              "account_id": payload.get("account_id"),
                                              "enrich_reason": payload.get("reason")})
                c = ctx.store.get("contacts", cid)
    return c


def enrich_queue(ctx, now: datetime | None = None) -> dict:
    """Requests from other agents first, then target contacts missing email or phone. Stops at the spend caps."""
    eng = _eng(ctx)
    run = eng.new_run()
    cfg = eng.providers_cfg(ctx)
    stats = {"contacts": 0, "filled": 0, "by_field": {}, "approvals": 0, "manual": 0, "requests": 0}
    limit = int(ctx.manifest.config.get("max_per_run", 50))
    done: set[str] = set()

    def full():
        return stats["contacts"] >= limit or bool(run["capped"])

    def work(c, fields=None) -> bool:
        if c is None or c["id"] in done or full():
            return False
        done.add(c["id"])
        r = eng.enrich_contact(ctx, c, fields, run, cfg, now=now)
        stats["contacts"] += 1
        for f in r.get("changed", {}):
            stats["filled"] += 1
            stats["by_field"][f] = stats["by_field"].get(f, 0) + 1
        stats["approvals"] += len(r.get("approvals", []))
        stats["manual"] += sum(1 for v in (r.get("results") or {}).values() if v.get("status") == "needs manual research")
        return not run["capped"] or bool(r.get("changed"))

    # Requests from other agents: consumed only when actually worked; left pending when the run is full or capped.
    for h in ctx.handoffs.pending("enrich_request"):
        if full():
            break
        if not ctx.handoffs.claim(h["id"]):
            continue
        try:
            c = _from_request(ctx, h["payload"])
            if c is None:  # nothing identifiable to look up: close it
                ctx.handoffs.consume(h["id"])
                continue
            if work(c, h["payload"].get("fields")):
                stats["requests"] += 1
                ctx.handoffs.consume(h["id"])
            else:  # stopped by the cap or the run limit: back in the queue for the next run
                ctx.store.execute("UPDATE handoffs SET status='pending' WHERE id=?", (h["id"],))
        except Exception as e:
            ctx.handoffs.fail(h["id"], f"{type(e).__name__}: {e}")

    # Target contacts, rotated so the same first N are not re-queried every run.
    targets = [c for c in eng.target_contacts(ctx) if eng.missing(c)]
    off = int(ctx.store.get_state("enrichment_rotation", 0) or 0) % max(1, len(targets))
    worked = 0
    for c in targets[off:] + targets[:off]:
        if full():
            break
        miss = eng.missing(c)
        work(c, miss + ([] if c.get("title") else ["title"]))
        worked += 1
    ctx.store.set_state("enrichment_rotation", off + worked)
    stats.update({"calls": run["calls"], "spent": round(run["spent"], 2), "capped": run["capped"]})
    if stats["contacts"]:
        ctx.slack.post(eng.format_run(stats))
    return stats
