"""Event Campaigns engine: deterministic invite lists, attendee import and event reporting.

The model only writes copy (through gtm_core.writer, with template fallbacks). Every send is a
sequence_enroll approval with the event id as the campaign.
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import yaml

from gtm_core import personas, pipeline, profile, suppression, writer
from gtm_core.scoring import IcpProfile, icp_fit, signal_id

TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 9, None: 5}
FUNCTION_VP = {"revops": "deal_hygiene", "sales": "prioritization", "executive": "deal_hygiene"}
TYPE_LABEL = {"hosted": "a small dinner", "booth": "our booth", "webinar": "a live webinar"}


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


@lru_cache(maxsize=8)
def _yaml(path: str, mtime: float) -> dict:
    return yaml.safe_load(open(path).read()) or {}


def events(ctx) -> list[dict]:
    p = ctx.manifest.path(cfg(ctx, "events", "../../config/events.yaml"))
    if not p.exists():
        return []
    return list(_yaml(str(p), p.stat().st_mtime).get("events") or [])


def event(ctx, event_id: str) -> dict | None:
    return next((e for e in events(ctx) if e.get("id") == event_id), None)


@lru_cache(maxsize=8)
def _icp(path: str) -> IcpProfile:
    return IcpProfile.from_yaml(path)


def icp(ctx) -> IcpProfile:
    return _icp(str(profile.icp_path(ctx)))


def _now(now):
    return now or datetime.now(timezone.utc)


def event_date(ev: dict) -> date:
    d = ev.get("date")
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def latest_scores(ctx) -> dict[str, dict]:
    out = {}
    for r in ctx.store.query("SELECT * FROM scores ORDER BY id"):
        out[r["account_id"]] = r
    return out


def dnc(ctx) -> dict:
    p = ctx.manifest.path(cfg(ctx, "do_not_contact", "../icp-outbound/skill/references/do-not-contact.yaml"))
    d = (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}
    return {"domains": {x.lower() for x in d.get("domains") or []}, "emails": {x.lower() for x in d.get("emails") or []}}


# ---------- invite list ----------
def account_block(ctx, acct: dict, ev: dict) -> list[str]:
    """Reasons this account gets no invite from the agent. Empty = clear."""
    out = []
    countries = [c.upper() for c in ev.get("countries") or []]
    if countries and (acct.get("country") or "").upper() not in countries:
        out.append(f"outside the event region ({acct.get('country') or 'unknown country'})")
    fit, reasons = icp_fit(acct, icp(ctx))
    if reasons and reasons[0].startswith("excluded industry"):
        out.append(reasons[0])
    deals = [d for d in ctx.store.select("deals", "account_id=?", (acct["id"],)) if pipeline.is_open(d)]
    if deals:
        d = deals[0]
        out.append(f"active pipeline: {d.get('name')} (owner {d.get('owner')} invites)")
    if (acct.get("domain") or acct["id"]).lower() in dnc(ctx)["domains"]:
        out.append("on the do-not-contact list")
    return out


def invite_contacts(ctx, acct: dict, ev: dict) -> list[dict]:
    p = ev.get("personas") or {}
    fns = p.get("functions") or profile.company(ctx).get("personas", {}).get("buyer_functions", ["sales"])
    min_sen = p.get("min_seniority", "manager")
    d = dnc(ctx)
    picks = []
    for c in ctx.store.select("contacts", "account_id=?", (acct["id"],)):
        email = (c.get("email") or "").lower()
        if not email or suppression.is_suppressed(ctx.store, email, c, extra_emails=d["emails"], extra_domains=d["domains"]):
            continue
        m = personas.persona_match(c.get("title"), fns, min_sen)
        if not m["match"]:
            continue
        picks.append({"contact_id": c["id"], "name": c.get("name"), "email": email, "title": c.get("title"),
                      "function": m["function"], "seniority": m["seniority"], "_rank": m["rank"]})
    picks.sort(key=lambda x: -x.pop("_rank"))
    return picks[: int(cfg(ctx, "max_contacts_per_account", 2))]


def build_invite_list(ctx, event_id: str, now: datetime | None = None) -> dict:
    ev = event(ctx, event_id)
    if not ev:
        return {"error": f"event '{event_id}' not found; check config/events.yaml"}
    if event_date(ev) < _now(now).date():
        return {"error": f"{ev['name']} already happened ({ev['date']})"}
    tiers = ev.get("target_tiers") or ["A", "B"]
    scores = latest_scores(ctx)
    cap = int(int(ev.get("capacity", 20)) * float(cfg(ctx, "invite_multiplier", 3)))
    ranked, excluded = [], []
    for acct in ctx.store.accounts():
        s = scores.get(acct["id"])
        fit, _ = icp_fit(acct, icp(ctx))
        row = {"account_id": acct["id"], "name": acct["name"], "tier": s["tier"] if s else None,
               "score": float(s["score"]) if s else round(fit, 1), "basis": "signal scout" if s else "icp only"}
        why = account_block(ctx, acct, ev)
        if not why:
            if s and s["tier"] not in tiers:
                why = [f"tier {s['tier']} not in {tiers}"]
            elif not s and fit < float(cfg(ctx, "icp_only_min", 60)):
                why = [f"ICP {fit:.0f} below the ICP-only bar with no Signal Scout score"]
        if why:
            excluded.append({**row, "reasons": why})
            continue
        row["contacts"] = invite_contacts(ctx, acct, ev)
        if not row["contacts"]:
            excluded.append({**row, "reasons": ["no contact matching the event personas"]})
            continue
        ranked.append(row)
    ranked.sort(key=lambda r: (TIER_ORDER.get(r["tier"], 5), -r["score"]))
    out, n = [], 0
    for r in ranked:
        if n >= cap:
            excluded.append({**{k: v for k, v in r.items() if k != "contacts"}, "reasons": [f"over the invite cap ({cap})"]})
            continue
        r["contacts"] = r["contacts"][: cap - n]
        n += len(r["contacts"])
        out.append(r)
    return {"event": ev["id"], "name": ev["name"], "cap": cap, "invites": n, "accounts": out, "excluded": excluded}


# ---------- drafting ----------
def value_prop(ctx, function: str) -> dict:
    vps = profile.company(ctx).get("value_props", [])
    pref = FUNCTION_VP.get(function)
    return next((v for v in vps if v.get("id") == pref), vps[0] if vps else {})


def _lc(s: str) -> str:
    s = (s or "").rstrip(".")
    return s[:1].lower() + s[1:]


def _when(ev: dict) -> str:
    d = event_date(ev)
    return f"{d.strftime('%B')} {d.day}"


def templates(ctx, ev: dict, contact: dict, company: str) -> dict[str, str]:
    snd = profile.sender(ctx).get("name", "")
    first = (contact.get("name") or "there").split(" ")[0]
    vp = value_prop(ctx, contact.get("function", "sales"))
    topic = _lc(vp.get("outcome", "how teams pick the right accounts each week"))
    where = "online" if ev.get("type") == "webinar" else f"in {ev.get('city')}"
    label = TYPE_LABEL.get(ev.get("type"), "an event")
    link = ev.get("registration_link", "")
    return {
        "event_invite": f"Subject: {ev['name']}\nHi {first},\n\nWe are hosting {label} {where} on {_when(ev)} for "
                        f"leaders like you at {company}. The talk is about {topic}.\n\n"
                        f"Would you like a seat? You can save one here: {link}\n\n{snd}",
        "event_reminder": f"Subject: See you on {_when(ev)}\nHi {first},\n\nThanks for signing up for {ev['name']}. "
                          f"Here is the link again so it is easy to find: {link}\n\nAnything you want us to cover?\n\n{snd}",
        "event_followup_attended": f"Subject: Thanks for coming\nHi {first},\n\nThanks for joining {ev['name']}. "
                                   f"Teams that start with {topic} often see the first win in a few weeks.\n\n"
                                   f"Worth 20 minutes to map it to {company}?\n\n{snd}",
        "event_followup_missed": f"Subject: Sorry we missed you\nHi {first},\n\nWe missed you at {ev['name']}. "
                                 f"The short version: most teams start with {topic}.\n\n"
                                 f"Want me to send the notes?\n\n{snd}",
    }


INSTRUCTIONS = {
    "event_invite": "Event invite. Name the event, date and place, one reason it is worth their time, one ask with the link.",
    "event_reminder": "Short reminder for someone who registered. Date, link, one optional question.",
    "event_followup_attended": "Thank them for attending, tie one takeaway to their team, one ask for a meeting.",
    "event_followup_missed": "They registered or were invited but did not attend. Short, no guilt, offer the notes.",
}


def drafted(ctx, kind: str, event_id: str, email: str) -> bool:
    for r in ctx.store.query("SELECT meta FROM drafts WHERE agent=? AND kind=? AND status<>'rejected'",
                             (ctx.manifest.id, kind)):
        m = json.loads(r["meta"] or "{}")
        if m.get("event") == event_id and m.get("email") == email:
            return True
    return False


def draft_one(ctx, ev: dict, kind: str, contact: dict, company: str, account_id: str | None = None,
              lead_id: str | None = None, queue: bool = True) -> dict:
    """Draft one event email and queue it as a one-step sequence_enroll. Guards: email present, not
    suppressed, not already drafted for this event and step."""
    email = (contact.get("email") or "").lower()
    if not email:
        return {"skipped": True, "reasons": ["no email"]}
    why = suppression.reason(ctx.store, email, None, extra_emails=dnc(ctx)["emails"], extra_domains=dnc(ctx)["domains"])
    if why:
        return {"skipped": True, "reasons": [f"must not be contacted: {why}"]}
    if drafted(ctx, kind, ev["id"], email):
        return {"skipped": True, "reasons": [f"{kind} already drafted for this event"]}
    vp = value_prop(ctx, contact.get("function", "sales"))
    facts = {"event": {k: ev.get(k) for k in ("name", "type", "date", "city", "registration_link")},
             "contact": {k: contact.get(k) for k in ("name", "title")}, "company": company,
             "value_prop": vp, "sender": profile.sender(ctx)}
    d = writer.write(ctx, f"event email ({kind})", facts, INSTRUCTIONS[kind], templates(ctx, ev, contact, company)[kind],
                     max_words=int(cfg(ctx, "max_words", 90)))
    meta = {"event": ev["id"], "step": kind, "value_prop": vp.get("id"), "email": email}
    did = ctx.store.add_draft(ctx.manifest.id, kind, d.body, subject=d.subject, gate_score=d.score, gate_passed=d.passed,
                              source=d.source, account_id=account_id, contact_id=contact.get("contact_id"),
                              lead_id=lead_id, meta=meta)
    out = {"draft_id": did, "kind": kind, "email": email, **d.as_dict(), "approval": None}
    if queue and d.passed:
        rid = ctx.request_approval("sequence_enroll", {
            "contact": {"email": email, "name": contact.get("name"), "company": company},
            "steps": [{"subject": d.subject, "body": d.body}], "campaign": ev["id"], "draft_ids": [did],
            "meta": {"agent": ctx.manifest.id, **meta}},
            summary=f"{kind} for {ev['name']} to {contact.get('name')} ({company})")
        ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", rid, did))
        out["approval"] = rid
    return out


def draft_invites(ctx, event_id: str, limit: int = 20, now: datetime | None = None) -> dict:
    lst = build_invite_list(ctx, event_id, now)
    if lst.get("error"):
        return lst
    ev = event(ctx, event_id)
    done, skipped = [], []
    for a in lst["accounts"]:
        for c in a["contacts"]:
            if len(done) >= limit:
                break
            r = draft_one(ctx, ev, "event_invite", c, a["name"], account_id=a["account_id"])
            (skipped if r.get("skipped") else done).append({"contact": c["name"], "account": a["name"], **r})
    return {"event": event_id, "drafted": len(done), "queued": sum(1 for d in done if d["approval"]),
            "drafts": done, "skipped": skipped}


# ---------- attendees ----------
def _yes(v) -> bool:
    return str(v).strip().lower() in ("yes", "y", "true", "1", "attended", "x")


def lead_key(event_id: str, email: str) -> str:
    return f"event:{event_id}:{email}"


def import_attendees(ctx, event_id: str, file: str = "", rows: list[dict] | None = None,
                     now: datetime | None = None) -> dict:
    """Registrants and attendees -> leads (status new, event set) and event_attended signals."""
    ev = event(ctx, event_id)
    if not ev:
        return {"error": f"event '{event_id}' not found"}
    if file:
        try:
            with open(file, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except OSError as e:
            return {"error": str(e)}
    rows = rows or []
    added = updated = attended = signals = 0
    errors = []
    obs = event_date(ev).isoformat()
    for raw in rows:
        r = {str(k).strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items() if k}
        email = (r.get("email") or "").lower()
        if "@" not in email:
            errors.append({"row": r.get("name"), "error": "email required"})
            continue
        dom = email.split("@", 1)[1]
        acct = ctx.store.account_by_domain(dom)
        contact = ctx.store.contact_by_email(email)
        went = _yes(r.get("attended", ""))
        lid = lead_key(event_id, email)
        old = ctx.store.get("leads", lid)
        row = {"id": lid, "email": email, "name": r.get("name"), "company": r.get("company") or (acct or {}).get("name"),
               "domain": dom, "title": r.get("title"), "source": "event", "event": event_id,
               "received_at": (old or {}).get("received_at") or obs, "account_id": (acct or {}).get("id"),
               "contact_id": (contact or {}).get("id"), "registered": True, "attended": went}
        if not old:
            row["status"] = "new"
        ctx.store.upsert("leads", row)
        added += 0 if old else 1
        updated += 1 if old else 0
        if went:
            attended += 1
            if acct:
                sig = {"id": signal_id(acct["id"], "event_attended", f"{event_id}:{email}", obs), "account_id": acct["id"],
                       "signal_type": "event_attended", "category": "intent", "source": "event-campaigns",
                       "observed_at": obs, "payload": {"title": ev["name"], "event": ev["name"], "person": r.get("name")}}
                signals += 1 if ctx.store.add_signal(sig) else 0
    return {"event": event_id, "added": added, "updated": updated, "attended": attended, "signals_added": signals,
            "errors": errors}


# ---------- reporting ----------
def event_leads(ctx, event_id: str) -> list[dict]:
    return ctx.store.select("leads", "event=?", (event_id,))


def event_report(ctx, event_id: str) -> dict:
    ev = event(ctx, event_id)
    if not ev:
        return {"error": f"event '{event_id}' not found"}
    invites = [r for r in ctx.store.drafts(ctx.manifest.id, limit=100000)
               if r["kind"] == "event_invite" and r["meta"].get("event") == event_id]
    leads = event_leads(ctx, event_id)
    went = [l for l in leads if l.get("attended") in (True, "true", 1)]
    accts = sorted({l["account_id"] for l in went if l.get("account_id")})
    start = event_date(ev).isoformat()
    meetings = opps = 0
    for a in accts:
        for o in ctx.store.query("SELECT outcome FROM outcomes WHERE account_id=? AND observed_at>=?", (a, start)):
            meetings += o["outcome"] == "meeting"
            opps += o["outcome"] == "opportunity"
    deals = [d for a in accts for d in ctx.store.select("deals", "account_id=?", (a,))
             if (d.get("created_at") or "") >= start]
    return {"event": event_id, "name": ev["name"], "date": start, "capacity": ev.get("capacity"),
            "invited": len({r["meta"].get("email") for r in invites}),
            "invites_sent": sum(1 for r in invites if r["status"] == "sent"),
            "registered": len(leads), "attended": len(went), "no_shows": len(leads) - len(went),
            "attendance_rate": round(len(went) / len(leads), 3) if leads else None,
            "attending_accounts": accts, "meetings": meetings, "opportunities": opps,
            "new_deals": len(deals), "pipeline": round(sum(float(d.get("amount") or 0) for d in deals), 2)}


def format_report(r: dict) -> str:
    return (f"*{r['name']}* ({r['date']}): invited {r['invited']}, registered {r['registered']}, attended "
            f"{r['attended']}, no-shows {r['no_shows']}. Since the event: {r['meetings']} meetings, "
            f"{r['opportunities']} opportunities, {r['new_deals']} new deals worth ${r['pipeline']:,.0f}.")


def upcoming(ctx, now: datetime | None = None, days: int = 7) -> list[dict]:
    today = _now(now).date()
    return [e for e in events(ctx) if today <= event_date(e) <= today + timedelta(days=days)]


def finished(ctx, now: datetime | None = None, within_days: int = 14) -> list[dict]:
    today = _now(now).date()
    return [e for e in events(ctx) if today - timedelta(days=within_days) <= event_date(e) < today]
