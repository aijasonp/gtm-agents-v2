"""Signal Scout MCP tools. Deterministic: the model asks, the core computes."""
from __future__ import annotations

from gtm_core.agents import load_module
from gtm_core.scoring import signal_id
from gtm_core.store import now_iso


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def score_account(ctx, account: str) -> dict:
    """Score one account (id, domain or CRM id): ICP fit, signal heat, tier and the reasons behind it."""
    acct = ctx.store.account(account)
    if not acct:
        return {"error": f"account '{account}' not found; import it or run sync_accounts"}
    return _eng(ctx).score_one(ctx, acct).as_dict()


def list_priority_accounts(ctx, limit: int = 20, tier: str = "") -> dict:
    """Ranked accounts to work now. Optional tier filter (A, B, C, D). Excludes out-of-ICP accounts."""
    ranked = _eng(ctx).score_all(ctx, persist=False)
    rows = [r.as_dict() for r in ranked if r.tier != "X" and (not tier or r.tier == tier.upper())]
    return {"count": len(rows[:limit]), "accounts": rows[:limit]}


def explain_score(ctx, account: str) -> dict:
    """Plain-language breakdown of why an account scored where it did, and what would move it."""
    acct = ctx.store.account(account)
    if not acct:
        return {"error": f"account '{account}' not found"}
    r = _eng(ctx).score_one(ctx, acct)
    tax = _eng(ctx).taxonomy(ctx)
    present = set(r.signals.categories if r.signals else [])
    missing = [tax.categories[c] for c in tax.categories if c not in present]
    return {
        "account": r.name, "score": r.score, "tier": r.tier, "icp": r.icp, "signal": r.signal,
        "reasons": r.reasons, "rule_icp": r.rule_icp, "judged": r.judged,
        "signals": r.as_dict()["top_signals"],
        "would_raise_score": f"A strong signal in a new category ({', '.join(missing[:3])}) would trigger stacking."
        if missing else "Already stacked across categories.",
        "safe_openers": [c["say_it"] for c in r.as_dict()["top_signals"] if c["say_it"]],
    }


def add_signal(ctx, account: str, signal_type: str, observed_at: str = "", url: str = "", title: str = "",
               strength: float | None = None) -> dict:
    """Record a signal a rep or another system found. Duplicates (same account, type, source, day) are ignored."""
    acct = ctx.store.account(account)
    if not acct:
        return {"error": f"account '{account}' not found"}
    tax = _eng(ctx).taxonomy(ctx)
    if signal_type not in tax.types:
        return {"error": f"unknown signal_type; valid: {sorted(tax.types)}"}
    obs = observed_at or now_iso()
    sig = {"id": signal_id(acct["id"], signal_type, url or title, obs), "account_id": acct["id"],
           "signal_type": signal_type, "category": tax.types[signal_type].category, "source": "tool",
           "url": url or None, "observed_at": obs, "strength": strength, "payload": {"title": title}}
    try:
        added = ctx.store.add_signal(sig)
    except ValueError as e:
        return {"error": str(e)}
    return {"added": added, "duplicate": not added, "new_score": _eng(ctx).score_one(ctx, acct).as_dict()}


def record_outcome(ctx, account: str, outcome: str) -> dict:
    """Log what happened with an account so weekly learning can reweight signals.
    outcome: reply_positive, meeting, opportunity, closed_won, no_response, bad_fit, reply_negative."""
    valid = {"reply_positive", "meeting", "opportunity", "closed_won", "no_response", "bad_fit", "reply_negative"}
    if outcome not in valid:
        return {"error": f"outcome must be one of {sorted(valid)}"}
    acct = ctx.store.account(account)
    if not acct:
        return {"error": f"account '{account}' not found"}
    ctx.store.add_outcome(acct["id"], outcome, source="tool")
    return {"recorded": True, "account": acct["name"], "outcome": outcome}


def push_to_crm(ctx, account: str) -> dict:
    """Queue the account's current score, tier and reasons for a CRM write. A human must approve it first."""
    acct = ctx.store.account(account)
    if not acct or not acct.get("crm_id"):
        return {"error": "account not found or has no CRM id"}
    r = _eng(ctx).score_one(ctx, acct)
    f = ctx.manifest.config.get("crm_fields", {})
    rid = ctx.approvals.request("crm_update", {
        "crm_id": acct["crm_id"], "account": r.name,
        "fields": {f.get("score", "gtm_signal_score"): r.score, f.get("tier", "gtm_signal_tier"): r.tier,
                   f.get("reasons", "gtm_signal_reasons"): " | ".join(r.reasons)[:1000]}})
    return {"queued_for_approval": rid, "note": "Run `gtm approvals signal-scout list` to review."}


def judge_account(ctx, account: str, refresh: bool = False) -> dict:
    """Judged ICP answers for one account: each typed question, its answer, the quoted evidence and
    the backend that answered (rules, model or remote). refresh=True ignores the cached verdict."""
    acct = ctx.store.account(account)
    if not acct:
        return {"error": f"account '{account}' not found"}
    eng = _eng(ctx)
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=int(ctx.manifest.config.get("lookback_days", 120)))).isoformat()
    v = eng.judge(ctx, acct, ctx.store.signals_for(acct["id"], since), refresh=refresh)
    if not v:
        return {"account": acct["name"], "judgment": "off (no judgment section in config/icp.yaml)"}
    return {"account": acct["name"], **{k: x.as_dict() for k, x in v.items()},
            "score": eng.score_one(ctx, acct).as_dict()}


TOOLS = {f.__name__: f for f in [score_account, list_priority_accounts, explain_score, add_signal,
                                 record_outcome, push_to_crm, judge_account]}
