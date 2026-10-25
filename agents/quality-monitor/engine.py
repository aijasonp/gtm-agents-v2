"""Quality Monitor engine: deterministic sampling, re-scoring and regression math. No model calls."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from gtm_core import copy_gate, profile


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def _now(now):
    return now or datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.replace(microsecond=0).isoformat()


def banned(ctx) -> list[str]:
    return copy_gate.load_banned(ctx.manifest.path(cfg(ctx, "banned_file", "")))


def drafts_between(ctx, start: datetime, end: datetime) -> list[dict]:
    """Prospect-facing drafts (scored by the gate when created) in [start, end), oldest first."""
    rows = ctx.store.query("SELECT * FROM drafts WHERE created_at>=? AND created_at<? AND gate_score IS NOT NULL "
                           "ORDER BY id", (_iso(start), _iso(end)))
    skip = set(cfg(ctx, "exclude_kinds", []) or [])
    return [r for r in rows if r.get("kind") not in skip and r.get("agent") != ctx.manifest.id]


def sample(ctx, days: int | None = None, per_agent: int | None = None, now: datetime | None = None) -> dict[str, list[dict]]:
    """Every k-th draft per agent (by id) so each agent contributes at most `per_agent`. Same data, same sample."""
    now = _now(now)
    n = int(per_agent or cfg(ctx, "sample_per_agent", 5))
    rows = drafts_between(ctx, now - timedelta(days=int(days or cfg(ctx, "recent_days", 7))), now + timedelta(seconds=1))
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["agent"], []).append(r)
    out = {}
    for agent, rs in sorted(by.items()):
        k = max(1, len(rs) // n)
        out[agent] = rs[::k][:n]
    return out


NUM_CLAIM = re.compile(r"(\$\s?\d[\d,.]*\s?[kmb]?\b|\b\d+(?:\.\d+)?\s?(?:%|percent\b|x\b)|\b\d+(?:\.\d+)?\s(?:hours?)\b)", re.I)
CUSTOMER_CLAIM = re.compile(r"\b(?:customers?|clients?|companies|teams)\s+(?:like|such as)\s+([A-Z][\w&.-]*(?:\s[A-Z][\w&.-]*)*)")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def claims(ctx, text: str) -> list[dict]:
    """Numbers and named-customer claims, each marked sourced when it appears in company.yaml proof points."""
    proof = _norm(" ".join(str(p) for p in profile.company(ctx).get("proof_points", [])))
    out = []
    for m in NUM_CLAIM.finditer(text or ""):
        c = m.group(0).strip()
        out.append({"claim": c, "type": "number", "sourced": _norm(c) in proof})
    for m in CUSTOMER_CLAIM.finditer(text or ""):
        name = m.group(1).strip().rstrip(".")
        out.append({"claim": m.group(0).strip(), "type": "customer", "sourced": _norm(name) in proof})
    return out


def scorecard(ctx, d: dict) -> dict:
    body = d.get("body") or ""
    g = copy_gate.check(body, banned(ctx), max_words=int(cfg(ctx, "max_words", 120)), pass_mark=int(cfg(ctx, "pass_mark", 32)))
    cl = claims(ctx, body)
    unsourced = [c["claim"] for c in cl if not c["sourced"]]
    return {"draft_id": d["id"], "agent": d.get("agent"), "kind": d.get("kind"), "created_at": d.get("created_at"),
            "score": g.score, "passed": g.passed and not unsourced, "gate_passed": g.passed,
            "score_at_creation": d.get("gate_score"), "failures": g.failures(), "unsourced_claims": unsourced}


def _stats(cards: list[dict]) -> dict:
    if not cards:
        return {"n": 0, "mean": None, "pass_rate": None}
    return {"n": len(cards), "mean": round(sum(c["score"] for c in cards) / len(cards), 2),
            "pass_rate": round(100 * sum(c["passed"] for c in cards) / len(cards), 1)}


def regression(ctx, now: datetime | None = None) -> list[dict]:
    """Per agent: last `recent_days` vs the `baseline_days` before that, over every gated draft (not the sample)."""
    now = _now(now)
    rd, bd = int(cfg(ctx, "recent_days", 7)), int(cfg(ctx, "baseline_days", 28))
    split = now - timedelta(days=rd)
    recent = drafts_between(ctx, split, now + timedelta(seconds=1))
    base = drafts_between(ctx, split - timedelta(days=bd), split)
    agents = sorted({d["agent"] for d in recent + base})
    out = []
    for a in agents:
        r = _stats([scorecard(ctx, d) for d in recent if d["agent"] == a])
        b = _stats([scorecard(ctx, d) for d in base if d["agent"] == a])
        row = {"agent": a, "recent": r, "baseline": b, "alerts": []}
        if b["n"] >= int(cfg(ctx, "min_baseline_drafts", 5)) and r["n"] >= int(cfg(ctx, "min_recent_drafts", 3)):
            row["score_change"] = round(r["mean"] - b["mean"], 2)
            row["pass_rate_change"] = round(r["pass_rate"] - b["pass_rate"], 1)
            if -row["score_change"] > float(cfg(ctx, "score_drop_alert", 3)):
                row["alerts"].append(f"mean gate score down {-row['score_change']:.1f} points ({b['mean']} to {r['mean']})")
            if -row["pass_rate_change"] > float(cfg(ctx, "pass_rate_drop_alert", 10)):
                row["alerts"].append(f"pass rate down {-row['pass_rate_change']:.0f} points ({b['pass_rate']}% to {r['pass_rate']}%)")
        else:
            row["note"] = "not enough drafts to compare"
        out.append(row)
    return out


def report(ctx, days: int | None = None, now: datetime | None = None) -> dict:
    s = sample(ctx, days, None, now)
    cards = {a: [scorecard(ctx, d) for d in rs] for a, rs in s.items()}
    per = {}
    for a, cs in cards.items():
        st = _stats(cs)
        top = {}
        for c in cs:
            for f in c["failures"]:
                k = f.split(":")[0]
                top[k] = top.get(k, 0) + 1
        per[a] = {**st, "unsourced_claims": sum(len(c["unsourced_claims"]) for c in cs),
                  "top_failures": sorted(top, key=lambda k: (-top[k], k))[:3],
                  "worst": min(cs, key=lambda c: (c["score"], c["draft_id"]))["draft_id"] if cs else None}
    return {"agents": per, "sampled": sum(len(v) for v in cards.values()), "cards": cards}


def format_alert(rows: list[dict]) -> str:
    lines = ["*Quality Monitor: regression*"]
    for r in rows:
        lines.append(f"- {r['agent']}: " + "; ".join(r["alerts"]))
    lines.append("Check recent prompt, template or config changes for these agents.")
    return "\n".join(lines)
