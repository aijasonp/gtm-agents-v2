"""Signal Scout scoring engine: shared by scheduled jobs and MCP tools."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from gtm_core.scoring import IcpProfile, load_taxonomy, score_account
from gtm_core.store import now_iso


@lru_cache(maxsize=8)
def _tax(path: str):
    return load_taxonomy(path)


@lru_cache(maxsize=8)
def _icp(path: str):
    return IcpProfile.from_yaml(path)


def taxonomy(ctx):
    return _tax(str(ctx.manifest.path(ctx.manifest.config["taxonomy"])))


def icp(ctx):
    return _icp(str(ctx.manifest.path(ctx.manifest.config["icp"])))


def score_one(ctx, acct: dict, now: datetime | None = None):
    cfg = ctx.manifest.config
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=int(cfg.get("lookback_days", 120)))).isoformat()
    sigs = ctx.store.signals_for(acct["id"], since)
    return score_account(acct, sigs, taxonomy(ctx), icp(ctx), ctx.store.get_weights(),
                         icp_weight=float(cfg.get("icp_weight", 0.4)), icp_floor=float(cfg.get("icp_floor", 30)),
                         now=now)


def score_all(ctx, now: datetime | None = None, persist: bool = True) -> list:
    results = [score_one(ctx, a, now) for a in ctx.store.accounts()]
    results.sort(key=lambda r: (r.tier == "X", -r.score))
    if persist:
        ts = now_iso()
        for r in results:
            ctx.store.insert(
                "INSERT INTO scores (run_id, agent, account_id, score, icp, signal_score, tier, reasons, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ctx.run_id, ctx.manifest.id, r.account_id, r.score, r.icp, r.signal, r.tier,
                 json.dumps(r.reasons), ts))
    return results


def previous_ranks(ctx) -> dict[str, float]:
    """Scores from the last completed sweep, to show movers."""
    last = ctx.store.one("SELECT id FROM runs WHERE agent=? AND job='daily_sweep' AND status='ok' AND id<>? "
                         "ORDER BY finished_at DESC LIMIT 1", (ctx.manifest.id, ctx.run_id))
    if not last:
        return {}
    return {r["account_id"]: r["score"] for r in
            ctx.store.query("SELECT account_id, score FROM scores WHERE run_id=?", (last["id"],))}
