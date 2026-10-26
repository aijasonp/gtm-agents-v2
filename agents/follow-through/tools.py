"""Follow-Through MCP tools. Triggers only pause automation at once; every CRM write waits for approval."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def check_engagement(ctx, email: str) -> dict:
    """Facts and the trigger decision for one person, without acting: human opens, clicks, replies, steps sent,
    tier, open deal, and which rule in config/triggers.yaml matched."""
    return _eng(ctx).evaluate_email(ctx, email, apply=False)


def run_triggers(ctx, email: str = "") -> dict:
    """Run the triggers now: for one email, or for everyone with engagement since the last sweep. A tee-up
    pauses automation for that person, opens an AE task and queues the CRM task for approval."""
    eng = _eng(ctx)
    if email:
        return eng.evaluate_email(ctx, email)
    res = eng.evaluate_recent(ctx)
    res["results"] = [{"email": r["email"], "rule": r["decision"]["output"].get("rule"),
                       "action": (r.get("result") or {}).get("action")} for r in res["results"]]
    return res


def tee_ups(ctx, owner: str = "") -> dict:
    """Open tee-ups (prospects handed to an AE), soonest due first, with overdue flagged."""
    rows = _eng(ctx).open_teeups(ctx, owner or None)
    return {"count": len(rows), "overdue": sum(1 for r in rows if r["overdue"]),
            "tee_ups": [{k: r.get(k) for k in ("email", "owner", "rule", "priority", "reason", "due_at", "overdue")}
                        for r in rows]}


def resolve_tee_up(ctx, email: str, outcome: str = "contacted") -> dict:
    """Close a tee-up after the AE acted: contacted, meeting_booked, not_now or disqualified."""
    return _eng(ctx).resolve_teeup(ctx, email, outcome)


def explain_rules(ctx) -> dict:
    """The trigger table in plain words: each rule, what it tests and what it does, plus the engine in use."""
    from gtm_core import rules
    settings, tables = _eng(ctx).trigger_config(ctx)
    out = {"window_days": settings.get("window_days", 7), "cooldown_days": settings.get("cooldown_days", 14),
           "engine": "zen" if rules.zen_available() else "builtin", "tables": {}}
    for name, t in tables.items():
        out["tables"][name] = [{"id": r.id, "when": {k: v or "any" for k, v in r.when.items()},
                                "then": r.then} for r in t.rules]
    return out


def _cad(ctx):
    return load_module(ctx.manifest, "cadence")


def next_touches(ctx, owner: str = "", days: int = 7) -> dict:
    """Every scheduled next touch in the coming days, soonest first: who, which motion and step, when, and whether
    a draft is already waiting for the AE to confirm."""
    rows = _cad(ctx).schedule(ctx, owner or None, int(days))
    return {"count": len(rows), "touches": rows}


def cadence_status(ctx, email: str) -> dict:
    """Where one person stands: motion, step, next touch, last touch and the history of the cadence."""
    cad = _cad(ctx)
    rows = cad.live_for(ctx, email)
    if rows:
        return {"email": email, "live": True, "cadence": rows[0]}
    last = ctx.store.one("SELECT id FROM cadence WHERE email=? ORDER BY updated_at DESC LIMIT 1", ((email or "").lower(),))
    return {"email": email, "live": False, "last": cad.get(ctx, last["id"]) if last else None}


def log_touch(ctx, email: str, kind: str = "call", note: str = "") -> dict:
    """Record a touch the AE made outside the sequencer (call, LinkedIn, in person). The next sweep advances the
    cadence to the next step."""
    return _cad(ctx).log_touch(ctx, email, kind, note)


def follow_up_coverage(ctx) -> dict:
    """The no-gaps check: open deals with nobody in a cadence and no dated next step, and touches past due with no
    draft waiting on the AE. Empty gaps means every conversation has a next touch."""
    return _cad(ctx).coverage(ctx)


def start_motion(ctx, motion: str, email: str, ref: str = "manual") -> dict:
    """Put one person into a cadence by hand (motions are listed in config/cadences.yaml)."""
    from datetime import datetime, timezone
    c = ctx.store.contact_by_email(email) or {}
    r = _cad(ctx).start(ctx, motion, email, datetime.now(timezone.utc), ref, c.get("owner"), c.get("id"),
                        c.get("account_id"))
    return r or {"error": "already in this motion, or a later motion owns this person"}
