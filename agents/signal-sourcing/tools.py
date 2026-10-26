"""Signal Sourcing MCP tools. Sourcing writes only to the local signals table; nothing goes to the CRM."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def scan_account(ctx, account: str) -> dict:
    """Source signals for one account now (id, domain or CRM id): latest 10-K/10-Q, 8-K officer changes,
    newsroom or trusted press, and public job boards. Stores new signals for Signal Scout and says what
    each tier found or why it found nothing."""
    a = ctx.store.account(account)
    if not a:
        return {"error": f"account '{account}' not found; add it with add_company"}
    return _eng(ctx).scan_account(ctx, a)


def scan_due(ctx, limit: int = 25) -> dict:
    """Scan the accounts that are due (not scanned within rescan_days), best Signal Scout tier first."""
    res = _eng(ctx).scan_due(ctx, limit=limit)
    res["results"] = [{k: r.get(k) for k in ("account", "name", "rejected", "skipped")} |
                      {"signals": len(r.get("findings", [])), "stored": len(r.get("stored", []))}
                      for r in res["results"]]
    return res


def dispatch_batch(ctx, limit: int = 25) -> dict:
    """Send-ready accounts: each with a dated, sourced signal and every required field (domain, company,
    real industry, source, detail, URL, date, High or Medium, personas). Never padded. Excluded accounts
    are listed with the reason."""
    res = _eng(ctx).dispatch(ctx, limit=limit)
    return {**res, "text": _eng(ctx).format_dispatch(res)}


def discover_companies(ctx) -> dict:
    """New companies whose recent SEC filings use the configured phrases and are not accounts yet."""
    return _eng(ctx).discover(ctx)


def add_company(ctx, name: str, domain: str, cik: str = "", ticker: str = "", industry: str = "",
                employees: int | None = None, newsroom_rss: str = "") -> dict:
    """Add or update an account to source (local only). cik or ticker makes the SEC match exact;
    newsroom_rss is the company's press release feed."""
    return _eng(ctx).add_company(ctx, name, domain, cik, ticker, industry, employees, newsroom_rss)


def sourcing_report(ctx, days: int = 7) -> dict:
    """Signals sourced in the last N days by tier, accounts with signals, and fetch failures."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
    rows = ctx.store.query("SELECT source, COUNT(*) AS n, COUNT(DISTINCT account_id) AS accounts FROM signals "
                           "WHERE source LIKE 'sourcing:%' AND created_at>=? GROUP BY source", (since,))
    fails = ctx.store.query("SELECT COUNT(*) AS n FROM audit_log WHERE event='sourcing.fetch_failed' AND ts>=?", (since,))
    return {"days": days, "by_tier": {r["source"].split(":", 1)[1]: {"signals": r["n"], "accounts": r["accounts"]}
                                      for r in rows},
            "fetch_failures": fails[0]["n"] if fails else 0}


TOOLS = {f.__name__: f for f in [scan_account, scan_due, dispatch_batch, discover_companies, add_company,
                                 sourcing_report]}
