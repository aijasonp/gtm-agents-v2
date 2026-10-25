"""ICP Outbound engine: deterministic list building, conflicts, contact picks and angles.

The model only writes copy (through gtm_core.writer, with template fallbacks).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from gtm_core import decision, engagement, personas, pipeline, profile, suppression, writer
from gtm_core.scoring import IcpProfile, icp_fit, load_taxonomy
from gtm_core.scoring.signals import decay
from gtm_core.store import now_iso

TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 9, None: 5}
STEPS = ["first_touch", "bump", "breakup"]


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    try:
        return yaml.safe_load(open(path).read()) or {}
    except OSError:
        return {}


@lru_cache(maxsize=8)
def _icp(path: str) -> IcpProfile:
    return IcpProfile.from_yaml(path)


@lru_cache(maxsize=8)
def _tax(path: str):
    return load_taxonomy(path)


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def icp(ctx) -> IcpProfile:
    return _icp(str(profile.icp_path(ctx)))


def taxonomy(ctx):
    return _tax(str(ctx.manifest.path(cfg(ctx, "taxonomy", "../signal-scout/skill/references/signal-taxonomy.yaml"))))


def dnc(ctx) -> dict:
    d = _yaml(str(ctx.manifest.path(cfg(ctx, "do_not_contact", "skill/references/do-not-contact.yaml"))))
    return {"domains": {x.lower() for x in d.get("domains") or []}, "emails": {x.lower() for x in d.get("emails") or []}}


def _now(now):
    return now or datetime.now(timezone.utc)


# ---------- candidates ----------
def latest_scores(ctx) -> dict[str, dict]:
    """Latest Signal Scout score row per account."""
    rows = ctx.store.query("SELECT * FROM scores ORDER BY id")
    out = {}
    for r in rows:
        out[r["account_id"]] = r
    return out


def conflicts(ctx, acct: dict, now: datetime | None = None) -> list[str]:
    """Reasons this account must not get outbound right now. Empty list = clear."""
    out = []
    fit, reasons = icp_fit(acct, icp(ctx))
    if reasons and reasons[0].startswith("excluded industry"):
        out.append(reasons[0])
    elif fit < float(cfg(ctx, "icp_floor", 30)):
        out.append(f"below ICP floor ({fit:.0f})")
    deals = [d for d in ctx.store.select("deals", "account_id=?", (acct["id"],)) if pipeline.is_open(d)]
    if deals:
        d = deals[0]
        out.append(f"active pipeline: {d.get('name')} ({d.get('stage')}, owner {d.get('owner')})")
    days = int(cfg(ctx, "recent_touch_days", 45))
    since = (_now(now) - timedelta(days=days)).isoformat()
    # Inbound in flight: Lead Triage owns the conversation, so no cold outbound to the account.
    domain = (acct.get("domain") or acct["id"]).lower()
    lead = next(iter(ctx.store.select(
        "leads", "(account_id=? OR LOWER(domain)=?) AND status IN ('new','routed') AND received_at>=?",
        (acct["id"], domain, since), order="received_at DESC")), None)
    if lead:
        out.append(f"inbound lead in progress ({lead.get('name')}, owner {lead.get('owner') or 'unassigned'})")
    # Anything already sent by any agent, or queued for sending by another agent.
    sent = ctx.store.one("SELECT created_at FROM drafts WHERE account_id=? AND created_at>=? AND "
                         "(status='sent' OR (status='queued' AND agent<>?)) ORDER BY id DESC LIMIT 1",
                         (acct["id"], since, ctx.manifest.id))
    if sent:
        out.append(f"contacted in the last {days} days ({sent['created_at'][:10]})")
    else:
        for c in ctx.store.select("contacts", "account_id=?", (acct["id"],)):
            lt = pipeline.days_since(c.get("last_touched"), _now(now))
            if lt is not None and lt < days:
                out.append(f"contacted in the last {days} days ({c.get('name')}, {str(c['last_touched'])[:10]})")
                break
    d = dnc(ctx)
    if (acct.get("domain") or acct["id"]).lower() in d["domains"]:
        out.append("on the do-not-contact list")
    return out


def build_list(ctx, now: datetime | None = None, limit: int | None = None) -> dict:
    """Ranked target accounts with why-now and contacts, plus every excluded account and why."""
    limit = int(limit or cfg(ctx, "list_size", 25))
    scores = latest_scores(ctx)
    ranked, excluded = [], []
    for acct in ctx.store.accounts():
        s = scores.get(acct["id"])
        fit, _ = icp_fit(acct, icp(ctx))
        row = {"account_id": acct["id"], "name": acct["name"], "tier": s["tier"] if s else None,
               "score": float(s["score"]) if s else round(fit, 1), "icp": round(fit, 1),
               "basis": "signal scout" if s else "icp only"}
        why = conflicts(ctx, acct, now)
        if not why:
            if s and s["tier"] == "X":
                why = ["out of ICP (Signal Scout tier X)"]
            elif s and s["tier"] not in cfg(ctx, "list_tiers", ["A", "B", "C"]):
                why = [f"low priority (Signal Scout tier {s['tier']}, {float(s['score']):.0f})"]
            elif not s and fit < float(cfg(ctx, "icp_only_min", 60)):
                why = [f"ICP {fit:.0f} below the ICP-only bar with no signals"]
        if why:
            excluded.append({**row, "reasons": why})
            continue
        row["contacts"] = pick_contacts(ctx, acct)
        top = row["contacts"][0] if row["contacts"] else {}
        row["why_now"] = angle(ctx, acct, now, top.get("title", ""), top.get("name", ""), account_view=True)
        if not row["contacts"]:
            row["flags"] = ["no buyer contact found"]
        ranked.append(row)
    ranked.sort(key=lambda r: (TIER_ORDER.get(r["tier"], 5), -r["score"]))
    return {"accounts": ranked[:limit], "excluded": excluded, "count": len(ranked[:limit])}


# ---------- contacts ----------
def pick_contacts(ctx, acct: dict) -> list[dict]:
    comp = profile.company(ctx).get("personas", {})
    buyer = comp.get("buyer_functions", ["sales"])
    champ = comp.get("champion_functions", [])
    min_sen = comp.get("min_seniority", "manager")
    d = dnc(ctx)
    picks = []
    for c in ctx.store.select("contacts", "account_id=?", (acct["id"],)):
        email = (c.get("email") or "").lower()
        if not email or suppression.is_suppressed(ctx.store, email, c, extra_emails=d["emails"],
                                                   extra_domains=d["domains"]):
            continue
        cls = personas.classify(c.get("title"))
        is_buyer = cls["function"] in buyer
        is_champ = cls["function"] in champ
        if not (is_buyer or is_champ):
            continue
        if cls["rank"] < personas.SENIORITY_RANK.get(min_sen, 2) and not is_champ:
            continue
        if cls["rank"] < personas.SENIORITY_RANK.get("manager", 2):
            continue
        picks.append({"contact_id": c["id"], "name": c.get("name"), "email": email, "title": c.get("title"),
                      "function": cls["function"], "seniority": cls["seniority"],
                      "role": "buyer" if is_buyer else "champion", "_rank": (cls["rank"], 1 if is_buyer else 0)})
    picks.sort(key=lambda p: p["_rank"], reverse=True)
    for p in picks:
        p.pop("_rank")
    return picks[: int(cfg(ctx, "max_contacts_per_account", 3))]


# ---------- angle ----------
def _fill(say_it: str, acct: dict, title: str = "") -> str | None:
    fn = personas.function(title) if title else "sales"
    vals = {"company": acct.get("name", ""), "team": {"revops": "RevOps", "marketing": "marketing"}.get(fn, "sales")}
    out = say_it
    for k, v in vals.items():
        out = out.replace("{" + k + "}", v)
    return None if re.search(r"\{\w+\}", out) else out


PERSON_SIGNALS = {"new_exec_in_buyer_function", "new_exec_c_suite", "champion_joined"}
STOP = {"new", "of", "the", "and", "a", "an", "joined", "hired", "named", "as", "at", "for", "&"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", (s or "").lower()) if t not in STOP}


def about_contact(signal: dict, name: str, title: str) -> bool:
    """A person-specific signal (new role, joined) may only be said to the person it is about."""
    text = f"{(signal.get('payload') or {}).get('title', '')} {(signal.get('payload') or {}).get('person', '')}"
    if name and name.lower() in text.lower():
        return True
    st, ct = _tokens(text), _tokens(title)
    return bool(st) and len(st & ct) >= max(2, int(0.6 * len(st) + 0.999))


def angle(ctx, acct: dict, now: datetime | None = None, title: str = "", name: str = "",
          account_view: bool = False) -> dict:
    """Freshest signal with a say_it line. Timing-only signals are counted but never used in copy."""
    tax = taxonomy(ctx)
    since = (_now(now) - timedelta(days=int(cfg(ctx, "lookback_days", 120)))).isoformat()
    best, timing = None, []
    for s in ctx.store.signals_for(acct["id"], since):
        st = tax.types.get(s["signal_type"])
        if not st:
            continue
        v = st.base_weight * decay(s["observed_at"], st.half_life_days, _now(now))
        if not st.say_it:
            timing.append(st.name)
            continue
        if st.type in PERSON_SIGNALS and not account_view and not about_contact(s, name, title):
            continue  # about someone else at the account; never congratulate the wrong person
        line = _fill(st.say_it, acct, title)
        if line and (best is None or v > best["value"]):
            best = {"signal_type": st.type, "signal": st.name, "observed_at": s["observed_at"][:10],
                    "say_it": line, "value": round(v, 3)}
    return {"signal": best, "timing_only": sorted(set(timing)),
            "summary": f"{best['signal']} ({best['observed_at']})" if best else "no mentionable signal; lead with value"}


FUNCTION_DEFAULT = {"revops": "deal_hygiene", "sales": "prioritization", "executive": "deal_hygiene"}


def value_prop_for(ctx, function: str) -> dict:
    vps = profile.company(ctx).get("value_props", [])
    pref = FUNCTION_DEFAULT.get(function)
    return next((v for v in vps if v.get("id") == pref), vps[0] if vps else {})


def choose_value_prop(ctx, acct: dict, function: str, now: datetime | None = None) -> dict:
    """Pick the pain to lead with. Order of evidence:
    1. the judged primary pain for this account (Signal Scout's icp_fit decision), as a prior
    2. the persona default for the contact's function, as a smaller prior
    3. what has earned opens and replies here (engagement by value prop over the learning window)
    Deterministic: same data, same pick. Returns {value_prop, why, scores}."""
    vps = profile.company(ctx).get("value_props", [])
    ids = [v["id"] for v in vps if v.get("id")]
    if not ids:
        return {"value_prop": {}, "why": "no value props in company.yaml", "scores": {}}
    d = decision.latest(ctx.store, "icp_fit", acct["id"])
    judged = ((d or {}).get("answers", {}).get("primary_pain") or {}).get("value")
    default = FUNCTION_DEFAULT.get(function)
    order = [x for x in [judged, default] if x in ids] + [x for x in ids if x not in (judged, default)]
    lc = cfg(ctx, "angle_learning", {}) or {}
    prior = {}
    if judged in ids:
        prior[judged] = float(lc.get("judged_prior", 0.08))
    if default in ids:
        prior[default] = prior.get(default, 0.0) + float(lc.get("persona_prior", 0.03))
    stats = engagement.breakdown(ctx.store, "value_prop", engagement.since_days(int(lc.get("window_days", 120)), now))
    best, scores = engagement.pick(order, stats, prior, float(lc.get("explore", 0.15)), lc.get("weights"))
    why = []
    if best == judged:
        why.append("judged primary pain for this account")
    if best == default:
        why.append(f"default for {function}")
    s = stats.get(best) or {}
    if s.get("sends"):
        why.append(f"{s['open_rate']:.0%} open, {s['reply_rate']:.0%} reply over {s['sends']} sends")
    return {"value_prop": next(v for v in vps if v.get("id") == best), "why": "; ".join(why) or "first value prop",
            "scores": scores, "judged_pain": judged}


# ---------- drafting ----------
def _lc(s: str) -> str:
    s = (s or "").rstrip(".")
    return s[:1].lower() + s[1:]


def templates(ctx, acct: dict, contact: dict, ang: dict, vp: dict | None = None) -> dict[str, str]:
    snd = profile.sender(ctx)
    vp = vp or value_prop_for(ctx, contact.get("function", "sales"))
    first = (contact.get("name") or "there").split(" ")[0]
    sig = ang.get("signal")
    label = {"revops": "RevOps", "customer_success": "customer success", "executive": "executive"}.get(
        contact.get("function", "sales"), contact.get("function", "sales"))
    opener = f"{sig['say_it']}." if sig else f"I work with {label} leaders at companies like {acct['name']}."
    outcome = _lc(vp.get("outcome", "a ranked list of accounts every morning"))
    pain = _lc(vp.get("pain", "reps lose hours building lists by hand"))
    name = snd.get("name", "")
    cal = f" Here is my calendar if easier: {snd['calendar_link']}" if snd.get("calendar_link") else ""
    return {
        "first_touch": f"Subject: {acct['name']} and {profile.company(ctx).get('company', 'us')}\nHi {first},\n\n"
                       f"{opener} Most teams we work with start with one outcome: {outcome}.\n\n"
                       f"Worth 15 minutes next week to see if it fits?\n\n{name}",
        "bump": f"Subject: Re: {acct['name']} and {profile.company(ctx).get('company', 'us')}\nHi {first},\n\n"
                f"One more thought. A common problem we hear: {pain}. "
                f"How does your team handle that today?\n\n{name}",
        "breakup": f"Subject: Re: {acct['name']} and {profile.company(ctx).get('company', 'us')}\nHi {first},\n\n"
                   f"I will stop here so I do not crowd your inbox. If {outcome} becomes a priority, "
                   f"reply and I will send a short overview.{cal}\n\n{name}",
    }


def draft_sequence(ctx, acct: dict, contact: dict, now: datetime | None = None, queue: bool = True) -> dict:
    """Draft first touch, bump and breakup; queue one sequence_enroll approval with the passing steps.
    Every guard runs here, whoever calls it (job or tool): account conflicts, the contact belongs to the
    account, do-not-contact, and no second sequence for the same contact."""
    why = conflicts(ctx, acct, now)
    email = (contact.get("email") or "").lower()
    row = (ctx.store.get("contacts", contact["contact_id"]) if contact.get("contact_id") else None) \
        or (ctx.store.contact_by_email(email) if email else None)
    if not email:
        why.append("contact has no email")
    if row and row.get("account_id") and row["account_id"] != acct["id"]:
        why.append(f"contact belongs to another account ({row['account_id']})")
    elif email and acct.get("domain") and not email.endswith("@" + acct["domain"].lower()) and not row:
        why.append(f"contact email domain does not match {acct['domain']}")
    sup = suppression.reason(ctx.store, email, row, extra_emails=dnc(ctx)["emails"],
                             extra_domains=dnc(ctx)["domains"]) if email else None
    if sup:
        why.append(f"contact must not be contacted: {sup}")
    cid = contact.get("contact_id") or (row or {}).get("id")
    if cid and already_drafted(ctx, cid):
        why.append("a sequence was already drafted for this contact")
    if why:
        return {"skipped": True, "reasons": why}
    ang = angle(ctx, acct, now, contact.get("title", ""), contact.get("name", ""))
    comp = profile.company(ctx)
    pick = choose_value_prop(ctx, acct, contact.get("function", "sales"), now)
    vp = pick["value_prop"]
    angle_key = f"signal:{ang['signal']['signal_type']}" if ang.get("signal") else "value_led"
    track = {"angle": ang["summary"], "angle_key": angle_key, "value_prop": vp.get("id"), "account_id": acct["id"]}
    tpl = templates(ctx, acct, contact, ang, vp)
    facts = {"account": {"name": acct["name"], "industry": acct.get("industry")},
             "contact": {k: contact.get(k) for k in ("name", "title", "function")},
             "reason_now": ang["signal"]["say_it"] if ang.get("signal") else None,
             "value_prop": vp,
             "proof_points": comp.get("proof_points", []), "sender": profile.sender(ctx), "our_company": comp.get("company")}
    instructions = {
        "first_touch": "Step 1 of 3: first touch. Open with reason_now if given, then one outcome, then one ask.",
        "bump": "Step 2 of 3: short bump on the same thread with one new angle as a question. No 'following up'.",
        "breakup": "Step 3 of 3: short breakup. Say you will stop, leave the door open, one soft ask.",
    }
    steps, passing, ids = [], [], []
    for step in STEPS:
        d = writer.write(ctx, f"outbound email ({step})", facts, instructions[step], tpl[step],
                         max_words=int(cfg(ctx, "max_words", 110)))
        did = ctx.store.add_draft(ctx.manifest.id, step, d.body, subject=d.subject, gate_score=d.score,
                                  gate_passed=d.passed, source=d.source, account_id=acct["id"],
                                  contact_id=contact.get("contact_id"),
                                  meta={**track, "step": step})
        steps.append({"step": step, "draft_id": did, **d.as_dict()})
        if d.passed:
            passing.append({"subject": d.subject, "body": d.body})
            ids.append(did)
    out = {"account": acct["name"], "contact": contact.get("name"), "angle": ang, "steps": steps, "approval": None,
           "value_prop": {"id": vp.get("id"), "why": pick["why"]}}
    if not steps[0]["gate_passed"]:  # never open a sequence with a bump or breakup
        out["needs_rewrite"] = steps[0]["fix"]
        passing = []
    if queue and passing:
        rid = ctx.request_approval("sequence_enroll", {
            "contact": {"email": contact["email"], "name": contact.get("name"), "company": acct["name"]},
            "steps": passing, "campaign": None, "draft_ids": ids,
            "meta": {"agent": ctx.manifest.id, **track}},
            summary=f"outbound to {contact.get('name')} ({acct['name']}): {len(passing)} steps, why now: {ang['summary']}")
        for did in ids:
            ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", rid, did))
        if contact.get("contact_id"):
            ctx.store.upsert("contacts", {"id": contact["contact_id"], "outbound_queued_at": now_iso()})
        out["approval"] = rid
    return out


def already_drafted(ctx, contact_id: str) -> bool:
    return bool(ctx.store.one("SELECT id FROM drafts WHERE agent=? AND contact_id=? AND kind='first_touch' "
                              "AND status<>'rejected'", (ctx.manifest.id, contact_id)))


def format_list(result: dict, size: int = 25) -> str:
    accts = result["accounts"][:size]
    lines = [f"*ICP Outbound: {len(accts)} target accounts this week*"]
    for i, a in enumerate(accts, 1):
        who = ", ".join(f"{c['name']} ({c['title']})" for c in a["contacts"]) or "no buyer contact found"
        tier = f"{a['tier']} {a['score']:.0f}" if a["tier"] else f"ICP {a['icp']:.0f}"
        lines.append(f"{i}. *{a['name']}* | {tier} | why now: {a['why_now']['summary']}\n   Contacts: {who}")
    conf = [e for e in result["excluded"] if any(r.startswith("active pipeline") for r in e["reasons"])]
    if conf:
        lines.append("_Skipped, active pipeline:_ " + "; ".join(
            f"{e['name']} ({next(r for r in e['reasons'] if r.startswith('active pipeline'))[17:]})" for e in conf))
    other = len(result["excluded"]) - len(conf)
    if other:
        lines.append(f"_Also skipped: {other} accounts (ICP, recent touch or do-not-contact). Ask for the list._")
    return "\n".join(lines)
