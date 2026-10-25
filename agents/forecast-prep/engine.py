"""Forecast Prep engine: every total, variance and pace number is computed here. The model only writes summary bullets."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from gtm_core import meddpicc, pipeline, profile, writer

SNAP_KEY = "forecast_prep:snapshots"
ALERT_KEY = "forecast_prep:alerted"
BUCKETS = ("commit", "best_case", "pipeline", "omitted")


# ---------- config ----------
@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    return yaml.safe_load(open(path).read()) or {}


@lru_cache(maxsize=8)
def _questions(path: str) -> dict[str, str]:
    out = {}
    for line in open(path).read().splitlines():
        m = re.match(r"^([a-z_]+):\s+(.+)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def cats(ctx) -> dict:
    return _yaml(str(ctx.manifest.path(cfg(ctx, "categories", "skill/references/forecast-categories.yaml"))))


def questions(ctx) -> dict[str, str]:
    return _questions(str(ctx.manifest.path(cfg(ctx, "questions", "skill/references/questions-bank.md"))))


def _now(now):
    return now or datetime.now(timezone.utc)


def quarter_bounds(now: datetime) -> tuple[datetime, datetime]:
    q = (now.month - 1) // 3
    start = datetime(now.year, 3 * q + 1, 1, tzinfo=timezone.utc)
    end = datetime(now.year + (1 if q == 3 else 0), 1 if q == 3 else 3 * q + 4, 1, tzinfo=timezone.utc)
    return start, end


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    end = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def quarter_label(now: datetime) -> str:
    return f"Q{(now.month - 1) // 3 + 1} {now.year}"


def amt(d: dict) -> float:
    try:
        return float(d.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.0f}"


def bucket(ctx, deal: dict) -> str:
    """commit | best_case | pipeline | omitted | won | lost."""
    if pipeline.is_won(deal):
        return "won"
    if pipeline.is_lost(deal):
        return "lost"
    return category_bucket(ctx, deal.get("forecast_category"))


def category_bucket(ctx, value) -> str:
    v = (value or "").strip().lower()
    if not v:
        return "pipeline"
    m = cats(ctx).get("categories", {})
    for b in ("omitted", "best_case", "commit", "pipeline"):  # specific before broad ("best case" vs "commit")
        names = [n.lower() for n in m.get(b, [])]
        if v in names:
            return b
    for b in ("omitted", "best_case", "commit", "pipeline"):
        if any(n.lower() in v for n in m.get(b, [])):
            return b
    return "pipeline"


def stage_key(ctx, stage) -> str:
    return meddpicc.stage_key(stage, cats(ctx).get("stage_aliases"))


# ---------- team and quotas ----------
def owners(ctx) -> list[str]:
    team = profile.company(ctx).get("team", {}) or {}
    names = [o["name"] for o in team.get("owners", []) if o.get("name")]
    seen = {d.get("owner") for d in ctx.store.select("deals") if d.get("owner")}
    return names + sorted(n for n in seen if n not in names)


def quotas(ctx) -> dict[str, float | None]:
    """Per-owner quarter quota: explicit `quota` on the owner, else the team quarter quota split evenly
    across configured owners. Owners not in the config get None (no coverage shown)."""
    team = profile.company(ctx).get("team", {}) or {}
    conf = [o for o in team.get("owners", []) if o.get("name")]
    total = team.get("quarter_quota")
    explicit = {o["name"]: float(o["quota"]) for o in conf if o.get("quota") is not None}
    rest = [o["name"] for o in conf if o["name"] not in explicit]
    out: dict[str, float | None] = dict(explicit)
    if rest:
        remaining = (float(total) - sum(explicit.values())) if total is not None else None
        for n in rest:
            out[n] = round(remaining / len(rest), 2) if remaining is not None and remaining > 0 else None
    return out


# ---------- per-deal facts ----------
def latest_inspection(ctx, deal_id: str) -> dict | None:
    rows = ctx.store.insights(kind="deal_inspection", deal_id=deal_id)
    return rows[0]["value"] if rows else None


def deal_facts(ctx, d: dict, now: datetime) -> dict:
    ins = latest_inspection(ctx, d["id"])
    hist = ctx.store.deal_history(d["id"])
    gaps = (ins or {}).get("gaps")
    if gaps is None:
        gaps = [g["element"] for g in meddpicc.gaps(d.get("meddpicc"), d.get("stage"),
                                                       aliases=cats(ctx).get("stage_aliases"))]
    return {"deal_id": d["id"], "name": d.get("name") or d["id"], "owner": d.get("owner"), "amount": amt(d),
            "stage": d.get("stage"), "stage_key": stage_key(ctx, d.get("stage")), "close_date": d.get("close_date"),
            "bucket": bucket(ctx, d), "risk": (ins or {}).get("risk"), "inspected": ins is not None,
            "recommendation": (ins or {}).get("recommendation"), "gaps": gaps, "slips": pipeline.slips(hist),
            "next_step": d.get("next_step"), "next_step_date": d.get("next_step_date"),
            "close_passed": bool(pipeline.parse_dt(d.get("close_date")) and pipeline.parse_dt(d["close_date"]) < now)}


def deal_questions(ctx, f: dict, now: datetime, limit: int = 3) -> list[str]:
    qb = questions(ctx)
    keys = []
    if f["close_passed"]:
        keys.append("close_date_passed")
    if f["slips"] >= 2:
        keys.append("slipped_twice")
    elif f["slips"] == 1:
        keys.append("slipped")
    if not (f.get("next_step") or "").strip():
        keys.append("no_next_step")
    else:
        nd = pipeline.parse_dt(f.get("next_step_date"))
        if nd and nd < now:
            keys.append("next_step_overdue")
    if f.get("risk") is not None and f["risk"] >= int(cfg(ctx, "commit_risk_max", 50)):
        keys.append("high_risk")
    order = ["economic_buyer", "paper_process", "decision_process", "champion", "metrics", "decision_criteria",
             "competition", "identify_pain"]
    keys += [g for g in order if g in (f.get("gaps") or [])]
    out = []
    for k in keys:
        if k in qb and qb[k] not in out:
            out.append(qb[k])
        if len(out) >= limit:
            break
    return out


def in_suggested(ctx, f: dict) -> bool:
    risk = f["risk"]
    if f["bucket"] == "commit":
        return risk is None or risk < int(cfg(ctx, "commit_risk_max", 50))
    if f["bucket"] == "best_case":
        late = f["stage_key"] in cfg(ctx, "late_stages", ["negotiation", "commit"])
        return late and risk is not None and risk < int(cfg(ctx, "upside_risk_max", 25))
    return False


# ---------- changes since a date ----------
def deal_changes(ctx, d: dict, since: datetime) -> list[dict]:
    """What moved on this deal since `since`: category, amount, close date, stage, created, closed."""
    out = []
    hist = ctx.store.deal_history(d["id"])
    before = [h for h in hist if (pipeline.parse_dt(h.get("snapshot_at")) or since) < since]
    base = before[-1] if before else None
    created = pipeline.parse_dt(d.get("created_at"))
    if pipeline.is_won(d) or pipeline.is_lost(d):
        cd = pipeline.parse_dt(d.get("close_date"))
        was_open = base is None or (base.get("status") or "open") == "open"
        if cd and cd >= since and was_open:
            out.append({"kind": "closed_won" if pipeline.is_won(d) else "closed_lost", "text": "closed won" if pipeline.is_won(d) else "closed lost"})
        return out
    if created and created >= since and base is None:
        out.append({"kind": "new", "text": "new deal"})
        return out
    if base is None:
        return out
    # Only attribute a change to this window when a snapshot was taken inside it (sync and import snapshot
    # every deal); otherwise the move happened before the window and was already reported then.
    if not any((pipeline.parse_dt(h.get("snapshot_at")) or since) >= since for h in hist):
        return out
    b_old, b_new = category_bucket(ctx, base.get("forecast_category")), bucket(ctx, d)
    if b_old != b_new:
        if b_new == "commit":
            out.append({"kind": "into_commit", "text": "moved into commit"})
        elif b_old == "commit":
            out.append({"kind": "out_of_commit", "text": f"moved out of commit to {b_new.replace('_', ' ')}"})
        else:
            out.append({"kind": "category", "text": f"{b_old.replace('_', ' ')} -> {b_new.replace('_', ' ')}"})
    old_amt = float(base.get("amount") or 0)
    if base.get("amount") is not None and abs(amt(d) - old_amt) >= 1:
        out.append({"kind": "amount", "text": f"amount {money(old_amt)} -> {money(amt(d))}", "from": old_amt, "to": amt(d)})
    oc, nc = pipeline.parse_dt(base.get("close_date")), pipeline.parse_dt(d.get("close_date"))
    if oc and nc and oc.date() != nc.date():
        out.append({"kind": "close_date", "text": f"close date {oc.date().isoformat()} -> {nc.date().isoformat()}",
                    "from": oc.date().isoformat(), "to": nc.date().isoformat(), "later": nc > oc})
    if base.get("stage") and base.get("stage") != d.get("stage"):
        out.append({"kind": "stage", "text": f"stage {base['stage']} -> {d.get('stage')}"})
    return out


def changes(ctx, owner: str = "", days: int = 7, now: datetime | None = None) -> list[dict]:
    now = _now(now)
    since = now - timedelta(days=days)
    out = []
    for d in ctx.store.select("deals"):
        if owner and d.get("owner") != owner:
            continue
        ch = deal_changes(ctx, d, since)
        if ch:
            out.append({"deal_id": d["id"], "name": d.get("name") or d["id"], "owner": d.get("owner"),
                        "amount": amt(d), "changes": ch})
    out.sort(key=lambda c: -c["amount"])
    return out


# ---------- AE level ----------
def _quarter_deals(ctx, owner: str, now: datetime) -> list[dict]:
    qs, qe = quarter_bounds(now)
    out = []
    for d in ctx.store.select("deals"):
        if owner and d.get("owner") != owner:
            continue
        cd = pipeline.parse_dt(d.get("close_date"))
        if pipeline.is_open(d):
            if cd is None or cd < qe:  # open and due this quarter, or overdue / undated: still on the hook
                out.append(d)
        elif cd and qs <= cd < qe:
            out.append(d)
    return out


def totals(ctx, facts: list[dict], start: datetime | None = None, end: datetime | None = None) -> dict:
    def within(f):
        if start is None:
            return True
        cd = pipeline.parse_dt(f["close_date"])
        return cd is not None and start <= cd < end
    sel = [f for f in facts if within(f)]
    s = lambda b: round(sum(f["amount"] for f in sel if f["bucket"] == b), 2)
    commit, best = s("commit"), s("best_case")
    return {"won": s("won"), "commit": commit, "best_case": round(commit + best, 2),
            "pipeline": round(sum(f["amount"] for f in sel if f["bucket"] in ("commit", "best_case", "pipeline")), 2)}


def ae_prep(ctx, owner: str, now: datetime | None = None) -> dict:
    now = _now(now)
    facts = [deal_facts(ctx, d, now) for d in _quarter_deals(ctx, owner, now)]
    q = totals(ctx, facts)
    ms, me = month_bounds(now)
    m = totals(ctx, facts, ms, me)
    commit_deals = sorted([f for f in facts if f["bucket"] == "commit"], key=lambda f: -f["amount"])
    for f in commit_deals:
        f["questions"] = deal_questions(ctx, f, now)
    suggested = [f for f in facts if in_suggested(ctx, f)]
    dropped = [f for f in commit_deals if f not in suggested]
    added = [f for f in suggested if f["bucket"] == "best_case"]
    suggested_total = round(sum(f["amount"] for f in suggested), 2)
    quota = quotas(ctx).get(owner)
    out = {"owner": owner, "as_of": now.replace(microsecond=0).isoformat(), "quarter": quarter_label(now),
           "quota": quota, "quarter_totals": q, "month_totals": m,
           "rep_commit": q["commit"], "suggested_commit": suggested_total,
           "variance": round(q["commit"] - suggested_total, 2), "flag": variance_flag(ctx, q["commit"], suggested_total),
           "dropped": [{"name": f["name"], "amount": f["amount"], "risk": f["risk"]} for f in dropped],
           "added": [{"name": f["name"], "amount": f["amount"], "risk": f["risk"]} for f in added],
           "commit_deals": commit_deals, "changes": changes(ctx, owner, 7, now),
           "not_inspected": [f["name"] for f in commit_deals if not f["inspected"]]}
    out["coverage"] = round((q["won"] + q["commit"]) / quota, 2) if quota else None
    fallback = "\n".join([
        f"- Commit {money(q['commit'])} against a suggested {money(suggested_total)}"
        + (f" ({out['flag']})." if out["flag"] else "."),
        f"- {len(commit_deals)} commit deals; {len(dropped)} carry risk at or above the threshold.",
        f"- {len(out['changes'])} deals changed in the last 7 days.",
    ])
    out["summary"], out["summary_source"] = writer.narrate(
        ctx, "Write 3 short bullets for a rep preparing their forecast call. Use only these facts.",
        {k: out[k] for k in ("owner", "quarter_totals", "rep_commit", "suggested_commit", "flag", "dropped", "added")},
        fallback, max_words=80)
    return out


def variance_flag(ctx, rep: float, suggested: float) -> str | None:
    gap = rep - suggested
    pct = float(cfg(ctx, "variance_flag_pct", 25)) / 100
    floor = float(cfg(ctx, "variance_flag_min", 25000))
    if abs(gap) < floor:
        return None
    base = max(suggested, 1.0)
    if gap > 0 and gap / base > pct:
        return f"happy ears: rep commit {money(gap)} above suggested"
    if gap < 0 and -gap / max(rep, 1.0) > pct:
        return f"sandbagging: rep commit {money(-gap)} below suggested"
    return None


def format_ae(p: dict) -> str:
    q, m = p["quarter_totals"], p["month_totals"]
    week = datetime.fromisoformat(p["as_of"]).strftime("%b %d").replace(" 0", " ")
    lines = [f"*Forecast prep: {p['owner']}* | {p['quarter']}, as of {week}",
             f"Quarter: won {money(q['won'])} | commit {money(q['commit'])} | best case {money(q['best_case'])} | pipeline {money(q['pipeline'])}"
             + (f" | quota {money(p['quota'])}, coverage {p['coverage']}x" if p.get("quota") else " | no quota set"),
             f"Month: commit {money(m['commit'])} | best case {money(m['best_case'])}"]
    why = []
    if p["dropped"]:
        why.append("dropped " + ", ".join(f"{d['name']} (risk {d['risk']})" for d in p["dropped"][:3]))
    if p["added"]:
        why.append("added " + ", ".join(f"{d['name']} (risk {d['risk']})" for d in p["added"][:3]))
    lines.append(f"Your commit {money(p['rep_commit'])} | suggested {money(p['suggested_commit'])}"
                 + (f" ({'; '.join(why)})" if why else "") + (f" | {p['flag']}" if p.get("flag") else ""))
    if p["changes"]:
        lines.append("Changes since last week: " + "; ".join(
            f"{c['name']}: {', '.join(x['text'] for x in c['changes'])}" for c in p["changes"][:5]))
    else:
        lines.append("Changes since last week: none")
    if p["commit_deals"]:
        lines.append("Commit deals:")
        for f in p["commit_deals"][:8]:
            risk = f"risk {f['risk']}" if f["risk"] is not None else "not inspected"
            lines.append(f"- {f['name']} {money(f['amount'])} | {f['stage']} | {risk}")
            lines += [f"  Q: {q_}" for q_ in f.get("questions", [])]
    else:
        lines.append("Commit deals: none")
    return "\n".join(lines)


# ---------- manager level ----------
def manager_prep(ctx, now: datetime | None = None) -> dict:
    now = _now(now)
    reps = [ae_prep(ctx, o, now) for o in owners(ctx)]
    reps = [r for r in reps if r["quarter_totals"]["pipeline"] or r["quarter_totals"]["won"] or r.get("quota")]
    qs, qe = quarter_bounds(now)
    open_facts = [deal_facts(ctx, d, now) for d in _quarter_deals(ctx, "", now) if pipeline.is_open(d)]
    open_facts = [f for f in open_facts if f["bucket"] in ("commit", "best_case", "pipeline")]
    weight = {"commit": 3, "best_case": 2, "pipeline": 1}
    top = sorted(open_facts, key=lambda f: (-weight[f["bucket"]] * f["amount"] * ((f["risk"] if f["risk"] is not None else 50) + 1)))
    top = top[:int(cfg(ctx, "top_deals", 5))]
    for f in top:
        f["questions"] = deal_questions(ctx, f, now, 2)
    slipped = [f for f in open_facts if f["slips"] >= 2]
    team = {k: round(sum(r["quarter_totals"][k] for r in reps), 2) for k in ("won", "commit", "best_case", "pipeline")}
    team_quota = sum(r["quota"] for r in reps if r.get("quota")) or None
    out = {"as_of": now.replace(microsecond=0).isoformat(), "quarter": quarter_label(now), "reps": reps,
           "team": team, "team_quota": team_quota, "suggested_commit": round(sum(r["suggested_commit"] for r in reps), 2),
           "top_deals": top, "slipped_twice": slipped, "flags": [f"{r['owner']}: {r['flag']}" for r in reps if r.get("flag")]}
    out["team_coverage"] = round((team["won"] + team["commit"]) / team_quota, 2) if team_quota else None
    fallback = "\n".join([
        f"- Team commit {money(team['commit'])} vs suggested {money(out['suggested_commit'])}; won {money(team['won'])}"
        + (f" of {money(team_quota)}." if team_quota else "."),
        f"- {len(out['flags'])} rep calls flagged; {len(slipped)} deals slipped twice or more.",
        f"- Inspect first: {top[0]['name']} ({money(top[0]['amount'])})." if top else "- No open deals to inspect.",
    ])
    out["summary"], out["summary_source"] = writer.narrate(
        ctx, "Write 3 short bullets for a sales manager preparing the team forecast call. Use only these facts.",
        {"team": team, "team_quota": team_quota, "suggested": out["suggested_commit"], "flags": out["flags"],
         "top_deals": [(f["name"], f["amount"], f["risk"]) for f in top]}, fallback, max_words=90)
    return out


def format_manager(p: dict) -> str:
    t = p["team"]
    lines = [f"*Forecast rollup* | {p['quarter']}",
             f"Team: won {money(t['won'])} | commit {money(t['commit'])} | suggested {money(p['suggested_commit'])} | "
             f"best case {money(t['best_case'])} | pipeline {money(t['pipeline'])}"
             + (f" | quota {money(p['team_quota'])}, coverage {p['team_coverage']}x" if p.get("team_quota") else "")]
    for r in p["reps"]:
        q = r["quarter_totals"]
        cov = f"{r['coverage']}x" if r.get("coverage") is not None else "n/a"
        lines.append(f"- {r['owner']}: quota {money(r.get('quota'))} | won {money(q['won'])} | commit {money(q['commit'])} | "
                     f"suggested {money(r['suggested_commit'])} | coverage {cov}" + (f" | {r['flag']}" if r.get("flag") else ""))
    if p["top_deals"]:
        lines.append("Inspect on the call:")
        for i, f in enumerate(p["top_deals"], 1):
            risk = f"risk {f['risk']}" if f["risk"] is not None else "not inspected"
            lines.append(f"{i}. {f['name']} ({f['owner']}) {money(f['amount'])} | {f['bucket'].replace('_', ' ')} | {risk}")
    if p["slipped_twice"]:
        lines.append("Slipped twice or more: " + ", ".join(f"{f['name']} ({f['slips']}x)" for f in p["slipped_twice"]))
    lines.append("Summary:\n" + p["summary"])
    return "\n".join(lines)


# ---------- exec level ----------
def exec_prep(ctx, now: datetime | None = None) -> dict:
    now = _now(now)
    m = manager_prep(ctx, now)
    qs, qe = quarter_bounds(now)
    elapsed = max(0.0, min(1.0, (now - qs).total_seconds() / (qe - qs).total_seconds()))
    quota = m["team_quota"]
    pace = round(quota * elapsed, 2) if quota else None
    t = m["team"]
    prev = previous_snapshot(ctx, now)
    wow = None
    if prev:
        po = prev.get("org", {})
        wow = {k: round(t[k] - float(po.get(k, 0)), 2) for k in ("won", "commit", "best_case", "pipeline")}
    swings = []
    for c in changes(ctx, "", 7, now):
        for x in c["changes"]:
            if x["kind"] in ("into_commit", "out_of_commit", "closed_won", "closed_lost", "new"):
                swings.append({"name": c["name"], "owner": c["owner"], "amount": c["amount"], "change": x["text"]})
            elif x["kind"] == "amount":
                swings.append({"name": c["name"], "owner": c["owner"], "amount": abs(x["to"] - x["from"]), "change": x["text"]})
    swings.sort(key=lambda s: -s["amount"])
    risks = sorted([f for f in m["top_deals"] if f["risk"] is not None], key=lambda f: -f["risk"])[:5]
    out = {"as_of": m["as_of"], "quarter": m["quarter"], "org": t, "quota": quota,
           "attainment_pct": round(100 * t["won"] / quota, 1) if quota else None,
           "elapsed_pct": round(100 * elapsed, 1), "linear_pace": pace,
           "pace_gap": round(t["won"] - pace, 2) if pace is not None else None,
           "forecast_pct": round(100 * (t["won"] + t["commit"]) / quota, 1) if quota else None,
           "wow": wow, "swings": swings[:5], "risks": [{"name": f["name"], "owner": f["owner"], "amount": f["amount"],
                                                          "risk": f["risk"]} for f in risks],
           "suggested_commit": m["suggested_commit"], "flags": m["flags"]}
    gap = out["pace_gap"]
    fallback = "\n".join([
        (f"- Won {money(t['won'])} of {money(quota)} ({out['attainment_pct']}%) with {out['elapsed_pct']}% of the quarter gone; "
         f"{'ahead of' if gap >= 0 else 'behind'} linear pace by {money(abs(gap))}.") if quota else
        f"- Won {money(t['won'])}; no quota set.",
        f"- Won plus commit {money(t['won'] + t['commit'])}"
        + (f" ({out['forecast_pct']}% of quota)" if quota else "") + f"; suggested commit {money(m['suggested_commit'])}.",
        f"- Biggest swing: {swings[0]['name']} ({swings[0]['change']})." if swings else "- No major swings this week.",
    ])
    out["summary"], out["summary_source"] = writer.narrate(
        ctx, "Write 3 short bullets for a revenue leader on where the quarter stands. Use only these facts.",
        {k: out[k] for k in ("org", "quota", "attainment_pct", "elapsed_pct", "pace_gap", "wow", "swings", "risks")},
        fallback, max_words=90)
    return out


def format_exec(p: dict) -> str:
    o = p["org"]
    lines = [f"*Quarter view* | {p['quarter']} | {p['elapsed_pct']}% elapsed"]
    if p.get("quota"):
        lines.append(f"Won {money(o['won'])} of {money(p['quota'])} ({p['attainment_pct']}%) | linear pace {money(p['linear_pace'])} | "
                     f"{'ahead' if p['pace_gap'] >= 0 else 'behind'} by {money(abs(p['pace_gap']))}")
    else:
        lines.append(f"Won {money(o['won'])} | no quota set")
    lines.append(f"Commit {money(o['commit'])} | suggested {money(p['suggested_commit'])} | best case {money(o['best_case'])} | "
                 f"pipeline {money(o['pipeline'])}")
    if p.get("wow"):
        w = p["wow"]
        sign = lambda v: ("+" if v >= 0 else "-") + money(abs(v))
        lines.append(f"Week over week: won {sign(w['won'])} | commit {sign(w['commit'])} | best case {sign(w['best_case'])} | "
                     f"pipeline {sign(w['pipeline'])}")
    if p["swings"]:
        lines.append("Swings: " + "; ".join(f"{s['name']} ({s['change']})" for s in p["swings"]))
    if p["risks"]:
        lines.append("Risks: " + "; ".join(f"{r['name']} ({r['owner']}) risk {r['risk']}" for r in p["risks"]))
    lines.append("Summary:\n" + p["summary"])
    return "\n".join(lines)


# ---------- snapshots ----------
def snapshot(ctx, m: dict) -> dict:
    snap = {"as_of": m["as_of"], "org": m["team"],
            "reps": {r["owner"]: {**r["quarter_totals"], "suggested": r["suggested_commit"]} for r in m["reps"]}}
    snaps = ctx.store.get_state(SNAP_KEY, []) or []
    snaps = [s for s in snaps if s["as_of"][:10] != snap["as_of"][:10]] + [snap]
    ctx.store.set_state(SNAP_KEY, snaps[-26:])
    return snap


def previous_snapshot(ctx, now: datetime) -> dict | None:
    """Latest snapshot at least 5 days older than now (last week's call)."""
    snaps = ctx.store.get_state(SNAP_KEY, []) or []
    old = [s for s in snaps if (pipeline.parse_dt(s["as_of"]) or now) <= now - timedelta(days=5)]
    return old[-1] if old else None


# ---------- daily change alerts ----------
def change_alerts(ctx, now: datetime | None = None) -> list[dict]:
    """Deals that entered or left commit, moved amount by more than the threshold, or slid out of the quarter
    in the last day. Each alert fires once."""
    now = _now(now)
    since = now - timedelta(days=1)
    qs, qe = quarter_bounds(now)
    pct = float(cfg(ctx, "amount_move_pct", 20)) / 100
    seen = set(ctx.store.get_state(ALERT_KEY, []) or [])
    out = []
    for d in ctx.store.select("deals"):
        for x in deal_changes(ctx, d, since):
            text = None
            if x["kind"] in ("into_commit", "out_of_commit"):
                text = x["text"]
            elif x["kind"] == "amount" and x["from"] and abs(x["to"] - x["from"]) / x["from"] > pct:
                text = x["text"]
            elif x["kind"] == "close_date":
                old_in = qs <= pipeline.parse_dt(x["from"]) < qe
                new_in = qs <= pipeline.parse_dt(x["to"]) < qe
                if old_in and not new_in and x.get("later"):
                    text = f"close date moved out of the quarter ({x['from']} -> {x['to']})"
            if not text:
                continue
            key = f"{d['id']}|{x['kind']}|{x.get('to', '')}|{bucket(ctx, d)}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"deal_id": d["id"], "name": d.get("name") or d["id"], "owner": d.get("owner"),
                        "amount": amt(d), "alert": text})
    ctx.store.set_state(ALERT_KEY, sorted(seen)[-2000:])
    return out


def format_alerts(alerts: list[dict]) -> str:
    lines = [f"*Forecast changes: {len(alerts)}*"]
    lines += [f"- {a['name']} ({a['owner']}) {money(a['amount'])}: {a['alert']}" for a in alerts]
    return "\n".join(lines)


def agenda(ctx, level: str = "manager", owner: str = "", now: datetime | None = None) -> dict:
    """Ordered call agenda with time boxes, built from the prep at that level."""
    level = (level or "manager").lower()
    if level == "ae":
        p = ae_prep(ctx, owner, now)
        items = [("Numbers: commit vs suggested", 3)] + [(f"Deal: {f['name']}", 4) for f in p["commit_deals"][:5]] + \
                [("Changes since last week", 3), ("What would move a best-case deal into commit", 3)]
        return {"level": "ae", "owner": owner, "items": [{"topic": t, "minutes": m} for t, m in items],
                "total_minutes": sum(m for _, m in items), "prep": format_ae(p)}
    if level == "exec":
        p = exec_prep(ctx, now)
        items = [("Pace vs linear quarter", 5), ("Week-over-week movement", 5)] + \
                [(f"Swing: {s['name']}", 3) for s in p["swings"][:3]] + [(f"Risk: {r['name']}", 3) for r in p["risks"][:3]] + \
                [("Decisions and asks", 5)]
        return {"level": "exec", "items": [{"topic": t, "minutes": m} for t, m in items],
                "total_minutes": sum(m for _, m in items), "prep": format_exec(p)}
    p = manager_prep(ctx, now)
    items = [("Team number vs suggested", 5)] + [(f"Rep: {r['owner']}", 5) for r in p["reps"]] + \
            [(f"Inspect: {f['name']}", 4) for f in p["top_deals"]] + [("Slipped deals: keep or move", 4)]
    return {"level": "manager", "items": [{"topic": t, "minutes": m} for t, m in items],
            "total_minutes": sum(m for _, m in items), "prep": format_manager(p)}
