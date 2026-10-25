"""Rep Brief engine: per-rep daily brief and the push-button AE workflow.

Ranking, ownership, gaps and conflicts are deterministic. The model only drafts the first touch
(gated by the Copy QA Gate) and, optionally, a one-line opener for the brief.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from gtm_core import personas, pipeline, profile, suppression, writer
from gtm_core.scoring import IcpProfile, icp_fit, load_taxonomy
from gtm_core.scoring.signals import decay

PERSON_SIGNALS = {"new_exec_in_buyer_function", "new_exec_c_suite", "champion_joined"}
SOCIAL_MENTIONABLE = {"social_buying_question", "social_comment", "social_share"}
REPLY_KEYS = {"positive", "referral", "objection", "meeting_request", "question"}


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


def taxonomy(ctx):
    return _tax(str(ctx.manifest.path(cfg(ctx, "taxonomy", "../signal-scout/skill/references/signal-taxonomy.yaml"))))


def icp(ctx) -> IcpProfile:
    return _icp(str(profile.icp_path(ctx)))


def dnc(ctx) -> dict:
    d = _yaml(str(ctx.manifest.path(cfg(ctx, "do_not_contact", "../icp-outbound/skill/references/do-not-contact.yaml"))))
    return {"domains": {x.lower() for x in d.get("domains") or []}, "emails": {x.lower() for x in d.get("emails") or []}}


def amount(v) -> float:
    """Best-effort money parse: 12000, "12,000", "$12k", "1.2m". Unreadable values count as 0."""
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().lower().replace(",", "").replace("$", "").replace("usd", "").strip()
    mult = 1.0
    if t.endswith("k"):
        mult, t = 1e3, t[:-1]
    elif t.endswith("m"):
        mult, t = 1e6, t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return 0.0


def _now(now):
    return now or datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.replace(microsecond=0).isoformat()


# ---------- team, ownership, quota ----------
def team(ctx) -> list[dict]:
    return profile.company(ctx).get("team", {}).get("owners", [])


def owner_names(ctx) -> list[str]:
    return [o["name"] for o in team(ctx)]


def find_owner(ctx, owner: str) -> str | None:
    """Match a name or email to a team owner (case-insensitive, first name allowed when unique)."""
    o = (owner or "").strip().lower()
    for t in team(ctx):
        if o in (t["name"].lower(), (t.get("email") or "").lower()):
            return t["name"]
    first = [t["name"] for t in team(ctx) if t["name"].lower().split(" ")[0] == o]
    return first[0] if len(first) == 1 else None


def rep_quota(ctx, owner: str) -> float:
    t = next((x for x in team(ctx) if x["name"] == owner), {})
    if t.get("quota"):
        return float(t["quota"])
    q = float(profile.company(ctx).get("team", {}).get("quarter_quota") or 0)
    return round(q / max(1, len(team(ctx))), 2)


def open_deals(ctx, account_id: str | None = None) -> list[dict]:
    rows = ctx.store.select("deals", "account_id=?", (account_id,)) if account_id else ctx.store.select("deals")
    return [d for d in rows if pipeline.is_open(d)]


def assigned_owner(ctx, acct: dict) -> tuple[str | None, str]:
    """Who owns this account: CRM owner, then open-deal owner, then a stable territory assignment."""
    if acct.get("owner"):
        return acct["owner"], "crm owner"
    deals = [d for d in open_deals(ctx, acct["id"]) if d.get("owner")]
    if deals:
        return deals[0]["owner"], "open deal owner"
    owners = team(ctx)
    if not owners:
        return None, "no team configured"
    country = (acct.get("country") or "").upper()
    seg = "enterprise" if (acct.get("employees") or 0) >= int(cfg(ctx, "enterprise_employees", 1000)) else "mid_market"
    pool = [o for o in owners if country in [c.upper() for c in o.get("regions", [])] and seg in o.get("segments", [seg])] \
        or [o for o in owners if seg in o.get("segments", [seg])] or owners
    i = int(hashlib.sha1(acct["id"].encode()).hexdigest(), 16) % len(pool)  # stable, no state
    return pool[i]["name"], f"territory ({country or 'any'} / {seg})"


def latest_scores(ctx) -> dict[str, dict]:
    out = {}
    for r in ctx.store.query("SELECT * FROM scores ORDER BY id"):
        out[r["account_id"]] = r
    return out


def rep_accounts(ctx, owner: str) -> list[dict]:
    out = []
    for a in ctx.store.accounts():
        who, how = assigned_owner(ctx, a)
        if who == owner:
            out.append({**a, "_owned_by": how})
    return out


# ---------- signals and angles ----------
def _fill(say_it: str, acct: dict, sig: dict) -> str | None:
    payload = sig.get("payload") or {}
    vals = {"company": acct.get("name", ""), "team": "sales", "topic": payload.get("topic") or ""}
    out = say_it
    for k, v in vals.items():
        if v:
            out = out.replace("{" + k + "}", v)
    return None if re.search(r"\{\w+\}", out) else out


def account_signals(ctx, acct: dict, now: datetime | None = None) -> list[dict]:
    """Signals in the lookback window, freshest value first, flagged mentionable or timing only."""
    tax = taxonomy(ctx)
    since = _iso(_now(now) - timedelta(days=int(cfg(ctx, "lookback_days", 120))))
    out = []
    for s in ctx.store.signals_for(acct["id"], since):
        st = tax.types.get(s["signal_type"])
        if not st:
            continue
        line = _fill(st.say_it, acct, s) if st.say_it else None
        payload = s.get("payload") or {}
        person_only = st.type in PERSON_SIGNALS or st.type in SOCIAL_MENTIONABLE
        out.append({"signal_type": st.type, "name": st.name, "category": st.category, "observed_at": s["observed_at"][:10],
                    "created_at": s.get("created_at"), "value": round(st.base_weight * decay(s["observed_at"], st.half_life_days,
                                                                                              _now(now)), 3),
                    "say_it": line, "timing_only": not st.say_it, "about": payload.get("person") if person_only else None,
                    "contact_id": payload.get("contact_id"), "title": payload.get("title", "")})
    out.sort(key=lambda x: -x["value"])
    return out


def why_now(sigs: list[dict]) -> dict | None:
    """Best mentionable signal. Timing-only signals never appear in a why-now line."""
    s = next((x for x in sigs if x["say_it"]), None)
    if not s:
        return None
    note = f" (say only to {s['about']})" if s.get("about") else ""
    return {"signal": s["name"], "observed_at": s["observed_at"], "say_it": s["say_it"] + note, "signal_type": s["signal_type"]}


# ---------- contacts ----------
def touched_recently(ctx, contact: dict, acct_id: str, now: datetime | None = None) -> str | None:
    days = int(cfg(ctx, "recent_touch_days", 45))
    since = _iso(_now(now) - timedelta(days=days))
    lt = pipeline.days_since(contact.get("last_touched") or contact.get("outbound_queued_at") or contact.get("pushed_at"),
                             _now(now))
    if lt is not None and lt < days:
        return f"touched {lt} days ago"
    r = ctx.store.one("SELECT agent, status FROM drafts WHERE contact_id=? AND created_at>=? AND status IN ('queued','sent') "
                      "LIMIT 1", (contact["id"], since))
    if r:
        return f"{r['agent']} draft {r['status']}"
    return None


def pick_contacts(ctx, acct: dict, now: datetime | None = None, limit: int | None = None) -> list[dict]:
    comp = profile.company(ctx).get("personas", {})
    buyer, champ = comp.get("buyer_functions", ["sales"]), comp.get("champion_functions", [])
    min_rank = personas.SENIORITY_RANK.get(comp.get("min_seniority", "manager"), 2)
    d = dnc(ctx)
    engaged = {}
    for i in ctx.store.insights("social_engagement", account_id=acct["id"]):
        v = i.get("value") or {}
        if v.get("contact_id"):
            engaged[v["contact_id"]] = engaged.get(v["contact_id"], 0) + 1
    picks = []
    for c in ctx.store.select("contacts", "account_id=?", (acct["id"],)):
        email = (c.get("email") or "").lower()
        if not email or suppression.is_suppressed(ctx.store, email, c, extra_emails=d["emails"],
                                                   extra_domains=d["domains"]):
            continue
        cls = personas.classify(c.get("title"))
        is_buyer, is_champ = cls["function"] in buyer, cls["function"] in champ
        if not (is_buyer or is_champ) or cls["rank"] < 2 or (is_buyer and not is_champ and cls["rank"] < min_rank):
            continue
        touched = touched_recently(ctx, c, acct["id"], now)
        picks.append({"contact_id": c["id"], "name": c.get("name"), "email": email, "title": c.get("title"),
                      "phone": c.get("phone"), "function": cls["function"], "seniority": cls["seniority"],
                      "role": "buyer" if is_buyer else "champion", "engaged": engaged.get(c["id"], 0),
                      "touched": touched, "_rank": (touched is None, engaged.get(c["id"], 0) > 0, cls["rank"], is_buyer)})
    picks.sort(key=lambda p: p["_rank"], reverse=True)
    for p in picks:
        p.pop("_rank")
    return picks[: limit or int(cfg(ctx, "contacts_per_account", 2))]


# ---------- brief ----------
def top_accounts(ctx, owner: str, limit: int | None = None, now: datetime | None = None) -> list[dict]:
    scores = latest_scores(ctx)
    rows = []
    for a in rep_accounts(ctx, owner):
        sc = scores.get(a["id"]) or {}
        if sc.get("tier") == "X":
            continue
        fit, _ = icp_fit(a, icp(ctx))
        if not sc and fit < float(cfg(ctx, "icp_floor", 30)):
            continue
        sigs = account_signals(ctx, a, now)
        deals = open_deals(ctx, a["id"])
        hold = [] if deals else conflicts(ctx, a, owner, None, now)
        rows.append({"account_id": a["id"], "name": a["name"], "tier": sc.get("tier"), "score": sc.get("score"),
                     "icp": fit, "owned_by": a["_owned_by"], "why_now": why_now(sigs),
                     "timing_only": sorted({s["name"] for s in sigs if s["timing_only"]}),
                     "open_deal": deals[0]["name"] if deals else None, "hold": hold[0] if hold else None,
                     "contacts": [] if deals else pick_contacts(ctx, a, now)})
    rows.sort(key=lambda r: (-(r["score"] if r["score"] is not None else -1), -r["icp"]))
    return rows[: limit or int(cfg(ctx, "top_accounts", 5))]


def quarter_start(now: datetime) -> datetime:
    m = 3 * ((now.month - 1) // 3) + 1
    return datetime(now.year, m, 1, tzinfo=timezone.utc)


def latest_inspection(ctx) -> dict[str, dict]:
    out = {}
    for i in reversed(ctx.store.insights("deal_inspection")):  # oldest first, newest wins
        out[i["key"]] = i.get("value") or {}
    return out


def pipeline_gaps(ctx, owner: str, now: datetime | None = None) -> dict:
    now = _now(now)
    mine = [d for d in ctx.store.select("deals") if d.get("owner") == owner]
    opn = [d for d in mine if pipeline.is_open(d)]
    qs = quarter_start(now)
    won = sum(amount(d.get("amount")) for d in mine if pipeline.is_won(d) and pipeline.in_period(d.get("close_date"), qs, now + timedelta(days=1)))
    quota = rep_quota(ctx, owner)
    remaining = max(0.0, quota - won)
    open_amt = sum(amount(d.get("amount")) for d in opn)
    target = float(cfg(ctx, "coverage_target", 3.0))
    coverage = round(open_amt / remaining, 2) if remaining else None
    gap = round(max(0.0, target * remaining - open_amt), 2)
    idle_days = int(cfg(ctx, "idle_days", 14))
    insp = latest_inspection(ctx)
    no_next, idle, flagged = [], [], []
    for d in opn:
        try:  # one malformed deal never stops the brief
            name = d.get("name") or d.get("id")
            if not (d.get("next_step") or "").strip():
                no_next.append(name)
            elif d.get("next_step_date") and (pipeline.days_since(d["next_step_date"], now) or 0) > 0:
                no_next.append(f"{name} (next step {pipeline.days_since(d['next_step_date'], now)}d late)")
            ds = pipeline.days_since(d.get("last_activity_at"), now)
            if ds is not None and ds > idle_days:
                idle.append(f"{name} ({ds}d quiet)")
            i = insp.get(d["id"])
            if i and i.get("recommendation") in ("fix", "disqualify"):
                flagged.append({"deal": name, "recommendation": i["recommendation"], "risk": i.get("risk"),
                                "top_gap": (i.get("flags") or [""])[0]})
        except Exception as e:
            ctx.audit.log("rep_brief.bad_deal", deal=d.get("id"), error=str(e)[:200])
    flagged.sort(key=lambda f: -(f.get("risk") or 0))
    return {"owner": owner, "quota": quota, "won_qtd": won, "remaining": remaining, "open_pipeline": open_amt,
            "coverage": coverage, "coverage_target": target, "pipeline_gap": gap, "open_deals": len(opn),
            "missing_next_step": no_next, "idle": idle, "flagged": flagged}


def hot_leads(ctx, owner: str) -> list[dict]:
    rows = []
    for l in ctx.store.select("leads", "status=? AND owner=?", ("routed", owner), order="received_at DESC"):
        if l.get("tier") not in ("hot", "warm"):
            continue
        if ctx.store.one("SELECT id FROM drafts WHERE lead_id=? AND status='sent'", (l["id"],)):
            continue
        rows.append({"lead_id": l["id"], "name": l.get("name"), "company": l.get("company"), "tier": l["tier"],
                     "received_at": l.get("received_at"),
                     "score": l.get("score"), "sla_due": l.get("sla_due"), "flags": l.get("flags") or []})
    return rows


def replies_to_handle(ctx, owner: str) -> list[dict]:
    """Replies classified by a reply agent (insights kind 'reply'). Empty when that agent is not installed."""
    out = []
    for i in ctx.store.insights("reply"):
        v = i.get("value") or {}
        if i["key"] not in REPLY_KEYS or v.get("handled"):
            continue
        who = v.get("owner") or (assigned_owner(ctx, ctx.store.account(i["account_id"]) or {"id": ""})[0]
                                  if i.get("account_id") and ctx.store.account(i["account_id"]) else None)
        if who != owner:
            continue
        out.append({"kind": i["key"], "from": v.get("from") or v.get("name"), "account_id": i.get("account_id"),
                    "summary": v.get("summary") or (i.get("evidence") or "")[:140], "at": i["observed_at"]})
    return out


def new_signals(ctx, owner: str, since_iso: str | None, now: datetime | None = None) -> list[dict]:
    out = []
    for a in rep_accounts(ctx, owner):
        for s in account_signals(ctx, a, now):
            if since_iso and (s.get("created_at") or "") <= since_iso:
                continue
            out.append({"account": a["name"], "account_id": a["id"], **{k: s[k] for k in ("name", "observed_at", "timing_only")}})
    out.sort(key=lambda s: s["observed_at"], reverse=True)
    return out


def do_next(top: list[dict], gaps: dict, leads: list[dict], replies: list[dict], news: list[dict],
            now: datetime | None = None) -> list[str]:
    """Up to three actions, ranked by how soon value decays (see references/prioritization.md)."""
    acts = []
    now_s = _iso(_now(now))
    for r in replies:
        if r["kind"] in ("positive", "meeting_request"):
            acts.append(f"Reply to {r['from'] or 'a positive reply'} today and book the meeting.")
    for l in leads:
        if l["tier"] == "hot":
            due = str(l.get("sla_due") or "")
            when = "now (response time already passed)" if due and due < now_s else (
                f"before {due[11:16]} UTC" if due else "today")
            acts.append(f"Respond to hot lead {l['name']} ({l['company']}) {when}.")
    for r in replies:
        if r["kind"] in ("referral", "objection", "question"):
            acts.append(f"Handle the {r['kind']} from {r['from'] or 'a prospect'}.")
    fresh = {n["account_id"] for n in news if not n["timing_only"]}
    workable = [a for a in top if not a["open_deal"] and not a.get("hold") and a["contacts"]]
    for a in workable:
        if a["account_id"] in fresh or a["tier"] == "A":
            acts.append(f"Push-button {a['name']}: start with {a['contacts'][0]['name']} ({a['contacts'][0]['title']}).")
    for f in gaps["flagged"]:
        acts.append(f"Fix {f['deal']} ({f['recommendation']}, risk {f['risk']}): {f['top_gap'] or 'see Deal Inspection'}.")
    for n in gaps["missing_next_step"]:
        acts.append(f"Set a dated next step on {n}.")
    if gaps["pipeline_gap"] > 0:
        if workable:
            names = ", ".join(a["name"] for a in workable[:3])
            acts.append(f"Build ${gaps['pipeline_gap']:,.0f} more pipeline: push-button {names}.")
        else:
            acts.append(f"Build ${gaps['pipeline_gap']:,.0f} more pipeline: no open accounts in your territory; "
                        "ask ICP Outbound for a target list.")
    seen, out = set(), []
    for a in acts:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out[:3]


def brief(ctx, owner: str, now: datetime | None = None, since_iso: str | None = None) -> dict:
    now = _now(now)
    name = find_owner(ctx, owner) or owner
    last = since_iso if since_iso is not None else ctx.store.get_state(f"rep_brief_last:{name}")
    top = top_accounts(ctx, name, now=now)
    gaps = pipeline_gaps(ctx, name, now)
    leads = hot_leads(ctx, name)
    replies = replies_to_handle(ctx, name)
    news = new_signals(ctx, name, last, now)
    actions = do_next(top, gaps, leads, replies, news, now)
    fresh = lambda ts: not last or (ts or "") > last  # noqa: E731
    has_news = bool(news or any(fresh(l.get("received_at")) for l in leads) or any(fresh(r["at"]) for r in replies)
                    or (not last and (leads or replies or gaps["flagged"])))
    return {"owner": name, "as_of": _iso(now), "since": last, "top_accounts": top, "new_signals": news,
            "hot_leads": leads, "replies": replies, "pipeline": gaps, "do_next": actions, "has_news": has_news}


def _money(v) -> str:
    return f"${amount(v):,.0f}"


def format_brief(b: dict) -> str:
    p = b["pipeline"]
    cov = f"{p['coverage']}x" if p["coverage"] is not None else "n/a"
    lines = [f"*Your brief, {b['owner']}* ({b['as_of'][:10]})"]
    if b["do_next"]:
        lines.append("*Do next*")
        lines += [f"{i}. {a}" for i, a in enumerate(b["do_next"], 1)]
    if b["replies"]:
        lines.append("*Replies*: " + "; ".join(f"{r['kind']} from {r['from'] or 'unknown'}" for r in b["replies"][:5]))
    if b["hot_leads"]:
        lines.append("*Leads*: " + "; ".join(f"{l['name']} ({l['company']}, {l['tier']})" for l in b["hot_leads"][:5]))
    if b["top_accounts"]:
        lines.append("*Top accounts*")
        for a in b["top_accounts"]:
            tier = f"{a['tier']} {a['score']:.0f}" if a["tier"] else f"ICP {a['icp']:.0f}"
            why = f" | why now: {a['why_now']['signal']} ({a['why_now']['observed_at']})" if a["why_now"] else ""
            ppl = (" | " + ", ".join(f"{c['name']} ({c['title']})" for c in a["contacts"])) if a["contacts"] else ""
            deal = f" | open deal: {a['open_deal']}" if a["open_deal"] else (f" | hold: {a['hold']}" if a.get("hold") else "")
            lines.append(f"- {a['name']} | {tier}{why}{deal}{ppl}")
    if b["new_signals"]:
        mention = [s for s in b["new_signals"] if not s["timing_only"]]
        timing = [s for s in b["new_signals"] if s["timing_only"]]
        lines.append(f"*New signals*: {len(b['new_signals'])}" + (
            " | " + "; ".join(f"{s['account']}: {s['name']}" for s in mention[:4]) if mention else "") + (
            f" | timing only: {len(timing)}" if timing else ""))
    lines.append(f"*Pipeline*: open {_money(p['open_pipeline'])} vs {_money(p['remaining'])} left to quota "
                 f"({cov}, target {p['coverage_target']}x)" + (f" | gap {_money(p['pipeline_gap'])}" if p["pipeline_gap"] else ""))
    gaps = p["missing_next_step"] + p["idle"]
    if gaps:
        lines.append("*Deal hygiene*: " + "; ".join(gaps[:5]))
    return "\n".join(lines)


# ---------- push-button AE workflow ----------
def conflicts(ctx, acct: dict, owner: str, contact: dict | None, now: datetime | None = None) -> list[str]:
    why = []
    fit, reasons = icp_fit(acct, icp(ctx))
    if reasons and reasons[0].startswith("excluded industry"):
        why.append(reasons[0])
    for d in open_deals(ctx, acct["id"]):
        if d.get("owner") and d["owner"] != owner:
            why.append(f"open deal owned by {d['owner']}: {d['name']} ({d.get('stage')})")
    days = int(cfg(ctx, "recent_touch_days", 45))
    since = _iso(_now(now) - timedelta(days=days))
    dom = (acct.get("domain") or acct["id"]).lower()
    lead = next(iter(ctx.store.select("leads", "(account_id=? OR LOWER(domain)=?) AND status IN ('new','routed','triaging') "
                                      "AND received_at>=?", (acct["id"], dom, since), order="received_at DESC")), None)
    if lead:
        why.append(f"inbound lead in progress ({lead.get('name')}, owner {lead.get('owner') or 'unassigned'}): reply on that thread")
    sent = ctx.store.one("SELECT agent, status, created_at FROM drafts WHERE account_id=? AND created_at>=? AND "
                         "(status='sent' OR (status='queued' AND agent<>?)) ORDER BY id DESC LIMIT 1",
                         (acct["id"], since, ctx.manifest.id))
    if sent:
        why.append(f"account contacted recently ({sent['agent']} draft {sent['status']} {sent['created_at'][:10]})")
    d = dnc(ctx)
    if dom in d["domains"]:
        why.append("account is on the do-not-contact list")
    if contact:
        email = (contact.get("email") or "").lower()
        if not email:
            why.append("contact has no email")
        row = ctx.store.get("contacts", contact["contact_id"]) if contact.get("contact_id") else None
        sup = suppression.reason(ctx.store, email, row or (contact if contact.get("unsubscribed") else None),
                                 extra_emails=d["emails"], extra_domains=d["domains"]) if email else None
        if sup:
            why.append(f"contact must not be contacted: {sup}")
        if row and row.get("account_id") and row["account_id"] != acct["id"]:
            why.append(f"contact belongs to another account ({row['account_id']})")
        if row:
            t = touched_recently(ctx, row, acct["id"], now)
            if t:
                why.append(f"{contact.get('name')} {t}")
    return why


def research(ctx, acct: dict, contact: dict | None, now: datetime | None = None) -> dict:
    sc = latest_scores(ctx).get(acct["id"]) or {}
    fit, fit_reasons = icp_fit(acct, icp(ctx))
    sigs = account_signals(ctx, acct, now)
    meetings = [m for m in ctx.store.select("meetings", "account_id=?", (acct["id"],), order="started_at IS NULL, started_at DESC")
                if m.get("summary")][:2]
    insights = [{"kind": i["kind"], "key": i["key"], "evidence": (i.get("evidence") or "")[:160]}
                for i in ctx.store.insights(account_id=acct["id"]) if i["kind"] in ("competitor_mention", "objection")][:5]
    engaged = []
    if contact and contact.get("contact_id"):
        for i in ctx.store.insights("social_engagement", account_id=acct["id"]):
            v = i.get("value") or {}
            if v.get("contact_id") == contact["contact_id"]:
                engaged.append(f"{v.get('type')} on {v.get('post_title')}")
    return {"account": {k: acct.get(k) for k in ("name", "domain", "industry", "employees", "country", "revenue")},
            "icp": {"fit": fit, "reasons": fit_reasons[:3]},
            "signal_scout": {"tier": sc.get("tier"), "score": sc.get("score")},
            "signals": [{"name": s["name"], "date": s["observed_at"], "mention": bool(s["say_it"]) and not s["about"]}
                        for s in sigs[:6]],
            "open_deals": [{"name": d["name"], "stage": d.get("stage"), "owner": d.get("owner")} for d in open_deals(ctx, acct["id"])],
            "contacts": pick_contacts(ctx, acct, now, limit=5),
            "recent_meetings": [{"title": m.get("title"), "date": (m.get("started_at") or "")[:10],
                                 "pain": (m.get("summary") or {}).get("pain") if isinstance(m.get("summary"), dict) else None}
                                for m in meetings],
            "field_notes": insights, "contact_engagement": engaged[:3]}


def opener_for(sigs: list[dict], contact: dict) -> dict | None:
    """Pick a line the rep may say to THIS contact. Person-specific lines only to the person they are about."""
    for s in sigs:
        if not s["say_it"]:
            continue
        if s["signal_type"] in SOCIAL_MENTIONABLE and s.get("contact_id") != contact.get("contact_id"):
            continue
        if s["signal_type"] in PERSON_SIGNALS:
            text = f"{s.get('about') or ''} {s.get('title') or ''}".lower()
            if not (contact.get("name") and contact["name"].lower() in text):
                continue
        return s
    return None


def value_prop_for(ctx, function: str) -> dict:
    vps = profile.company(ctx).get("value_props", [])
    pref = {"revops": "deal_hygiene", "sales": "prioritization", "executive": "deal_hygiene"}.get(function)
    return next((v for v in vps if v.get("id") == pref), vps[0] if vps else {})


def _lc(s: str) -> str:
    s = (s or "").rstrip(".")
    return s[:1].lower() + s[1:]


def template_first_touch(ctx, acct: dict, contact: dict, opener: dict | None) -> str:
    snd = profile.sender(ctx)
    vp = value_prop_for(ctx, contact.get("function", "sales"))
    first = (contact.get("name") or "there").split(" ")[0]
    line1 = f"{opener['say_it']}." if opener else f"I work with {contact.get('function', 'sales')} leaders at teams like {acct['name']}."
    outcome = _lc(vp.get("outcome", "a ranked list of accounts every morning"))
    return (f"Subject: {acct['name']} and {profile.company(ctx).get('company', 'us')}\nHi {first},\n\n"
            f"{line1} Most teams we work with start with one outcome: {outcome}.\n\n"
            f"Worth 15 minutes next week to see if it fits?\n\n{snd.get('name', '')}")


def call_script(acct: dict, contact: dict, opener: dict | None, vp: dict) -> str:
    l1 = f"Reason for the call: {opener['say_it']}." if opener else f"Reason for the call: teams like {acct['name']} we work with."
    l2 = f"Problem to test: {_lc(vp.get('pain', 'how the team decides who to call each day'))}?"
    l3 = "Ask: 15 minutes next week to compare notes."
    return "\n".join([l1, l2, l3])


def push_button(ctx, account: str, contact: str | None = None, owner: str | None = None,
                now: datetime | None = None) -> dict:
    """Research, draft and queue the whole first-touch package for one contact. Nothing goes out unapproved."""
    acct = ctx.store.account(account)
    if not acct:
        return {"error": f"account '{account}' not found"}
    rep = find_owner(ctx, owner) if owner else None
    rep = rep or assigned_owner(ctx, acct)[0]
    picks = pick_contacts(ctx, acct, now, limit=5)
    c = None
    if contact:
        c = next((p for p in picks if contact.lower() in ((p["email"] or ""), p["contact_id"].lower(), (p["name"] or "").lower())), None)
        if c is None:
            row = ctx.store.contact_by_email(contact) or ctx.store.get("contacts", contact)
            if not row:
                return {"error": f"contact '{contact}' not found"}
            cls = personas.classify(row.get("title"))
            c = {"contact_id": row["id"], "name": row.get("name"), "email": (row.get("email") or "").lower(),
                 "title": row.get("title"), "phone": row.get("phone"), "function": cls["function"],
                 "seniority": cls["seniority"], "role": "manual"}
    elif picks:
        c = next((p for p in picks if not p["touched"]), None)
    if not c:
        return {"account": acct["name"], "refused": True, "reasons": ["no reachable buyer contact at this account"],
                "research": research(ctx, acct, None, now)}
    why = conflicts(ctx, acct, rep, c, now)
    brief_ = research(ctx, acct, c, now)
    if why:
        return {"account": acct["name"], "contact": c["name"], "owner": rep, "refused": True, "reasons": why,
                "research": brief_}
    sigs = account_signals(ctx, acct, now)
    op = opener_for(sigs, c)
    vp = value_prop_for(ctx, c.get("function", "sales"))
    comp = profile.company(ctx)
    facts = {"account": brief_["account"], "contact": {k: c.get(k) for k in ("name", "title", "function")},
             "reason_now": op["say_it"] if op else None, "value_prop": vp, "proof_points": comp.get("proof_points", []),
             "sender": profile.sender(ctx), "our_company": comp.get("company"),
             "field_notes": [n["evidence"] for n in brief_["field_notes"]][:2]}
    d = writer.write(ctx, "first-touch email from an account executive", facts,
                     "One reason to write now (reason_now if given), one outcome, one ask. Under 110 words.",
                     template_first_touch(ctx, acct, c, op), max_words=int(cfg(ctx, "max_words", 110)))
    did = ctx.store.add_draft(ctx.manifest.id, "push_button_first_touch", d.body, subject=d.subject, gate_score=d.score,
                              gate_passed=d.passed, source=d.source, account_id=acct["id"], contact_id=c["contact_id"],
                              meta={"owner": rep, "opener": op["signal_type"] if op else None})
    out = {"account": acct["name"], "contact": c["name"], "owner": rep, "refused": False, "research": brief_,
           "draft": {**d.as_dict(), "draft_id": did}, "approvals": []}
    if not d.passed:  # the package goes together or not at all
        ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("needs_rewrite", did))
        out["needs_rewrite"] = d.fix
        return out
    script = call_script(acct, c, op, vp)
    rid = ctx.request_approval("sequence_enroll", {
        "contact": {"email": c["email"], "name": c["name"], "company": acct["name"]},
        "steps": [{"subject": d.subject, "body": d.body}], "campaign": None, "draft_ids": [did],
        "meta": {"agent": ctx.manifest.id, "owner": rep}},
        summary=f"{rep}: push-button first touch to {c['name']} ({acct['name']}), gate {d.score}/40")
    ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", rid, did))
    out["approvals"].append(rid)
    out["approvals"].append(ctx.request_approval("crm_task", {
        "subject": f"Push-button: follow up with {c['name']} at {acct['name']}",
        "body": f"Email queued (draft #{did}).\nCall script:\n{script}",
        "due_at": _iso(_now(now) + timedelta(days=2))[:10], "account_crm_id": acct.get("crm_id"), "owner": rep}))
    if c.get("phone"):
        out["approvals"].append(ctx.request_approval("dialer_enqueue", {
            "contact": {"name": c["name"], "phone": c["phone"], "email": c["email"], "company": acct["name"]},
            "owner": rep, "script": script, "meta": {"agent": ctx.manifest.id, "draft_id": did}}))
    out["call_script"] = script
    ctx.store.upsert("contacts", {"id": c["contact_id"], "pushed_at": _iso(_now(now))})
    return out
