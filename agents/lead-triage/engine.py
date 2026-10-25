"""Lead Triage engine: deterministic qualification, routing and SLA. The model only drafts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from gtm_core import personas, pipeline, profile, suppression
from gtm_core.scoring import IcpProfile, icp_fit


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    return yaml.safe_load(open(path).read()) or {}


@lru_cache(maxsize=8)
def _icp(path: str) -> IcpProfile:
    return IcpProfile.from_yaml(path)


def rules(ctx) -> dict:
    return _yaml(str(ctx.manifest.path(ctx.manifest.config.get("routing", "skill/references/routing.yaml"))))


def icp(ctx) -> IcpProfile:
    return _icp(str(profile.icp_path(ctx)))


def _now(now):
    return now or datetime.now(timezone.utc)


def open_deals(ctx, account_id: str | None) -> list[dict]:
    if not account_id:
        return []
    return [d for d in ctx.store.select("deals", "account_id=?", (account_id,)) if pipeline.is_open(d)]


def latest_heat(ctx, account_id: str | None) -> float:
    if not account_id:
        return 0.0
    r = ctx.store.one("SELECT signal_score FROM scores WHERE account_id=? ORDER BY id DESC LIMIT 1", (account_id,))
    return float(r["signal_score"]) if r and r["signal_score"] is not None else 0.0


def evaluate(ctx, lead: dict, commit: bool = False) -> dict:
    """Score, classify and pick an owner for one lead. Pure read unless commit=True (advances round robin)."""
    r = rules(ctx)
    comp = profile.company(ctx)
    email = (lead.get("email") or "").lower()
    domain = (lead.get("domain") or (email.split("@", 1)[1] if "@" in email else "")).lower()
    free = domain in [d.lower() for d in r.get("free_email_domains", [])]
    acct = None if free else ctx.store.account_by_domain(domain)
    contact = ctx.store.contact_by_email(email) if email else None
    flags, reasons = [], []

    # ICP part: known account, else whatever firmographics came on the form
    firmo = acct or {"industry": lead.get("industry"), "employees": _int(lead.get("employees")),
                     "country": lead.get("country"), "revenue": None}
    fit, fit_reasons = icp_fit(firmo, icp(ctx))
    if free:
        fit, fit_reasons = 50.0, ["free email domain: company unverified"]
        flags.append("verify company (free email domain)")
    excluded = bool(fit_reasons and fit_reasons[0].startswith("excluded industry"))

    pm = personas.persona_match(lead.get("title"), comp.get("personas", {}).get("buyer_functions", ["sales"]),
                                comp.get("personas", {}).get("min_seniority", "manager"))
    si = r.get("source_intent", {})
    intent = float(si.get((lead.get("source") or "").lower(), si.get("default", 40)))
    if (lead.get("message") or "").strip():
        intent = min(100.0, intent + 10)
    heat = latest_heat(ctx, acct["id"] if acct else None)

    w = r.get("weights", {"icp": 0.35, "persona": 0.25, "intent": 0.30, "heat": 0.10})
    score = round(w["icp"] * fit + w["persona"] * pm["score"] + w["intent"] * intent + w["heat"] * heat, 1)
    reasons += [f"ICP {fit:.0f} ({'; '.join(fit_reasons[:2])})", f"persona {pm['score']} ({pm['why']})",
                f"intent {intent:.0f} ({lead.get('source') or 'unknown source'})"]
    if heat:
        reasons.append(f"account heat {heat:.0f}")

    # hard rules
    deals = open_deals(ctx, acct["id"] if acct else None)
    title = (lead.get("title") or "").lower()
    dq_reason = None
    if excluded:
        dq_reason = fit_reasons[0]
    elif any(t in title for t in r.get("disqualify_titles", [])):
        dq_reason = f"title not a buyer: {lead.get('title')}"
    elif free and not (lead.get("company") or "").strip():
        dq_reason = "free email and no company"

    tier, sla = "disqualify", 0
    if not dq_reason:
        for t in sorted(r.get("tiers", []), key=lambda t: -t["min"]):
            if score >= t["min"]:
                tier, sla = t["tier"], int(t.get("sla_minutes", 0))
                break
    if deals:
        flags.insert(0, f"ACTIVE PIPELINE: {deals[0]['name']} ({deals[0].get('stage')}, owner {deals[0].get('owner')})")
        if tier in ("nurture", "disqualify") and not dq_reason:
            tier, sla = "warm", 240

    if acct:
        queued = ctx.store.one("SELECT d.id, d.agent FROM drafts d JOIN approvals a ON a.id = d.approval_id "
                               "WHERE d.account_id=? AND d.agent<>? AND d.status='queued' AND a.status='pending' LIMIT 1",
                               (acct["id"], ctx.manifest.id))
        if queued:
            flags.append(f"cold outbound already queued for this account ({queued['agent']} draft #{queued['id']}): "
                         "reject that approval so the inbound reply goes alone")
    sup = suppression.reason(ctx.store, email) if email else None
    if sup:
        flags.insert(1 if deals else 0, f"DO NOT CONTACT: {sup}. Owner decides by hand; no automated outreach")
    owner, how = route(ctx, lead, acct, deals, commit)
    return {"lead_id": lead.get("id"), "email": email, "name": lead.get("name"), "company": lead.get("company") or (acct or {}).get("name"),
            "account_id": acct["id"] if acct else None, "contact_id": contact["id"] if contact else None,
            "score": score, "tier": tier, "sla_minutes": sla, "owner": owner, "routed_by": how,
            "active_pipeline": bool(deals), "deal_id": deals[0]["id"] if deals else None,
            "deal_crm_id": deals[0].get("crm_id") if deals else None, "account_crm_id": (acct or {}).get("crm_id"),
            "disqualify_reason": dq_reason, "flags": flags, "reasons": reasons, "persona": pm, "suppressed": sup}


def _int(v):
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def route(ctx, lead: dict, acct: dict | None, deals: list[dict], commit: bool = False) -> tuple[str | None, str]:
    if deals and deals[0].get("owner"):
        return deals[0]["owner"], "deal owner"
    if acct and acct.get("owner"):
        return acct["owner"], "account owner"
    owners = profile.company(ctx).get("team", {}).get("owners", [])
    if not owners:
        return None, "no owners configured"
    country = ((acct or {}).get("country") or lead.get("country") or "").upper()
    employees = (acct or {}).get("employees") or _int(lead.get("employees")) or 0
    segment = "enterprise" if employees >= int(rules(ctx).get("enterprise_employees", 1000)) else "mid_market"
    in_region = lambda o: not country or country in [c.upper() for c in o.get("regions", [])]
    in_segment = lambda o: segment in o.get("segments", [segment])
    pool, how = owners, "round robin (no match)"
    for test, label in ((lambda o: in_region(o) and in_segment(o), f"region {country or 'any'} / {segment}"),
                        (in_segment, f"segment {segment} (no owner covers {country or 'region'})"),
                        (in_region, f"region {country} (no {segment} owner)")):
        match = [o for o in owners if test(o)]
        if match:
            pool, how = match, label
            break
    key = "lead_triage_rr:" + ",".join(sorted(o["name"] for o in pool))
    i = int(ctx.store.get_state(key, 0))
    if commit:  # previews must not change who gets the next lead
        ctx.store.set_state(key, i + 1)
    return pool[i % len(pool)]["name"], how


def value_prop_for(ctx, function: str) -> dict:
    vps = profile.company(ctx).get("value_props", [])
    pref = {"revops": "deal_hygiene", "sales": "prioritization", "executive": "deal_hygiene"}.get(function)
    return next((v for v in vps if v.get("id") == pref), vps[0] if vps else {})


def template_follow_up(ctx, lead: dict, ev: dict) -> str:
    snd = profile.sender(ctx)
    vp = value_prop_for(ctx, ev["persona"]["function"])
    first = (lead.get("name") or "there").split(" ")[0]
    company = ev.get("company") or "your team"
    src = (lead.get("source") or "").lower()
    if src == "event" and lead.get("event"):
        opener = f"Good to meet you at {lead['event']}."
    elif src in ("demo_request", "contact_sales", "pricing", "trial_signup"):
        opener = "Thanks for asking for a walkthrough."
    else:
        opener = "Thanks for checking out our material."
    outcome = vp.get("outcome", "").rstrip(".")
    line2 = f"Most teams start with one outcome: {outcome[0].lower() + outcome[1:]}." if outcome else ""
    ask = f"Does Tuesday or Wednesday next week work for 20 minutes? Or grab a time here: {snd['calendar_link']}" \
        if snd.get("calendar_link") else "Does Tuesday or Wednesday next week work for 20 minutes?"
    subj = f"{company} and {profile.company(ctx).get('company', 'us')}"
    return f"Subject: {subj}\nHi {first},\n\n{opener} {line2}\n\n{ask}\n\n{snd.get('name', '')}".strip()


def sla_due(received_at: str | None, minutes: int, now: datetime | None = None) -> str | None:
    if not minutes:
        return None
    start = pipeline.parse_dt(received_at) or _now(now)
    return (start + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def draft(ctx, lead: dict, ev: dict):
    from gtm_core import writer
    comp = profile.company(ctx)
    facts = {"lead": {k: lead.get(k) for k in ("name", "title", "company", "source", "event", "message")},
             "persona": ev["persona"]["why"], "value_prop": value_prop_for(ctx, ev["persona"]["function"]),
             "proof_points": comp.get("proof_points", []), "sender": profile.sender(ctx),
             "our_company": comp.get("company"), "product": comp.get("one_liner")}
    return writer.write(ctx, "first follow-up email to an inbound lead", facts,
                        "Follow references/follow-up-patterns.md for this lead source. Reference what they asked for.",
                        template_follow_up(ctx, lead, ev), max_words=int(ctx.manifest.config.get("max_words", 110)))


def process(ctx, lead: dict, now: datetime | None = None) -> dict:
    """Triage one lead end to end: evaluate, persist, draft, queue approvals.
    Idempotent: the lead is claimed atomically (new -> triaging), so a second call or a racing job does nothing."""
    if not ctx.store.execute("UPDATE leads SET status=? WHERE id=? AND status=?", ("triaging", lead["id"], "new")):
        cur = ctx.store.get("leads", lead["id"]) or {}
        return {"lead_id": lead["id"], "skipped": f"already triaged (status {cur.get('status')})",
                "status": cur.get("status"), "tier": cur.get("tier"), "owner": cur.get("owner"), "approvals": []}
    ev = evaluate(ctx, lead, commit=True)
    due = sla_due(lead.get("received_at"), ev["sla_minutes"], now)
    status = "disqualified" if ev["tier"] == "disqualify" else ("nurture" if ev["tier"] == "nurture" else "routed")
    ctx.store.upsert("leads", {"id": lead["id"], "status": status, "score": ev["score"], "tier": ev["tier"],
                               "owner": ev["owner"], "account_id": ev["account_id"], "contact_id": ev["contact_id"],
                               "sla_due": due, "flags": ev["flags"], "reasons": ev["reasons"],
                               "triaged_at": _now(now).replace(microsecond=0).isoformat()})
    out = {**ev, "sla_due": due, "status": status, "approvals": [], "draft": None}
    if status != "routed":
        return out

    if ev.get("suppressed") and not ev["active_pipeline"]:
        # Opted out or bounced before: a person reviews it; nothing is drafted or sent automatically.
        rid = ctx.request_approval("crm_task", {
            "subject": f"Inbound from {lead.get('name')} ({lead.get('title')}): previously opted out",
            "body": f"{lead.get('source')}: {lead.get('message') or 'no message'}\n{ev['suppressed']}\n"
                    "They asked to hear from us again only if this request says so. Reply by hand if appropriate.",
            "due_at": due, "account_crm_id": ev["account_crm_id"], "owner": ev["owner"]},
            summary=f"{ev['owner']}: inbound from {lead.get('name')} who previously opted out (review by hand)")
        out["approvals"].append(rid)
        return out

    if ev["active_pipeline"]:
        rid = ctx.request_approval("crm_task", {
            "subject": f"Inbound from {lead.get('name')} ({lead.get('title')}) on open deal",
            "body": f"{lead.get('source')}: {lead.get('message') or 'no message'}\n" + "\n".join(ev["reasons"]),
            "due_at": due, "deal_crm_id": ev["deal_crm_id"], "account_crm_id": ev["account_crm_id"], "owner": ev["owner"]},
            summary=f"{ev['owner']}: inbound on open deal {ev['company']} from {lead.get('name')}")
        out["approvals"].append(rid)
        return out

    d = draft(ctx, lead, ev)
    did = ctx.store.add_draft(ctx.manifest.id, "lead_follow_up", d.body, subject=d.subject, gate_score=d.score,
                              gate_passed=d.passed, source=d.source, lead_id=lead["id"], account_id=ev["account_id"],
                              contact_id=ev["contact_id"], meta={"tier": ev["tier"], "owner": ev["owner"]})
    out["draft"] = {**d.as_dict(), "draft_id": did}
    if not ev["contact_id"]:
        out["approvals"].append(ctx.request_approval("crm_contact", {
            "fields": {"name": lead.get("name"), "email": ev["email"], "title": lead.get("title")},
            "account_crm_id": ev["account_crm_id"]}))
    out["approvals"].append(ctx.request_approval("crm_task", {
        "subject": f"{ev['tier'].upper()} lead: {lead.get('name')} at {ev['company']} (respond by {due})",
        "body": "\n".join(ev["reasons"] + ev["flags"]), "due_at": due, "account_crm_id": ev["account_crm_id"],
        "owner": ev["owner"]}))
    if d.passed:
        rid = ctx.request_approval("sequence_enroll", {
            "contact": {"email": ev["email"], "name": lead.get("name"), "company": ev["company"]},
            "steps": [{"subject": d.subject, "body": d.body}], "campaign": None, "draft_ids": [did],
            "meta": {"agent": "lead-triage", "tier": ev["tier"], "owner": ev["owner"]}},
            summary=f"{ev['tier']} lead {lead.get('name')} ({ev['company']}) -> {ev['owner']}: send first follow-up (gate {d.score}/40)")
        ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", rid, did))
        out["approvals"].append(rid)
    return out


def digest(results: list[dict]) -> str:
    if not results:
        return "*Lead Triage*: no new leads."
    order = {"hot": 0, "warm": 1, "nurture": 2, "disqualify": 3}
    rs = sorted(results, key=lambda r: (not r["active_pipeline"], order.get(r["tier"], 9), -r["score"]))
    counts = {t: sum(1 for r in results if r["tier"] == t) for t in order}
    lines = [f"*Lead Triage: {len(results)} new* (hot {counts['hot']}, warm {counts['warm']}, "
             f"nurture {counts['nurture']}, disqualified {counts['disqualify']})"]
    for r in rs:
        if r["tier"] == "disqualify":
            lines.append(f"- {r['name']} ({r['company'] or r['email']}): disqualified, {r['disqualify_reason']}")
            continue
        flag = f" | {r['flags'][0]}" if r["flags"] else ""
        due = f" | respond by {r['sla_due'][11:16]} UTC" if r.get("sla_due") and r["tier"] in ("hot", "warm") else ""
        lines.append(f"- *{r['name']}* ({r['company']}) | {r['tier']} {r['score']:.0f} | {r['owner']}{due}{flag}")
    return "\n".join(lines)
