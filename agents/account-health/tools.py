"""Account Health MCP tools. Every score is computed in engine.py; the model only explains."""
from __future__ import annotations

from gtm_core import writer
from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def account_health(ctx, account: str) -> dict:
    """Renewal risk and expansion readiness for one customer (id, domain or name): scores, band, drivers with
    evidence, renewal date, recommendation (save, expand, watch, steady) and the next actions."""
    eng = _eng(ctx)
    a = eng.find(ctx, account)
    if not a:
        return {"error": f"customer '{account}' not found; mark the account customer: true or import its won deal"}
    x = eng.assess(ctx, a)
    eng.record(ctx, x)
    return {**{k: v for k, v in x.items() if k != "usage"}, "text": eng.format_one(x)}


def at_risk_customers(ctx, owner: str = "", limit: int = 10, renewing_within_days: int = 0) -> dict:
    """Customers at risk or on watch, renewal urgency first. Optional owner filter and renewal window in days."""
    res = [x for x in _eng(ctx).assess_all(ctx, owner=owner, persist=False) if x["band"] != "healthy"]
    if renewing_within_days:
        res = [x for x in res if x["days_to_renewal"] is not None and 0 <= x["days_to_renewal"] <= int(renewing_within_days)]
    keep = ("account_id", "name", "owner", "arr", "renewal_date", "days_to_renewal", "risk", "band", "priority",
            "risk_drivers", "actions")
    return {"count": len(res), "customers": [{k: x[k] for k in keep} for x in res[:int(limit)]]}


def expansion_ready(ctx, owner: str = "", limit: int = 10) -> dict:
    """Customers ready for an expansion conversation (not at risk), highest expansion score first, with the evidence."""
    res = sorted([x for x in _eng(ctx).assess_all(ctx, owner=owner, persist=False) if x["recommendation"] == "expand"],
                 key=lambda x: -x["expansion"])
    keep = ("account_id", "name", "owner", "arr", "seats", "expansion", "risk", "expansion_drivers", "actions")
    return {"count": len(res), "customers": [{k: x[k] for k in keep} for x in res[:int(limit)]]}


def portfolio_summary(ctx, owner: str = "") -> dict:
    """Customer count and ARR at risk, on watch, in expansion plays and renewing inside the alert window."""
    eng = _eng(ctx)
    res = eng.assess_all(ctx, owner=owner, persist=False)
    return {**eng.portfolio(res), "text": eng.format_report(res)}


def explain_health(ctx, account: str) -> dict:
    """A short plain-language read of one customer's health for the owner, built only from the computed drivers."""
    eng = _eng(ctx)
    a = eng.find(ctx, account)
    if not a:
        return {"error": f"customer '{account}' not found"}
    x = eng.assess(ctx, a)
    fallback = eng.format_one(x)
    facts = {k: x[k] for k in ("name", "arr", "renewal_date", "days_to_renewal", "risk", "band", "expansion",
                                "recommendation", "risk_drivers", "expansion_drivers", "actions")}
    facts["quotes"] = [q["quote"] for q in x["evidence"]["churn"][:2] + x["evidence"]["expansion"][:2]]
    text, src = writer.narrate(ctx, "Explain this customer's renewal risk and expansion readiness to the account owner in "
                               "four sentences. Keep every number, the recommendation and the actions exactly as given.",
                               facts, fallback, max_words=110)
    return {"name": x["name"], "recommendation": x["recommendation"], "risk": x["risk"], "expansion": x["expansion"],
            "summary": text, "summary_source": src}


def add_usage(ctx, account: str, metric: str, value: float, observed_at: str, source: str = "manual") -> dict:
    """Record one product usage observation. metric: active_users, core_actions, features_used, teams,
    support_tickets, escalations (or an alias listed in health-rules.yaml). observed_at: ISO date."""
    return _eng(ctx).add_usage(ctx, account, metric, value, observed_at, source)


def import_usage(ctx, path: str, source: str = "csv") -> dict:
    """Load product usage from a CSV or JSON file with account, metric, value, observed_at columns
    (a Snowflake, PostHog or product analytics export)."""
    return _eng(ctx).import_usage(ctx, path, source)


TOOLS = {f.__name__: f for f in [account_health, at_risk_customers, expansion_ready, portfolio_summary, explain_health,
                                 add_usage, import_usage]}
