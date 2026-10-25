"""Stack Audit engine: utilization, overlap, coverage, renewals and savings, all computed from the inventory."""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from gtm_core import pipeline, writer

ALERT_KEY = "stack_audit:renewal_alerts"
POSITIVE = {"meeting", "opportunity", "closed_won", "reply_positive"}


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def _now(now):
    return now or datetime.now(timezone.utc)


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    return yaml.safe_load(open(path).read()) or {}


def cap_map(ctx) -> dict:
    return _yaml(str(ctx.manifest.path(cfg(ctx, "capability_map", "skill/references/capability-map.yaml")))).get("capabilities", {})


# ---------- inventory ----------
def _num(v, cast=float):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return cast(float(str(v).replace("$", "").replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if str(x).strip()]
    return [x.strip().lower() for x in str(v or "").replace(",", ";").split(";") if x.strip()]


def resolve(ctx, file: str | None) -> Path:
    p = Path(file) if file else ctx.manifest.path(cfg(ctx, "inventory_file", "sample/inventory.csv"))
    return p if p.is_absolute() or p.exists() else ctx.manifest.path(str(p))


def load_inventory(ctx, file: str | None = None) -> list[dict]:
    path = resolve(ctx, file)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        rows = data if isinstance(data, list) else data.get("tools", [])
    else:
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        name = (r.get("tool") or "").strip()
        if not name:
            continue
        out.append({"tool": name, "capabilities": _list(r.get("capabilities") or r.get("category")),
                    "owner": (r.get("owner") or "").strip() or None,
                    "seats_purchased": _num(r.get("seats_purchased"), int), "seats_active": _num(r.get("seats_active_30d"), int),
                    "logins_30d": _num(r.get("logins_30d"), int), "logins_90d": _num(r.get("logins_90d"), int),
                    "annual_cost": _num(r.get("annual_cost")), "renewal_date": (r.get("renewal_date") or "").strip() or None,
                    "notice_days": _num(r.get("notice_days"), int), "contract_term": (r.get("contract_term") or "").strip() or None,
                    "integrations": _list(r.get("integrations")), "data_exported_to": _list(r.get("data_exported_to"))})
    return out


def metrics(t: dict) -> dict:
    cost, bought, active = t["annual_cost"], t["seats_purchased"], t["seats_active"]
    util = round(active / bought, 3) if bought and active is not None else None
    trend = None
    if t["logins_30d"] is not None and t["logins_90d"]:
        avg = t["logins_90d"] / 3
        trend = round((t["logins_30d"] - avg) / avg, 3) if avg else None
    return {"cost_per_seat": round(cost / bought, 2) if cost is not None and bought else None,
            "cost_per_active_seat": round(cost / active, 2) if cost is not None and active else None,
            "utilization": util, "login_trend": trend}


def renewal(t: dict, now: datetime) -> dict:
    r = pipeline.parse_dt(t["renewal_date"])
    if r is None:
        return {"renewal_date": None, "notice_deadline": None, "days_to_notice": None, "days_to_renewal": None}
    from datetime import timedelta
    deadline = r - timedelta(days=t["notice_days"] or 0)
    return {"renewal_date": r.date().isoformat(), "notice_deadline": deadline.date().isoformat(),
            "days_to_notice": (deadline.date() - now.date()).days, "days_to_renewal": (r.date() - now.date()).days}


def enriched(ctx, file: str | None = None, now: datetime | None = None) -> list[dict]:
    now = _now(now)
    return [{**t, **metrics(t), **renewal(t, now)} for t in load_inventory(ctx, file)]


# ---------- overlap and coverage ----------
def overlap(tools: list[dict]) -> dict[str, list[dict]]:
    caps: dict[str, list[dict]] = {}
    for t in tools:
        for c in t["capabilities"]:
            caps.setdefault(c, []).append({"tool": t["tool"], "utilization": t["utilization"], "annual_cost": t["annual_cost"]})
    return {c: ts for c, ts in sorted(caps.items()) if len(ts) >= 2}


def _stronger(a: dict, b: dict) -> bool:
    """Is tool b a better home for a shared capability than tool a (higher utilization, then cheaper per active seat)?"""
    ua, ub = a.get("utilization") or 0, b.get("utilization") or 0
    if ub != ua:
        return ub > ua
    ca, cb = a.get("cost_per_active_seat"), b.get("cost_per_active_seat")
    return ca is not None and cb is not None and cb < ca


def coverage(ctx, t: dict, tools: list[dict]) -> list[dict]:
    m = cap_map(ctx)
    out = []
    for c in t["capabilities"]:
        info = m.get(c, {"agent": None, "replace": "none", "condition": "not in the capability map; review by hand"})
        others = [o["tool"] for o in tools if o["tool"] != t["tool"] and c in o["capabilities"] and _stronger(t, o)]
        out.append({"capability": c, "agent": info.get("agent"), "replace": info.get("replace", "none"),
                    "condition": info.get("condition", ""), "covered_by_tools": others})
    return out


# ---------- recommendations ----------
def recommend(ctx, t: dict, tools: list[dict]) -> dict:
    cov = coverage(ctx, t, tools)
    agent_full = [c for c in cov if c["replace"] == "full"]
    by_tool = [c for c in cov if c["replace"] != "full" and c["covered_by_tools"]]
    gaps = [c for c in cov if c["replace"] != "full" and not c["covered_by_tools"]]
    partial = [c["capability"] for c in cov if c["replace"] == "partial"]
    conditions = sorted({c["condition"] for c in agent_full + [c for c in cov if c["replace"] == "partial"] if c["condition"]})
    cost = t["annual_cost"]
    evidence = []
    if t["utilization"] is not None:
        evidence.append(f"utilization {round(100 * t['utilization'])}% ({t['seats_active']} of {t['seats_purchased']} seats)")
    if t["cost_per_active_seat"] is not None:
        evidence.append(f"cost per active seat ${t['cost_per_active_seat']:,.0f}")
    if t["logins_30d"] is not None:
        evidence.append(f"{t['logins_30d']} logins in 30 days")
    rec = {"tool": t["tool"], "owner": t["owner"], "annual_cost": cost, "evidence": evidence,
           "coverage": cov, "gaps": [c["capability"] for c in gaps], "partial": partial,
           "notice_deadline": t["notice_deadline"], "days_to_notice": t["days_to_notice"]}
    if not gaps and (agent_full or by_tool):
        if by_tool:
            into = sorted({x for c in by_tool for x in c["covered_by_tools"]})
            rec.update(action="consolidate", into=into, savings=cost,
                       condition="; ".join(conditions + [f"move {', '.join(c['capability'] for c in by_tool)} work into {', '.join(into)}"]))
        else:
            rec.update(action="cut", into=sorted({c["agent"] for c in agent_full}), savings=cost, condition="; ".join(conditions))
        if cost is None:
            rec["note"] = "annual cost unknown: savings not counted"
        return rec
    bought, active = t["seats_purchased"], t["seats_active"]
    if bought and active is not None:
        keep = math.ceil(active * (1 + float(cfg(ctx, "seat_buffer_pct", 10)) / 100))
        if bought > keep:
            per = t["cost_per_seat"]
            rec.update(action="downsize", keep_seats=keep, excess_seats=bought - keep,
                       savings=round(per * (bought - keep), 2) if per is not None else None,
                       condition=f"reassign or remove {bought - keep} inactive seats before the notice deadline")
            if gaps:
                rec["condition"] += f"; cannot cut: no replacement for {', '.join(c['capability'] for c in gaps)}"
            if per is None:
                rec["note"] = "annual cost unknown: savings not counted"
            return rec
    rec.update(action="keep", savings=0, condition="" if not gaps else f"no replacement for {', '.join(c['capability'] for c in gaps)}")
    return rec


def scenarios(ctx, file: str | None = None, now: datetime | None = None) -> dict:
    tools = enriched(ctx, file, now)
    recs = [recommend(ctx, t, tools) for t in tools]
    known = [t for t in tools if t["annual_cost"] is not None]
    by_action = {}
    for r in recs:
        a = by_action.setdefault(r["action"], {"tools": [], "savings": 0.0})
        a["tools"].append(r["tool"])
        a["savings"] = round(a["savings"] + (r["savings"] or 0), 2)
    total = round(sum(r["savings"] or 0 for r in recs), 2)
    unknown = [t["tool"] for t in tools if t["annual_cost"] is None]
    return {"recommendations": recs, "by_action": by_action, "total_savings": total,
            "total_spend": round(sum(t["annual_cost"] for t in known), 2),
            "savings_pct": round(100 * total / sum(t["annual_cost"] for t in known), 1) if known else None,
            "unknown_cost": unknown,
            "note": (f"{len(unknown)} tool(s) with unknown cost excluded from totals: {', '.join(unknown)}" if unknown else "")}


def summary(ctx, file: str | None = None, now: datetime | None = None) -> dict:
    tools = enriched(ctx, file, now)
    known = [t for t in tools if t["annual_cost"] is not None]
    low = float(cfg(ctx, "low_utilization_pct", 50)) / 100
    bought = sum(t["seats_purchased"] or 0 for t in tools)
    active = sum(t["seats_active"] or 0 for t in tools if t["seats_purchased"])
    return {"tools": len(tools), "total_spend": round(sum(t["annual_cost"] for t in known), 2),
            "unknown_cost": [t["tool"] for t in tools if t["annual_cost"] is None],
            "seats_purchased": bought, "seats_active": active,
            "utilization": round(active / bought, 3) if bought else None,
            "low_utilization": [t["tool"] for t in tools if t["utilization"] is not None and t["utilization"] < low],
            "overlapping_capabilities": len(overlap(tools)),
            "rows": [{k: t[k] for k in ("tool", "owner", "annual_cost", "seats_purchased", "seats_active", "utilization",
                                         "cost_per_active_seat", "login_trend", "renewal_date", "notice_deadline")}
                     for t in sorted(tools, key=lambda t: -(t["annual_cost"] or 0))]}


def calendar(ctx, days: int = 120, file: str | None = None, now: datetime | None = None) -> list[dict]:
    rows = []
    for t in enriched(ctx, file, now):
        d = t["days_to_notice"]
        if d is None or d > days or (t["days_to_renewal"] is not None and t["days_to_renewal"] < 0):
            continue
        rows.append({"tool": t["tool"], "owner": t["owner"], "annual_cost": t["annual_cost"], "renewal_date": t["renewal_date"],
                     "notice_deadline": t["notice_deadline"], "days_to_notice": d,
                     "status": "notice deadline passed: renews unless notice was already given" if d < 0 else f"{d} days to notice"})
    return sorted(rows, key=lambda r: r["days_to_notice"])


def renewal_alerts(ctx, file: str | None = None, now: datetime | None = None) -> list[dict]:
    """Tools that crossed a new alert band (or passed the deadline) since the last run. Each band fires once."""
    bands = sorted(int(b) for b in cfg(ctx, "alert_bands", [120, 90, 60, 30]))
    seen = set(ctx.store.get_state(ALERT_KEY, []) or [])
    out = []
    for r in calendar(ctx, max(bands), file, now):
        d = r["days_to_notice"]
        band = "passed" if d < 0 else str(min(b for b in bands if d <= b))
        key = f"{r['tool']}|{r['notice_deadline']}|{band}"
        if key in seen:
            continue
        seen.add(key)
        out.append({**r, "band": band})
    ctx.store.set_state(ALERT_KEY, sorted(seen))
    return out


# ---------- side by side ----------
def _read_accounts(path: Path) -> list[str]:
    text = path.read_text()
    if path.suffix.lower() == ".csv" and "," in text.splitlines()[0]:
        rows = list(csv.DictReader(text.splitlines()))
        key = next((k for k in ("account_id", "domain", "id", "account") if rows and k in rows[0]), None)
        vals = [r[key] for r in rows] if key else []
    else:
        vals = text.splitlines()
    return sorted({v.strip().lower().removeprefix("www.") for v in vals if v and v.strip() and not v.startswith("#")})


def agent_top_accounts(ctx, tiers=("A", "B")) -> list[str]:
    rows = ctx.store.query("SELECT account_id, tier FROM scores s WHERE id = (SELECT MAX(id) FROM scores s2 "
                           "WHERE s2.account_id = s.account_id)")
    return sorted({r["account_id"].lower() for r in rows if r["tier"] in tiers})


def converted(ctx, account_id: str) -> bool:
    o = ctx.store.query("SELECT outcome FROM outcomes WHERE LOWER(account_id)=?", (account_id,))
    if any(r["outcome"] in POSITIVE for r in o):
        return True
    return bool(ctx.store.select("deals", "LOWER(account_id)=?", (account_id,)))


def compare(ctx, tool: str, file: str) -> dict:
    p = Path(file)
    if not p.exists():
        return {"error": f"file not found: {file}"}
    theirs = _read_accounts(p)
    ours = agent_top_accounts(ctx)
    both = sorted(set(theirs) & set(ours))
    tool_only = sorted(set(theirs) - set(ours))
    tool_conv = [a for a in theirs if converted(ctx, a)]
    tool_only_conv = [a for a in tool_only if converted(ctx, a)]
    caught = len(tool_conv) - len(tool_only_conv)
    share = round(100 * caught / len(tool_conv), 1) if tool_conv else None
    need = float(cfg(ctx, "side_by_side_min_overlap", 70))
    return {"tool": tool, "tool_accounts": len(theirs), "agent_accounts": len(ours),
            "overlap_pct": round(100 * len(both) / len(theirs), 1) if theirs else None, "both": both,
            "tool_only": tool_only, "tool_only_converted": tool_only_conv, "agent_only": sorted(set(ours) - set(theirs)),
            "converted_caught_pct": share, "condition_met": share is not None and share >= need,
            "rule": f"agents must surface at least {need:.0f}% of the tool's converted accounts"}


# ---------- memo ----------
def memo(ctx, tool: str, file: str | None = None, side_by_side: dict | None = None, now: datetime | None = None) -> dict:
    now = _now(now)
    s = scenarios(ctx, file, now)
    r = next((x for x in s["recommendations"] if x["tool"].lower() == tool.lower()), None)
    if not r:
        return {"error": f"tool '{tool}' not in the inventory"}
    act = r["action"]
    if act == "consolidate":
        what = f"consolidate {r['tool']} into {', '.join(r['into'])}"
    elif act == "downsize":
        what = f"downsize {r['tool']} to {r['keep_seats']} seats"
    else:
        what = f"{act} {r['tool']}"
    saving = f"${r['savings']:,.0f} a year" if r.get("savings") else ("unknown savings (cost not on file)" if act != "keep" else "no savings")
    overlaps = [f"{c['capability']} ({', '.join(filter(None, [c['agent'] if c['replace'] == 'full' else None] + c['covered_by_tools'])) or 'no other coverage'})"
                for c in r["coverage"]]
    if side_by_side:
        sbs = (f"{side_by_side['overlap_pct']}% list overlap; agents caught {side_by_side['converted_caught_pct']}% of the "
               f"tool's converted accounts; {len(side_by_side['tool_only_converted'])} converted accounts only the tool found")
    else:
        sbs = "not run yet"
    deadline = (f"notice by {r['notice_deadline']} ({r['days_to_notice']} days)" if r.get("notice_deadline") else "renewal date unknown")
    body = "\n".join([
        f"Recommendation: {what}, saving {saving}.",
        f"Why: {'; '.join(r['evidence']) or 'no usage data on file'}.",
        f"Coverage: {'; '.join(overlaps)}.",
        f"Gaps: {', '.join(r['gaps'] + r['partial']) or 'none'}.",
        f"Condition before acting: {r.get('condition') or 'none'}.",
        f"Side by side: {sbs}.",
        f"Deadline: {deadline}.",
        f"Owner: {r['owner'] or 'unknown'}.",
    ])
    subject = f"Recommendation: {what}" + (f" before {r['notice_deadline']}" if r.get("notice_deadline") else "")
    lead, source = writer.narrate(ctx, "Write a 2-sentence opening for an internal tool-cut memo. Use only these facts.",
                                  {"recommendation": what, "savings": r.get("savings"), "evidence": r["evidence"],
                                   "condition": r.get("condition"), "deadline": r.get("notice_deadline")},
                                  f"{what[0].upper() + what[1:]} saves {saving}. {('Act before ' + r['notice_deadline'] + '.') if r.get('notice_deadline') else ''}".strip(),
                                  max_words=60)
    text = f"{lead}\n\n{body}"
    did = ctx.store.add_draft(ctx.manifest.id, "tool_cut_memo", text, subject=subject, source=source,
                              meta={"tool": r["tool"], "action": act, "savings": r.get("savings")})
    return {"draft_id": did, "subject": subject, "body": text, "recommendation": r, "source": source}


# ---------- formats ----------
def money(v):
    return "unknown" if v is None else f"${v:,.0f}"


def format_alerts(alerts: list[dict]) -> str:
    lines = [f"*Stack Audit: {len(alerts)} renewal notice deadline(s)*"]
    for a in alerts:
        lines.append(f"- {a['tool']} ({money(a['annual_cost'])}/yr, owner {a['owner'] or 'unknown'}): notice by "
                     f"{a['notice_deadline']} | {a['status']} | renews {a['renewal_date']}")
    return "\n".join(lines)


def format_utilization(s: dict, sc: dict) -> str:
    lines = [f"*Stack Audit: monthly utilization* | {s['tools']} tools | spend {money(s['total_spend'])}"
             + (f" (+{len(s['unknown_cost'])} unknown)" if s["unknown_cost"] else ""),
             f"Seats: {s['seats_active']} active of {s['seats_purchased']} purchased"
             + (f" ({round(100 * s['utilization'])}%)" if s["utilization"] is not None else "")]
    for r in s["rows"]:
        u = f"{round(100 * r['utilization'])}%" if r["utilization"] is not None else "n/a"
        lines.append(f"- {r['tool']}: {money(r['annual_cost'])} | utilization {u} | per active seat {money(r['cost_per_active_seat'])}")
    lines.append(f"Possible savings: {money(sc['total_savings'])} ({sc['savings_pct']}% of known spend)"
                 + (f". {sc['note']}" if sc["note"] else ""))
    return "\n".join(lines)
