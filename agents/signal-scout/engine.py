"""Signal Scout scoring engine: shared by scheduled jobs and MCP tools."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from gtm_core import decision, profile
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


def judgment(ctx) -> dict:
    return decision.judgment(ctx.manifest.path(ctx.manifest.config["icp"]))


def judge(ctx, acct: dict, sigs: list[dict], now: datetime | None = None, refresh: bool = False) -> dict:
    """Run the judged ICP and signal relevance models. Returns {} when judgment is off."""
    cfg = judgment(ctx)
    if not decision.enabled(cfg):
        return {}
    vps = profile.company(ctx).get("value_props", [])
    state = decision.account_state(acct, sigs, taxonomy(ctx))
    out = {}
    fit_m = decision.get_model(cfg, "icp_fit", vps)
    if fit_m:
        v = decision.decide(ctx, cfg, fit_m, acct["id"], state, now, refresh)
        out["icp_fit"] = v
    rel_m = decision.get_model(cfg, "signal_relevance", vps)
    if rel_m and sigs:
        v = decision.decide(ctx, cfg, rel_m, acct["id"], {"signals": state["signals"]}, now, refresh)
        out["signal_relevance"] = v
    return out


def signal_multiplier(cfg: dict, verdict) -> float:
    if verdict is None or verdict.score is None:
        return 1.0
    m = (cfg.get("models") or {}).get("signal_relevance") or {}
    lo, hi = float(m.get("floor", 0.85)), float(m.get("ceiling", 1.15))
    return round(lo + (hi - lo) * verdict.score / 100, 3)


def score_one(ctx, acct: dict, now: datetime | None = None, refresh: bool = False):
    cfg = ctx.manifest.config
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=int(cfg.get("lookback_days", 120)))).isoformat()
    sigs = ctx.store.signals_for(acct["id"], since)
    v = judge(ctx, acct, sigs, now, refresh)
    jcfg = judgment(ctx)
    fit_v = v.get("icp_fit")
    judged = None
    if fit_v is not None:
        judged = {"score": fit_v.score, "coverage": fit_v.coverage, "blend": float(jcfg.get("blend", 0.5)),
                  "reasons": fit_v.reasons, "backend": fit_v.backend,
                  "primary_pain": fit_v.value("primary_pain")}
    return score_account(acct, sigs, taxonomy(ctx), icp(ctx), ctx.store.get_weights(),
                         icp_weight=float(cfg.get("icp_weight", 0.4)), icp_floor=float(cfg.get("icp_floor", 30)),
                         now=now, judged=judged, signal_multiplier=signal_multiplier(jcfg, v.get("signal_relevance")))


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
