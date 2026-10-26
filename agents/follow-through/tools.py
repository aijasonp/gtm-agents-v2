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
