"""Deal Inspection engine: rule-based risk, MEDDPICC gaps and recommendations. The model only narrates."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache

import yaml

from gtm_core import meddpicc, personas, pipeline, profile
from gtm_core.scoring import IcpProfile, icp_fit
from gtm_core.store import now_iso

DEFAULT_MAX_DAYS = {"discovery": 30, "qualification": 30, "evaluation": 45, "proposal": 30, "negotiation": 30, "commit": 21}
STAGE_ORDER = ["discovery", "qualification", "evaluation", "proposal", "negotiation", "commit"]
DEFAULT_POINTS = {"stage_overdue": 20, "no_activity": 20, "close_date_past": 15, "per_slip": 10, "next_step_missing": 10,
                  "next_step_overdue": 10, "per_missing_element": 6, "per_unconfirmed_element": 3, "single_threaded": 10,
                  "no_senior_contact": 5, "negative_evidence": 15, "wrong_fit": 25}


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    return yaml.safe_load(open(path).read()) or {}


@lru_cache(maxsize=8)
def _icp(path: str) -> IcpProfile:
    return IcpProfile.from_yaml(path)


def rules(ctx) -> dict:
    return _yaml(str(ctx.manifest.path(ctx.manifest.config.get("rules", "skill/references/stage-rules.yaml"))))


def stage_key(ctx, stage: str | None) -> str:
    return meddpicc.stage_key(stage, rules(ctx).get("stage_aliases"))


def _now(now):
    return now or datetime.now(timezone.utc)


def find_deal(ctx, ref: str) -> dict | None:
    d = ctx.store.get("deals", ref)
    if d:
        return d
    rows = ctx.store.select("deals", "crm_id=? OR LOWER(name)=? OR account_id=?", (ref, ref.lower(), ref))
    rows = [r for r in rows if pipeline.is_open(r)] or rows
    return rows[0] if rows else None


def negative_evidence(ctx, deal: dict) -> list[str]:
    phrases = [p.lower() for p in rules(ctx).get("negative_phrases", [])]
    out = []

    def hit(text: str) -> bool:
        t = (text or "").lower()
        return any(re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", t) for p in phrases)

    for e, v in meddpicc.normalize(deal.get("meddpicc")).items():
        if v["evidence"] and hit(v["evidence"]):
            out.append(f"{meddpicc.LABELS[e]}: {v['evidence'][:160]}")
    for ins in ctx.store.insights("objection", deal_id=deal["id"]):
        ev = ins.get("evidence") or ""
        if hit(ev) and ev not in out:
            out.append(ev[:200])
    return out[:5]


def stakeholders(ctx, deal: dict) -> dict:
    people: dict[str, str] = {}
    if deal.get("account_id"):
        for c in ctx.store.select("contacts", "account_id=?", (deal["account_id"],)):
            people[(c.get("name") or c.get("email") or c["id"]).lower()] = c.get("seniority") or personas.seniority(c.get("title"))
    reps = {r.lower() for r in profile.rep_names(ctx)}
    for m in ctx.store.select("meetings", "deal_id=?", (deal["id"],)):
        for a in m.get("attendees") or []:
            name = str(a).strip()
            if name and name.lower() not in reps:
                people.setdefault(name.lower(), "unknown")
    ranks = [personas.SENIORITY_RANK.get(s, 0) for s in people.values()]
    return {"count": len(people), "max_rank": max(ranks, default=0),
            "senior": sum(1 for r in ranks if r >= personas.SENIORITY_RANK["director"])}


def account_fit(ctx, deal: dict) -> tuple[float | None, list[str]]:
    acct = ctx.store.account(deal["account_id"]) if deal.get("account_id") else None
    if not acct:
        return None, ["account not in store"]
    return icp_fit(acct, _icp(str(profile.icp_path(ctx))))


def inspect(ctx, deal: dict, now: datetime | None = None) -> dict:
    """Inspect one deal. Pure read: nothing is written."""
    now = _now(now)
    r = rules(ctx)
    pts = {**DEFAULT_POINTS, **r.get("risk_points", {})}
    key = stage_key(ctx, deal.get("stage"))
    drivers: list[tuple[int, str]] = []
    flags: list[str] = []

    days_in_stage = pipeline.days_since(deal.get("stage_entered_at") or deal.get("created_at"), now)
    max_stage = int(r.get("max_days_in_stage", DEFAULT_MAX_DAYS).get(key, 30))
    if days_in_stage is not None and days_in_stage > max_stage:
        drivers.append((pts["stage_overdue"], f"{days_in_stage} days in {key} (limit {max_stage})"))

    act_ref = deal.get("last_activity_at") or deal.get("stage_entered_at") or deal.get("created_at")
    idle = pipeline.days_since(act_ref, now)
    max_idle = int(r.get("max_days_without_activity", 14))
    if idle is not None and idle > max_idle:
        drivers.append((pts["no_activity"], f"no activity {idle} days"))

    to_close = pipeline.days_until(deal.get("close_date"), now)
    if to_close is not None and to_close < 0:
        drivers.append((pts["close_date_past"], f"close date {deal['close_date'][:10]} has passed"))
    slips = pipeline.slips(ctx.store.deal_history(deal["id"]))
    if slips:
        drivers.append((pts["per_slip"] * min(slips, 2), f"close date moved later {slips}x"))

    if not (deal.get("next_step") or "").strip():
        drivers.append((pts["next_step_missing"], "no next step"))
    else:
        ns_days = pipeline.days_until(deal.get("next_step_date"), now)
        if ns_days is not None and ns_days < 0:
            drivers.append((pts["next_step_overdue"], f"next step overdue since {deal['next_step_date'][:10]}"))

    md = meddpicc.score(deal.get("meddpicc"))
    gaps = meddpicc.gaps(deal.get("meddpicc"), deal.get("stage"), r.get("meddpicc_requirements"), r.get("stage_aliases"))
    missing = [g for g in gaps if g["kind"] == "missing"]
    unconf = [g for g in gaps if g["kind"] == "unconfirmed"]
    if missing:
        drivers.append((pts["per_missing_element"] * len(missing),
                        "missing data: " + ", ".join(g["label"].lower() for g in missing)))
    if unconf:
        drivers.append((pts["per_unconfirmed_element"] * len(unconf),
                        "unconfirmed: " + ", ".join(g["label"].lower() for g in unconf)))

    negative = negative_evidence(ctx, deal)
    if negative:
        drivers.append((pts["negative_evidence"], "negative evidence: " + negative[0][:90]))

    sh = stakeholders(ctx, deal)
    if sh["count"] < 2:
        drivers.append((pts["single_threaded"], f"single-threaded ({sh['count']} buyer contact{'s' if sh['count'] != 1 else ''} known)"))
    senior_from = r.get("senior_from_stage", "evaluation")
    need_rank = personas.SENIORITY_RANK.get(r.get("senior_min_seniority", "director"), 3)
    if STAGE_ORDER.index(key) >= STAGE_ORDER.index(senior_from) and sh["max_rank"] < need_rank:
        drivers.append((pts["no_senior_contact"], "no director-level or above contact engaged"))

    fit, fit_reasons = account_fit(ctx, deal)
    floor = float(r.get("recommendation", {}).get("disqualify_when", {}).get("icp_below", 30))
    if fit is not None and fit < floor:
        drivers.append((pts["wrong_fit"], f"wrong fit: ICP {fit:.0f} ({fit_reasons[0]})"))

    drivers.sort(key=lambda d: -d[0])
    risk = min(100, sum(p for p, _ in drivers))
    rec, rule = recommend(ctx, risk, gaps, fit, idle, slips, negative)
    out = {
        "deal_id": deal["id"], "name": deal.get("name"), "owner": deal.get("owner"), "account_id": deal.get("account_id"),
        "stage": deal.get("stage"), "stage_key": key, "amount": deal.get("amount"), "close_date": deal.get("close_date"),
        "days_in_stage": days_in_stage, "days_idle": idle, "slips": slips, "risk": risk,
        "drivers": [d for _, d in drivers], "gaps": gaps, "meddpicc": md["elements"], "meddpicc_pct": md["pct"],
        "meddpicc_total": md["total"], "negative_evidence": negative, "stakeholders": sh,
        "icp_fit": fit, "recommendation": rec, "rule": rule, "flags": flags,
    }
    out["actions"] = actions(out)
    return out


def recommend(ctx, risk: int, gaps: list, fit, idle, slips: int, negative: list) -> tuple[str, str]:
    rc = rules(ctx).get("recommendation", {})
    dq = rc.get("disqualify_when", {})
    if fit is not None and "icp_below" in dq and fit < float(dq["icp_below"]):
        return "disqualify", f"ICP fit {fit:.0f} below {dq['icp_below']}"
    if idle is not None and "no_activity_days_over" in dq and idle > int(dq["no_activity_days_over"]):
        return "disqualify", f"no activity for {idle} days (over {dq['no_activity_days_over']})"
    if "slips_at_least" in dq and slips >= int(dq["slips_at_least"]):
        return "disqualify", f"close date slipped {slips} times"
    if negative and idle is not None and "negative_and_idle_days_over" in dq and idle > int(dq["negative_and_idle_days_over"]):
        return "disqualify", f"negative evidence and idle {idle} days"
    if risk >= int(rc.get("fix_when_risk_at_least", 30)):
        return "fix", f"risk {risk} at or above {rc.get('fix_when_risk_at_least', 30)}"
    if gaps:
        return "fix", f"{len(gaps)} MEDDPICC gap(s) for this stage"
    return "progress", "no rule triggered"


ACTION_PRIORITY = ["economic_buyer", "champion", "metrics", "identify_pain", "decision_process", "paper_process",
                   "decision_criteria", "competition"]
ACTION_FOR = {
    "economic_buyer": "Get the economic buyer on a call: ask {champ} who signs off at this amount and book 30 minutes with them.",
    "champion": "Test the champion: ask {champ} to set up the next meeting with their boss. No intro means no champion.",
    "metrics": "Agree a number with the buyer: today's cost of the problem and the target after go-live.",
    "decision_criteria": "Write down the buyer's must-haves and send them back for a yes.",
    "decision_process": "Map the steps and dates from now to signature with the buyer.",
    "paper_process": "Ask who handles procurement, legal and security review, and how long each takes.",
    "identify_pain": "Get the pain in the buyer's words: what breaks today and what it costs them.",
    "competition": "Ask what else they are looking at, including doing nothing.",
}


def actions(i: dict) -> list[str]:
    if i["recommendation"] == "progress":
        return []
    champ_ev = i["meddpicc"].get("champion", {}).get("evidence") or ""
    champ = champ_ev.split(":")[-1].strip() if champ_ev and len(champ_ev) < 40 else "your contact"
    out = []
    if i["recommendation"] == "disqualify":
        out.append(f"Review with the manager this week: {i['rule']}. Close it out or get a dated commitment from the buyer.")
    if any(d.startswith("close date") for d in i["drivers"]):
        out.append("Reset the close date with the buyer, based on their steps to signature.")
    for g in sorted(i["gaps"], key=lambda g: (g["kind"] != "missing", ACTION_PRIORITY.index(g["element"]))):
        if len(out) >= 3:
            break
        out.append(ACTION_FOR[g["element"]].format(champ=champ))
    if len(out) < 3 and any(d.startswith("single-threaded") for d in i["drivers"]):
        out.append("Add a second buyer contact: ask for the person who would run the rollout.")
    if len(out) < 3 and any(d.startswith("no activity") or d == "no next step" for d in i["drivers"]):
        out.append("Book a dated next step with the buyer before the end of the week.")
    return out[:3]


def record(ctx, i: dict) -> int:
    """Store the result as an insight so Revenue Pulse and other agents can read it."""
    return ctx.store.add_insight(ctx.manifest.id, "deal_inspection", i["deal_id"], {
        "risk": i["risk"], "recommendation": i["recommendation"], "gaps": [g["element"] for g in i["gaps"]],
        "flags": i["drivers"], "meddpicc_pct": i["meddpicc_pct"], "stage_key": i["stage_key"],
        "days_in_stage": i["days_in_stage"], "name": i["name"], "owner": i["owner"], "amount": i["amount"],
        "rule": i["rule"]}, evidence="; ".join(i["drivers"][:3]), deal_id=i["deal_id"], account_id=i["account_id"])


def open_deals(ctx, owner: str = "") -> list[dict]:
    deals = [d for d in ctx.store.select("deals") if pipeline.is_open(d)]
    if owner:
        deals = [d for d in deals if (d.get("owner") or "").lower() == owner.lower()]
    return deals


def inspect_all(ctx, now: datetime | None = None, owner: str = "", persist: bool = True) -> list[dict]:
    res = [inspect(ctx, d, now) for d in open_deals(ctx, owner)]
    res.sort(key=lambda i: -i["risk"])
    if persist:
        for i in res:
            record(ctx, i)
    return res


def _money(v) -> str:
    return f"${float(v):,.0f}" if v not in (None, "") else "$?"


def format_one(i: dict) -> str:
    lines = [f"{i['name']} | {i['stage']} | {_money(i['amount'])} | owner {i['owner']}",
             f"Risk {i['risk']}: " + (", ".join(i["drivers"][:4]) or "no drivers"),
             f"MEDDPICC {i['meddpicc_total']}/16"]
    if i["gaps"]:
        lines.append("Gaps: " + ", ".join(f"{g['label'].lower()} ({g['kind']})" for g in i["gaps"]))
    if i["negative_evidence"]:
        lines.append(f"Negative: \"{i['negative_evidence'][0]}\"")
    lines.append(f"Recommendation: {i['recommendation'].upper()} ({i['rule']})")
    lines += [f"{n}. {a}" for n, a in enumerate(i["actions"], 1)]
    return "\n".join(lines)


def format_report(results: list[dict], size: int = 25) -> str:
    if not results:
        return "*Deal Inspection*: no open deals."
    c = {k: sum(1 for i in results if i["recommendation"] == k) for k in ("progress", "fix", "disqualify")}
    lines = [f"*Deal Inspection: {len(results)} open deals* | progress {c['progress']}, fix {c['fix']}, disqualify {c['disqualify']}"]
    by_owner: dict[str, list] = {}
    for i in results[:size]:
        by_owner.setdefault(i["owner"] or "Unassigned", []).append(i)
    for owner in sorted(by_owner, key=lambda o: -max(i["risk"] for i in by_owner[o])):
        lines.append(f"*{owner}*")
        for i in by_owner[owner]:
            why = "; ".join(i["drivers"][:2])
            lines.append(f"- {i['name']} | {i['stage']} | risk {i['risk']} | {i['recommendation'].upper()}" + (f" | {why}" if why else ""))
    return "\n".join(lines)


def apply_evidence(ctx, handoff: dict) -> dict:
    """Merge call evidence into the stored MEDDPICC; queue the CRM write for approval."""
    p = handoff.get("payload") or {}
    deal = ctx.store.get("deals", p.get("deal_id") or handoff.get("ref"))
    if not deal:
        return {"handoff": handoff["id"], "skipped": "deal not found"}
    before = meddpicc.normalize(deal.get("meddpicc"))
    merged = meddpicc.merge_evidence(deal.get("meddpicc"), p.get("evidence") or {}, f"call:{p.get('meeting_id', '')}")
    changed = [e for e in meddpicc.ELEMENTS if merged[e]["score"] > before[e]["score"]]
    if not changed:
        return {"handoff": handoff["id"], "changed": []}
    ctx.store.upsert("deals", {"id": deal["id"], "meddpicc": merged})
    approval = None
    if deal.get("crm_id"):
        fmap = rules(ctx).get("crm_fields", {})
        approval = ctx.request_approval("deal_update", {
            "crm_id": deal["crm_id"], "deal": deal.get("name"),
            "fields": {fmap.get(e, f"meddpicc_{e}"): merged[e]["evidence"] for e in changed}},
            summary=f"{deal.get('name')}: MEDDPICC evidence from call for {', '.join(changed)}")
    return {"handoff": handoff["id"], "deal_id": deal["id"], "changed": changed, "approval": approval}


def set_element(ctx, deal: dict, element: str, evidence: str, confirmed: bool, source: str = "rep") -> dict:
    md = meddpicc.normalize(deal.get("meddpicc"))
    md[element] = {"score": 2 if confirmed else 1, "evidence": evidence.strip(), "source": source,
                   "updated_at": now_iso()}
    ctx.store.upsert("deals", {"id": deal["id"], "meddpicc": md})
    approval = None
    if deal.get("crm_id"):
        field = rules(ctx).get("crm_fields", {}).get(element, f"meddpicc_{element}")
        approval = ctx.request_approval("deal_update", {
            "crm_id": deal["crm_id"], "deal": deal.get("name"),
            "fields": {field: ("confirmed: " if confirmed else "") + evidence.strip()}},
            summary=f"{deal.get('name')}: set {meddpicc.LABELS[element]}")
    return {"deal_id": deal["id"], "element": element, "score": md[element]["score"], "approval": approval}
