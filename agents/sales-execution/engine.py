"""Sales Execution engine: pre-call briefs and deal-moving helpers, assembled from facts only."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from gtm_core import meddpicc, personas, pipeline, profile, transcripts, writer

GOAL_TEXT = {"metrics": "Agree on how success will be measured", "economic_buyer": "Confirm the economic buyer",
             "decision_criteria": "Pin down the decision criteria", "decision_process": "Map the decision process",
             "paper_process": "Start the paper process (legal, security, procurement)",
             "identify_pain": "Get the pain in their words, with a cost", "champion": "Test for a champion",
             "competition": "Find out what else they are considering"}


def _now(now):
    return now or datetime.now(timezone.utc)


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    return yaml.safe_load(open(path).read()) or {}


@lru_cache(maxsize=8)
def _playbook(path: str) -> dict[str, str]:
    text = open(path).read()
    out = {}
    for block in re.split(r"(?m)^## ", text)[1:]:
        head, _, body = block.partition("\n")
        out[head.strip().lower()] = body.strip()
    return out


def question_bank(ctx) -> dict:
    return _yaml(str(ctx.manifest.path(ctx.manifest.config.get("question_bank", "skill/references/question-bank.yaml"))))


def playbook(ctx) -> dict[str, str]:
    return _playbook(str(ctx.manifest.path(ctx.manifest.config.get("objection_playbook",
                                                                   "skill/references/objection-playbook.md"))))


# ---------- lookups ----------
def find_deal(ctx, ref: str) -> dict | None:
    d = ctx.store.get("deals", ref)
    if d:
        return d
    rows = ctx.store.select("deals", "crm_id=? OR account_id=? OR LOWER(name) LIKE ?", (ref, ref, f"%{ref.lower()}%"))
    rows.sort(key=lambda r: (not pipeline.is_open(r), r.get("close_date") or "9999"))
    return rows[0] if rows else None


def open_deal_for(ctx, account_id: str | None, deal_id: str | None = None) -> dict | None:
    if deal_id:
        d = ctx.store.get("deals", deal_id)
        if d:
            return d
    if not account_id:
        return None
    rows = [d for d in ctx.store.select("deals", "account_id=?", (account_id,)) if pipeline.is_open(d)]
    rows.sort(key=lambda r: r.get("close_date") or "9999")
    return rows[0] if rows else None


def find_meeting(ctx, ref: str) -> dict | None:
    m = ctx.store.get("meetings", ref)
    if m:
        return m
    rows = ctx.store.select("meetings", "LOWER(title) LIKE ? OR account_id=? OR deal_id=?",
                            (f"%{ref.lower()}%", ref, ref), order="started_at IS NULL, started_at DESC")
    return rows[0] if rows else None


def ordered_gaps(deal: dict | None) -> list[dict]:
    if not deal:
        return []
    gs = meddpicc.gaps(deal.get("meddpicc"), deal.get("stage"))
    order = {e: i for i, e in enumerate(meddpicc.ELEMENTS)}
    return sorted(gs, key=lambda g: (-(g["need"] - g["have"]), order[g["element"]]))


def overdue_tasks(ctx, account_id: str | None, deal_id: str | None, now: datetime | None = None) -> list[dict]:
    rows = []
    for t in ctx.store.select("tasks", "status=?", ("open",)):
        if (deal_id and t.get("deal_id") == deal_id) or (account_id and t.get("account_id") == account_id):
            d = pipeline.days_until(t.get("due_at"), _now(now))
            if d is not None and d < 0:
                rows.append({**t, "days_overdue": -d})
    return sorted(rows, key=lambda t: -t["days_overdue"])


def last_call(ctx, account_id: str | None, deal_id: str | None) -> dict | None:
    rows = [m for m in ctx.store.select("meetings", "processed_at IS NOT NULL", order="started_at IS NULL, started_at DESC")
            if (deal_id and m.get("deal_id") == deal_id) or (account_id and m.get("account_id") == account_id)]
    return rows[0] if rows else None


def history(ctx, account_id: str | None, now: datetime | None = None) -> dict:
    if not account_id:
        return {"competitors": {}, "objections": {}}
    days = int(ctx.manifest.config.get("insight_days", 180))
    since = (_now(now) - timedelta(days=days)).isoformat()
    out = {"competitors": {}, "objections": {}}
    for kind, key in (("competitor_mention", "competitors"), ("objection", "objections")):
        for i in ctx.store.insights(kind, since, account_id=account_id):
            out[key][i["key"]] = out[key].get(i["key"], 0) + 1
    return out


def latest_score(ctx, account_id: str | None) -> dict | None:
    if not account_id:
        return None
    import json
    r = ctx.store.one("SELECT score, tier, reasons FROM scores WHERE account_id=? ORDER BY id DESC LIMIT 1", (account_id,))
    if not r:
        return None
    return {"score": r["score"], "tier": r["tier"], "reasons": json.loads(r["reasons"] or "[]")}


TITLE_FUNCTION_HINTS = {"financ": "finance", "operating officer": "executive", "executive officer": "executive",
                        "technology officer": "engineering", "information officer": "it", "security officer": "security",
                        "marketing officer": "marketing", "revenue officer": "sales"}


def _function(title: str | None, current: str | None) -> str:
    if current and current not in ("other", "unknown"):
        return current
    t = (title or "").lower()
    return next((f for k, f in TITLE_FUNCTION_HINTS.items() if k in t), current or "other")


def people(ctx, account_id: str | None, attendees: list[str] | None = None) -> list[dict]:
    contacts = ctx.store.select("contacts", "account_id=?", (account_id,)) if account_id else []
    names = {a.lower() for a in (attendees or [])}
    reps = {r.lower() for r in profile.rep_names(ctx)}
    out = []
    for c in contacts:
        cls = personas.classify(c.get("title"))
        out.append({"name": c.get("name"), "title": c.get("title"),
                    "function": _function(c.get("title"), c.get("function") or cls["function"]),
                    "seniority": c.get("seniority") or cls["seniority"], "rank": cls["rank"],
                    "attending": (c.get("name") or "").lower() in names})
    known = {(p["name"] or "").lower() for p in out}
    for a in attendees or []:
        if a.lower() not in known and a.lower() not in reps:
            out.append({"name": a, "title": "unknown", "function": "unknown", "seniority": "unknown", "rank": 0,
                        "attending": True})
    return sorted(out, key=lambda p: (not p["attending"], -p["rank"]))


# ---------- pre-call brief ----------
def plan_fallback(ctx, gaps: list[dict]) -> list[str]:
    bank = question_bank(ctx)
    steps = []
    for g in gaps[:2]:
        q = (bank.get(g["element"]) or [""])[0]
        steps.append(f"{GOAL_TEXT[g['element']]}: \"{q}\"" if q else GOAL_TEXT[g["element"]])
    if not gaps:
        steps.append("Confirm nothing changed since the last call: timeline, people, budget.")
    steps.append("Leave with a dated next step and an owner.")
    return steps


def build_brief(ctx, meeting: dict | None = None, account_id: str | None = None, now: datetime | None = None) -> dict:
    account_id = account_id or (meeting or {}).get("account_id")
    acct = ctx.store.account(account_id) if account_id else None
    deal = open_deal_for(ctx, account_id, (meeting or {}).get("deal_id"))
    gaps = ordered_gaps(deal)
    lc = last_call(ctx, account_id, (deal or {}).get("id"))
    lc_summary = (lc or {}).get("summary") or {}
    hist = history(ctx, account_id, now)
    od = overdue_tasks(ctx, account_id, (deal or {}).get("id"), now)
    score = latest_score(ctx, account_id)
    ppl = people(ctx, account_id, (meeting or {}).get("attendees"))
    plan = plan_fallback(ctx, gaps)
    missing = [k for k, v in {"account": acct, "deal": deal, "contacts": [p for p in ppl if p["title"] != "unknown"]}.items()
               if not v]
    brief = {
        "meeting_id": (meeting or {}).get("id"), "meeting_title": (meeting or {}).get("title"),
        "started_at": (meeting or {}).get("started_at"), "owner": (meeting or {}).get("owner") or (deal or {}).get("owner"),
        "account": {k: (acct or {}).get(k) for k in ("id", "name", "industry", "employees", "country")} if acct else None,
        "signal_score": score, "people": ppl[:6],
        "deal": {"id": deal["id"], "name": deal.get("name"), "stage": deal.get("stage"), "amount": deal.get("amount"),
                 "close_date": deal.get("close_date"), "days_in_stage": pipeline.days_since(deal.get("stage_entered_at"), _now(now)),
                 "next_step": deal.get("next_step")} if deal else None,
        "meddpicc_gaps": gaps, "last_call": {"id": lc["id"], "date": (lc.get("started_at") or "")[:10],
                                             "summary": lc_summary.get("headline"), "next_steps": lc_summary.get("next_steps", [])}
        if lc else None,
        "history": hist, "overdue_tasks": [{"title": t["title"], "due_at": t["due_at"], "days_overdue": t["days_overdue"]}
                                           for t in od],
        "plan": plan, "unknown": missing,
    }
    brief["text"] = brief_text(brief)
    return brief


def _money(v) -> str:
    return f"${float(v):,.0f}" if v not in (None, "") else "amount unknown"


def brief_text(b: dict) -> str:
    when = ""
    if b.get("started_at"):
        d = pipeline.parse_dt(b["started_at"])
        when = f" ({d.strftime('%a %b %d, %H:%M')} UTC)" if d else ""
    lines = [f"*Pre-call: {b.get('meeting_title') or (b.get('account') or {}).get('name') or 'account'}*{when}"
             + (f" | {b['owner']}" if b.get("owner") else "")]
    a = b.get("account")
    if a:
        firmo = ", ".join(x for x in [a.get("industry"), f"{a['employees']} people" if a.get("employees") else None,
                                      a.get("country")] if x)
        sc = b.get("signal_score")
        lines.append(f"Account: {a['name']}" + (f" | {firmo}" if firmo else "")
                     + (f" | Signal Scout {sc['tier']} {sc['score']:.0f}" if sc else ""))
    else:
        lines.append("Account: unknown (not in the CRM sync)")
    if b.get("people"):
        lines.append("People: " + ", ".join(f"{p['name']} ({p['title']}, {p['function']})" for p in b["people"][:4]))
    d = b.get("deal")
    if d:
        age = f" {d['days_in_stage']} days" if d.get("days_in_stage") is not None else ""
        lines.append(f"Deal: {d['name']} | {d['stage']}{age} | {_money(d.get('amount'))} | close {d.get('close_date') or 'unknown'}")
        gaps = b.get("meddpicc_gaps") or []
        lines.append("MEDDPICC gaps: " + (", ".join(f"{g['label']} ({g['kind']})" for g in gaps) or "none for this stage"))
    else:
        lines.append("Deal: no open deal")
    lc = b.get("last_call")
    if lc:
        nxt = "; ".join(lc.get("next_steps") or []) or "none recorded"
        lines.append(f"Last call ({lc['date']}): {lc.get('summary') or 'no summary'} Next steps: {nxt}")
    h = b.get("history") or {}
    comp = ", ".join(f"{k} ({v})" for k, v in h.get("competitors", {}).items()) or "none"
    obj = ", ".join(f"{k} ({v})" for k, v in h.get("objections", {}).items()) or "none"
    lines.append(f"History: competitors {comp}; objections {obj}")
    if b.get("overdue_tasks"):
        lines.append("Overdue: " + "; ".join(f"{t['title']} ({t['days_overdue']}d late)" for t in b["overdue_tasks"][:3]))
    lines.append("Plan for the call:")
    lines += [f"{i}. {p}" for i, p in enumerate(b.get("plan") or [], 1)]
    return "\n".join(lines)


def brief_with_plan(ctx, meeting: dict | None = None, account_id: str | None = None, now: datetime | None = None) -> dict:
    b = build_brief(ctx, meeting, account_id, now)
    facts = {k: b[k] for k in ("meeting_title", "account", "people", "deal", "meddpicc_gaps", "last_call", "history",
                               "overdue_tasks", "signal_score")}
    plan_text = "\n".join(f"{i}. {p}" for i, p in enumerate(b["plan"], 1))
    text, source = writer.narrate(ctx, "Write a numbered plan for this sales call: at most 3 goals, each with one "
                                       "question to ask. Base it on the MEDDPICC gaps and the last call.", facts, plan_text, 120)
    b["plan_text"], b["plan_source"] = text, source
    if source == "model":
        b["text"] = b["text"].split("Plan for the call:")[0] + "Plan for the call:\n" + text
    return b


def upcoming(ctx, now: datetime | None = None) -> list[dict]:
    now = _now(now)
    end = now + timedelta(hours=int(ctx.manifest.config.get("lookahead_hours", 48)))
    return [m for m in ctx.store.select("meetings", order="started_at")
            if not (m.get("transcript") or "").strip() and pipeline.in_period(m.get("started_at"), now, end)]


# ---------- on-demand helpers ----------
def questions_for(ctx, deal: dict) -> dict:
    bank = question_bank(ctx)
    gaps = ordered_gaps(deal)
    return {"deal": deal.get("name"), "stage": deal.get("stage"),
            "gaps": [{"element": g["element"], "label": g["label"], "kind": g["kind"],
                      "questions": (bank.get(g["element"]) or [])[:3]} for g in gaps]}


def classify_objection(text: str) -> str | None:
    t = (text or "").strip().lower()
    if t in transcripts.OBJECTIONS:
        return t
    for cat, pats in transcripts.OBJECTIONS.items():
        if any(re.search(p, t) for p in pats):
            return cat
    simple = {"price": ["price", "expensive", "cost", "budget"], "timing": ["timing", "later", "quarter", "busy"],
              "authority": ["boss", "approval", "decision maker"], "competition": ["competitor", "already have"],
              "security": ["security", "compliance"], "integration": ["integration", "api", "connect"]}
    for cat, words in simple.items():
        if any(w in t for w in words):
            return cat
    return None


def objection(ctx, text: str) -> dict:
    cat = classify_objection(text)
    pb = playbook(ctx)
    comps = [c for c in profile.company(ctx).get("competitors", []) if isinstance(c, dict)
             and c.get("name", "").lower() in (text or "").lower()]
    if comps and not cat:
        cat = "competition"
    out = {"objection": text, "category": cat, "playbook": pb.get(cat) if cat else None,
           "competitor_positioning": [{"name": c["name"], "positioning": c.get("positioning")} for c in comps]}
    if not cat:
        out["note"] = "No matching category. Ask one clarifying question before answering."
    return out


def _ev(m: dict, e: str) -> str | None:
    v = m[e]
    return v["evidence"] if v["score"] > 0 and v["evidence"] else None


def proposal(ctx, deal: dict) -> dict:
    m = meddpicc.normalize(deal.get("meddpicc"))
    bank = question_bank(ctx)
    comp = profile.company(ctx)
    pain = _ev(m, "identify_pain")
    pain_l = (pain or "").lower()
    vps = comp.get("value_props", [])
    matched = [v for v in vps if any(w in pain_l for w in re.findall(r"[a-z]{5,}", (v.get("pain") or "").lower()))] or vps[:1]

    def sec(title, val, element=None):
        if val:
            return {"section": title, "content": val, "missing": False}
        ask = (bank.get(element) or [""])[0] if element else ""
        return {"section": title, "content": f"MISSING: ask \"{ask}\"" if ask else "MISSING", "missing": True}

    dp = _ev(m, "decision_process")
    timeline = "; ".join(x for x in [dp, f"target close {deal['close_date']}" if deal.get("close_date") else None] if x)
    sections = [
        sec("Situation", pain, "identify_pain"),
        sec("Goals and how we will measure them", _ev(m, "metrics"), "metrics"),
        sec("Proposed approach", "; ".join(f"{v.get('outcome')}" for v in matched if v.get("outcome"))),
        sec("Decision criteria we meet", _ev(m, "decision_criteria"), "decision_criteria"),
        sec("Timeline", timeline if dp else None, "decision_process"),
        sec("Investment", _money(deal["amount"]) if deal.get("amount") else None),
        sec("Paper process", _ev(m, "paper_process"), "paper_process"),
        sec("Next steps", "; ".join(x for x in [deal.get("next_step"), deal.get("next_step_date")] if x) or None),
    ]
    return {"deal": deal.get("name"), "stage": deal.get("stage"), "sections": sections,
            "missing": [s["section"] for s in sections if s["missing"]],
            "ready_to_send": not any(s["missing"] for s in sections)}


def next_steps(ctx, deal: dict, now: datetime | None = None) -> dict:
    now = _now(now)
    items = []
    if deal.get("next_step"):
        d = pipeline.days_until(deal.get("next_step_date"), now)
        items.append({"source": "deal", "step": deal["next_step"], "due": deal.get("next_step_date"),
                      "overdue": d is not None and d < 0})
    for t in ctx.store.select("tasks", "deal_id=? AND status=?", (deal["id"], "open"), order="due_at"):
        d = pipeline.days_until(t.get("due_at"), now)
        items.append({"source": "task", "step": t["title"], "owner": t.get("owner"), "due": t.get("due_at"),
                      "overdue": d is not None and d < 0})
    lc = last_call(ctx, deal.get("account_id"), deal["id"])
    if lc:
        for s in ((lc.get("summary") or {}).get("next_steps") or []):
            items.append({"source": f"call {lc['id']}", "step": s, "due": None, "overdue": False})
    flags = []
    if not items:
        flags.append("No next step anywhere: deal has no dated plan")
    if any(i["overdue"] for i in items):
        flags.append(f"{sum(i['overdue'] for i in items)} overdue")
    return {"deal": deal.get("name"), "owner": deal.get("owner"), "stage": deal.get("stage"), "items": items, "flags": flags}
