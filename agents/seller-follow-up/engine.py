"""Seller Follow-Up engine: deterministic overdue detection, prioritization, cooldowns, recap building.

The model only writes the recap and follow-up emails (gtm_core.writer, with template fallbacks).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from gtm_core import meddpicc, pipeline, profile, writer

STAGE_WEIGHT = {"discovery": 1, "qualification": 2, "evaluation": 3, "proposal": 4, "negotiation": 5, "commit": 5}
KIND_WEIGHT = {"lead_sla": 30, "no_recap": 25, "next_step_late": 12, "task_overdue": 10, "no_next_step": 8, "quiet": 6}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _now(now):
    return now or datetime.now(timezone.utc)


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def _deal_label(d: dict | None) -> str:
    return (d or {}).get("name") or (d or {}).get("id") or "deal"


# ---------- overdue detection ----------
def collect(ctx, now: datetime | None = None, owner: str | None = None) -> list[dict]:
    """Every follow-up item, unfiltered by cooldown. Each has a stable item_id."""
    now = _now(now)
    items: list[dict] = []
    deals = {d["id"]: d for d in ctx.store.select("deals")}

    def add(item_id, kind, own, title, days, action, deal=None, **kw):
        sk = meddpicc.stage_key((deal or {}).get("stage"))
        amt = float((deal or {}).get("amount") or 0)
        prio = KIND_WEIGHT[kind] + STAGE_WEIGHT.get(sk, 1) * 3 + min(amt / 20000, 10) + min(max(days, 0), 30) * 0.5
        items.append({"item_id": item_id, "kind": kind, "owner": own, "title": title, "days": days, "action": action,
                      "deal_id": (deal or {}).get("id"), "deal": _deal_label(deal) if deal else None,
                      "account_id": (deal or {}).get("account_id") or kw.pop("account_id", None),
                      "amount": amt, "stage": (deal or {}).get("stage"), "priority": round(prio, 1), **kw})

    for t in ctx.store.select("tasks", "status=?", ("open",)):
        d = pipeline.days_since(t.get("due_at"), now)
        if d is not None and d > 0:
            deal = deals.get(t.get("deal_id"))
            add(f"task:{t['id']}", "task_overdue", t.get("owner") or (deal or {}).get("owner"),
                f"task {d} days late: {t.get('title')}", d, "do it today or move the date", deal,
                account_id=t.get("account_id"))

    stale = cfg(ctx, "stale_days", {}) or {}
    for d in deals.values():
        if not pipeline.is_open(d):
            continue
        own = d.get("owner")
        late = pipeline.days_since(d.get("next_step_date"), now)
        if d.get("next_step") and late is not None and late > 0:
            add(f"next_step:{d['id']}", "next_step_late", own, f"next step {late} days late: {d['next_step']}", late,
                "do it today or reset the date", d)
        elif not (d.get("next_step") or "").strip():
            add(f"no_next_step:{d['id']}", "no_next_step", own, "no next step on the deal", 0,
                "agree a dated next step with the buyer", d)
        quiet = pipeline.days_since(d.get("last_activity_at"), now)
        limit = int(stale.get(meddpicc.stage_key(d.get("stage")), stale.get("default", 14)))
        if quiet is not None and quiet > limit:
            add(f"quiet:{d['id']}", "quiet", own, f"quiet {quiet} days in {d.get('stage')} (limit {limit})", quiet - limit,
                "re-engage with a new reason, or close it out", d)

    for lead in ctx.store.select("leads", "status=?", ("routed",)):
        late = pipeline.days_since(lead.get("sla_due"), now)
        due = pipeline.parse_dt(lead.get("sla_due"))
        if not due or due > now:
            continue
        if ctx.store.one("SELECT id FROM drafts WHERE lead_id=? AND status='sent'", (lead["id"],)):
            continue
        hours = int((now - due).total_seconds() // 3600)
        active = any("ACTIVE PIPELINE" in str(f) for f in (lead.get("flags") or []))
        add(f"lead:{lead['id']}", "lead_sla", lead.get("owner"), f"{lead.get('tier', '')} lead, {hours}h past SLA",
            late or 0, "reply on the open deal thread" if active else "approve the queued reply, or call",
            None, account_id=lead.get("account_id"), label=f"{lead.get('name')} ({lead.get('company')})")

    window = (now - timedelta(days=int(cfg(ctx, "recap_window_days", 3)))).isoformat()
    for m in ctx.store.select("meetings", "started_at>=? AND started_at<=?", (window, now.isoformat())):
        if not (m.get("transcript") or m.get("summary") or m.get("processed_at")):
            continue
        if has_recap(ctx, m["id"]):
            continue
        deal = deals.get(m.get("deal_id"))
        add(f"recap:{m['id']}", "no_recap", m.get("owner") or (deal or {}).get("owner"),
            f"call {str(m.get('started_at'))[:10]} has no recap: {m.get('title')}", pipeline.days_since(m["started_at"], now) or 0,
            "review and send the recap", deal, account_id=m.get("account_id"), meeting_id=m["id"])

    if owner:
        items = [i for i in items if (i.get("owner") or "").lower() == owner.lower()]
    items.sort(key=lambda i: -i["priority"])
    return collapse(items)


def collapse(items: list[dict]) -> list[dict]:
    """One line per deal: keep the top item, fold the rest in as 'also'. Recaps stay separate (they carry a draft)."""
    out, by_deal = [], {}
    for i in items:
        key = i.get("deal_id")
        if not key or i["kind"] == "no_recap":
            out.append(i)
            continue
        if key in by_deal:
            top = by_deal[key]
            top.setdefault("also", []).append(i["title"].split(":")[0])
            top.setdefault("merged", []).append(i["item_id"])
            continue
        by_deal[key] = i
        out.append(i)
    return out


def has_recap(ctx, meeting_id: str) -> bool:
    import json
    for r in ctx.store.query("SELECT meta FROM drafts WHERE kind='meeting_recap' AND status<>'rejected'"):
        if json.loads(r["meta"] or "{}").get("meeting_id") == meeting_id:
            return True
    return False


def _state(ctx, key):
    return ctx.store.get_state(key, {}) or {}


def suppressed(ctx, item_id: str, now: datetime) -> str | None:
    snooze = _state(ctx, "sfu_snooze").get(item_id)
    if snooze and pipeline.parse_dt(snooze) > now:
        return f"snoozed until {snooze[:10]}"
    last = _state(ctx, "sfu_nudged").get(item_id)
    if last and (now - pipeline.parse_dt(last)).days < int(cfg(ctx, "cooldown_days", 3)):
        return f"nudged {last[:10]}"
    return None


def due_now(ctx, now: datetime | None = None, owner: str | None = None, mark: bool = False) -> dict[str, list[dict]]:
    """Items per owner after cooldown and snooze, capped per owner. mark=True records the nudge."""
    now = _now(now)
    cap = int(cfg(ctx, "max_items_per_owner", 5))
    out: dict[str, list[dict]] = {}
    for i in collect(ctx, now, owner):
        if suppressed(ctx, i["item_id"], now):
            continue
        own = i.get("owner") or "unassigned"
        if len(out.setdefault(own, [])) < cap:
            out[own].append(i)
    if mark:
        nudged = _state(ctx, "sfu_nudged")
        for items in out.values():
            for i in items:
                for iid in [i["item_id"], *i.get("merged", [])]:
                    nudged[iid] = now.replace(microsecond=0).isoformat()
        ctx.store.set_state("sfu_nudged", nudged)
    return out


def snooze(ctx, item_id: str, days: int, now: datetime | None = None) -> str:
    until = (_now(now) + timedelta(days=days)).replace(microsecond=0).isoformat()
    s = _state(ctx, "sfu_snooze")
    s[item_id] = until
    ctx.store.set_state("sfu_snooze", s)
    return until


def format_digest(owner: str, items: list[dict]) -> str:
    lines = [f"*Follow-ups for {owner} ({len(items)})*"]
    for n, i in enumerate(items, 1):
        label = i.get("deal") or i.get("label") or i["title"]
        draft = f" (draft #{i['draft_id']})" if i.get("draft_id") else ""
        also = f" (also: {', '.join(i['also'])})" if i.get("also") else ""
        lines.append(f"{n}. {label} | {i['title']}{also} | Do: {i['action']}{draft}")
    return "\n".join(lines)


# ---------- dates ----------
def add_business_days(d: datetime, n: int) -> datetime:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def parse_due(text: str, base: datetime, default_days: int = 2) -> str:
    """Due date said in a next step ("by Friday", "next week", "tomorrow", an ISO date), else +N business days."""
    t = (text or "").lower()
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    if m:
        return m.group(1)
    for i, wd in enumerate(WEEKDAYS):
        if re.search(rf"\b{wd}\b", t):
            ahead = (i - base.weekday()) % 7 or 7
            if "next " + wd in t and ahead < 7:
                ahead += 7
            return (base + timedelta(days=ahead)).date().isoformat()
    if "tomorrow" in t:
        return add_business_days(base, 1).date().isoformat()
    if "end of week" in t or "eow" in t:
        return (base + timedelta(days=(4 - base.weekday()) % 7 or 7)).date().isoformat()
    if "next week" in t:
        return (base + timedelta(days=7)).date().isoformat()
    if "end of month" in t:
        nxt = (base.replace(day=28) + timedelta(days=4))
        return (nxt - timedelta(days=nxt.day)).date().isoformat()
    return add_business_days(base, default_days).date().isoformat()


# ---------- recap ----------
def clean_step(s: str) -> str:
    s = re.sub(r"^[^:]{1,40}:\s*", "", s.strip())         # speaker prefix
    s = re.sub(r"(?i)^next steps?\s*[:\-]\s*", "", s)
    return s.strip().rstrip(".")


def summary_points(summary) -> list[str]:
    if not summary:
        return []
    if isinstance(summary, str):
        parts = [p.strip(" -*") for p in re.split(r"\n|(?<=[.!?])\s+", summary) if p.strip(" -*")]
        return parts[:3]
    if isinstance(summary, dict):
        pts = []
        for k in ("pain", "goals", "key_points", "points", "summary", "decision", "decision_criteria"):
            v = summary.get(k)
            if isinstance(v, list):
                pts += [str(x) for x in v]
            elif v:
                pts.append(str(v))
        return [p.strip() for p in pts if p.strip()][:3]
    if isinstance(summary, list):
        return [str(x) for x in summary][:3]
    return []


def buyer_attendees(ctx, attendees, account_id: str | None) -> list[dict]:
    if isinstance(attendees, str):  # "A; B" or "A, B" from a form or API
        attendees = [a.strip() for a in attendees.replace(";", ",").split(",") if a.strip()]
    reps = {r.lower() for r in profile.rep_names(ctx)}
    out = []
    for a in attendees or []:
        name = a.get("name") if isinstance(a, dict) else str(a)
        if not name or name.lower() in reps:
            continue
        c = None
        if "@" in name:
            c = ctx.store.contact_by_email(name)
        else:
            rows = ctx.store.select("contacts", "LOWER(name)=?", (name.lower(),))
            c = next((r for r in rows if not account_id or r.get("account_id") == account_id), rows[0] if rows else None)
        out.append({"name": (c or {}).get("name") or name, "email": (c or {}).get("email"), "contact_id": (c or {}).get("id")})
    return out


def recap_template(ctx, meeting: dict, points: list[str], steps: list[dict], buyers: list[dict],
                   now: datetime | None = None) -> str:
    """Only facts from the call. Sections with nothing to say are left out, never padded."""
    snd = profile.sender(ctx)
    first = buyers[0]["name"].split(" ")[0] if buyers else "all"
    started = pipeline.parse_dt(meeting.get("started_at"))
    when = "today" if not started or started.date() == _now(now).date() else f"on {started.strftime('%A')}"
    parts = [f"Thanks for the time {when}."]
    if points:
        parts.append("What I heard:\n" + "\n".join(f"- {p.rstrip('.')}" for p in points))
    if steps:
        parts.append("Next steps:\n" + "\n".join(
            f"- {s['text']}" + (f" (by {s['due_at']})" if s.get("said_date") else "") for s in steps))
        parts.append("Did I miss anything?")
    else:
        parts.append("What is the best next step on your side?")
    sender = meeting.get("owner") or snd.get("name", "")
    return f"Subject: Recap: {meeting.get('title') or 'our call'}\nHi {first},\n\n" + "\n\n".join(parts) + f"\n\n{sender}"


def from_transcript(ctx, transcript: str) -> tuple[list[str], list[str]]:
    """Fallback when no summary exists: buyer pain and criteria quotes, rep-side next steps, rule-based."""
    from gtm_core import transcripts
    turns = transcripts.parse(transcript or "")
    if not turns:
        return [], []
    reps = profile.rep_names(ctx)
    a = transcripts.analyze(turns, reps, profile.competitors(ctx))
    strip = lambda q: re.sub(r"^[^:]{1,40}:\s*", "", q).strip()
    points = [strip(q) for k in ("identify_pain", "decision_criteria") for q in a.meddpicc_evidence.get(k, [])][:3]
    rep_l = [r.lower() for r in reps]
    steps = [q for q in a.next_steps if q.split(":", 1)[0].strip().lower() in rep_l][:4]
    return points, steps


def build_recap(ctx, meeting_id: str, payload: dict | None = None, now: datetime | None = None, queue: bool = True) -> dict:
    """Recap email + CRM note + next-step tasks for one meeting. Queues approvals; sends nothing."""
    payload = payload or {}
    m = ctx.store.get("meetings", meeting_id) or {}
    if not m and not payload:
        return {"error": f"meeting '{meeting_id}' not found"}
    deal_id = payload.get("deal_id") or m.get("deal_id")
    account_id = payload.get("account_id") or m.get("account_id")
    deal = ctx.store.get("deals", deal_id) if deal_id else None
    acct = ctx.store.account(account_id) if account_id else None
    owner = payload.get("owner") or m.get("owner") or (deal or {}).get("owner")
    base = pipeline.parse_dt(m.get("started_at")) or _now(now)
    summary = payload.get("summary") or m.get("summary")
    if isinstance(summary, dict) and not payload.get("next_steps"):
        payload.setdefault("next_steps", summary.get("next_steps"))
    points = summary_points(summary)
    raw_steps = payload.get("next_steps") or []
    if not points and not raw_steps and m.get("transcript"):
        points, raw_steps = from_transcript(ctx, m["transcript"])
    steps = []
    for s in raw_steps:
        text = clean_step(s if isinstance(s, str) else s.get("text", ""))
        if not text:
            continue
        due = parse_due(text, base, int(cfg(ctx, "default_task_business_days", 2)))
        said = due != add_business_days(base, int(cfg(ctx, "default_task_business_days", 2))).date().isoformat()
        steps.append({"text": text, "due_at": due, "said_date": said})
    buyers = buyer_attendees(ctx, payload.get("attendees") or m.get("attendees") or [], account_id)
    facts = {"meeting": {"title": m.get("title"), "date": str(m.get("started_at") or "")[:10]},
             "what_we_heard": points, "next_steps": steps, "buyer_attendees": [b["name"] for b in buyers],
             "sender": owner or profile.sender(ctx).get("name")}
    tpl = recap_template(ctx, m or {"title": payload.get("title"), "owner": owner}, points, steps, buyers, now)
    d = writer.write(ctx, "meeting recap email to the buyer", facts,
                     "Follow references/recap-format.md. Only what was said. One question at the end.", tpl,
                     max_words=int(cfg(ctx, "recap_max_words", 170)))
    note = "\n".join([f"Call: {m.get('title') or meeting_id} ({str(m.get('started_at') or '')[:10]})",
                      "Attendees: " + ", ".join(str(a.get('name') if isinstance(a, dict) else a)
                                                 for a in (payload.get("attendees") or m.get("attendees") or [])),
                      "Heard: " + ("; ".join(points) or "see transcript"),
                      "Next steps: " + ("; ".join(f"{s['text']} ({s['due_at']})" for s in steps) or "none agreed")])
    did = ctx.store.add_draft(ctx.manifest.id, "meeting_recap", d.body, subject=d.subject, gate_score=d.score,
                              gate_passed=d.passed, source=d.source, account_id=account_id, deal_id=deal_id,
                              contact_id=buyers[0]["contact_id"] if buyers else None,
                              meta={"meeting_id": meeting_id, "to": [b["email"] for b in buyers if b.get("email")],
                                    "note": note})
    out = {"meeting_id": meeting_id, "draft_id": did, "draft": d.as_dict(), "note": note, "tasks": steps,
           "to": [b for b in buyers], "approvals": []}
    if not queue:
        return out
    crm = {"deal_crm_id": (deal or {}).get("crm_id"), "account_crm_id": (acct or {}).get("crm_id"), "owner": owner}
    to = ", ".join(b.get("email") or b["name"] for b in buyers) or "buyer attendees"
    send_id = None
    if d.passed:  # only gate-passing copy is ever queued to go to a buyer
        send_id = ctx.request_approval("crm_task", {
            "subject": f"Send recap to {to}: {m.get('title') or meeting_id}",
            "body": f"Draft #{did} (gate {d.score}/40)\n\nSubject: {d.subject}\n\n{d.body}",
            "due_at": _now(now).date().isoformat(), **crm},
            summary=f"{owner}: recap ready for {m.get('title') or meeting_id} (draft #{did}, gate {d.score}/40)")
        out["approvals"].append(send_id)
    else:
        out["needs_rewrite"] = d.fix
    if (deal or {}).get("crm_id"):
        out["approvals"].append(ctx.request_approval("deal_note", {"crm_id": deal["crm_id"], "body": note}))
    elif (acct or {}).get("crm_id"):
        out["approvals"].append(ctx.request_approval("crm_note", {"crm_id": acct["crm_id"], "body": note}))
    for s in steps:
        out["approvals"].append(ctx.request_approval("crm_task", {
            "subject": s["text"][:200], "body": f"From call {m.get('title') or meeting_id}", "due_at": s["due_at"], **crm}))
    if send_id:
        ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", send_id, did))
    else:
        ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("needs_rewrite", did))
    return out


# ---------- follow-up email for a deal ----------
def last_meeting(ctx, deal_id: str) -> dict | None:
    rows = [m for m in ctx.store.select("meetings", "deal_id=?", (deal_id,), order="started_at IS NULL, started_at DESC")
            if m.get("transcript") or m.get("summary")]
    return rows[0] if rows else None


def primary_contact(ctx, deal: dict) -> dict | None:
    if deal.get("contact_id"):
        c = ctx.store.get("contacts", deal["contact_id"])
        if c:
            return c
    from gtm_core import personas
    cs = ctx.store.select("contacts", "account_id=?", (deal.get("account_id"),))
    cs.sort(key=lambda c: -personas.classify(c.get("title"))["rank"])
    return cs[0] if cs else None


def draft_deal_follow_up(ctx, deal: dict, now: datetime | None = None) -> dict:
    m = last_meeting(ctx, deal["id"])
    c = primary_contact(ctx, deal)
    first = ((c or {}).get("name") or "there").split(" ")[0]
    snd = deal.get("owner") or profile.sender(ctx).get("name", "")
    points = summary_points((m or {}).get("summary"))
    step = (deal.get("next_step") or "").strip()
    ref = f"our call on {str(m['started_at'])[:10]}" if m else "our last conversation"
    line = f"Following {ref}, the open item on my side is: {step[0].lower() + step[1:]}." if step \
        else f"I wanted to pick up where we left off after {ref}."
    heard = f" You mentioned {points[0][0].lower() + points[0][1:].rstrip('.')}." if points else ""
    tpl = (f"Subject: {deal.get('name') or 'Next step'}\nHi {first},\n\n{line}{heard}\n\n"
           f"Does a 20 minute check-in on {(add_business_days(_now(now), 2)).strftime('%A')} work to agree the next step?\n\n{snd}")
    tpl = tpl.replace("I wanted to pick up", "Picking up")
    facts = {"deal": {k: deal.get(k) for k in ("name", "stage", "next_step", "next_step_date")},
             "last_meeting": {"date": str((m or {}).get("started_at") or "")[:10], "heard": points},
             "contact": {k: (c or {}).get(k) for k in ("name", "title")}, "sender": snd}
    d = writer.write(ctx, "follow-up email to move a deal to its next step", facts,
                     "One reason to reply, tied to the next step. One ask.", tpl,
                     max_words=int(cfg(ctx, "max_words", 120)))
    did = ctx.store.add_draft(ctx.manifest.id, "deal_follow_up", d.body, subject=d.subject, gate_score=d.score,
                              gate_passed=d.passed, source=d.source, deal_id=deal["id"], account_id=deal.get("account_id"),
                              contact_id=(c or {}).get("id"), meta={"to": (c or {}).get("email")})
    return {"deal": deal.get("name"), "to": (c or {}).get("email"), "draft_id": did, **d.as_dict()}
