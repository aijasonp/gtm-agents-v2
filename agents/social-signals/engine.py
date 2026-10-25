"""Social Signals engine: engagement exports -> resolved people -> scored signals -> owner alerts.

Everything here is deterministic. No model is needed to resolve, score or alert.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from gtm_core import personas, pipeline, profile, suppression
from gtm_core.scoring import load_taxonomy, signal_id

# Engagement type aliases -> canonical type
TYPE_ALIASES = {
    "like": "reaction", "reaction": "reaction", "react": "reaction", "love": "reaction", "celebrate": "reaction",
    "insightful": "reaction", "support": "reaction", "funny": "reaction", "curious": "reaction",
    "comment": "comment", "reply": "comment",
    "share": "share", "repost": "share", "reshare": "share", "quote": "share",
    "follow": "follow", "subscribe": "follow", "subscription": "follow",
    "view": "view", "watch": "view", "impression": "view",
}
# Relative value of each canonical engagement type (used for ranking people, not for Signal Scout weights)
TYPE_POINTS = {"comment": 5.0, "share": 4.0, "follow": 2.5, "reaction": 1.0, "view": 0.5}
INTENT_TERMS = {"pricing": r"\bpric(?:e|ing)\b", "evaluating": r"\bevaluat", "demo": r"\bdemo\b",
                "migration": r"\bmigrat", "replacing": r"\breplac", "how-to question": r"\bhow (?:do|does|would) (?:you|i|we|it)\b",
                "cost": r"\bcost\b", "trial": r"\btrial\b", "integration": r"\bintegrat", "comparison": r"\bcompar|\bvs\.?\s",
                "alternatives": r"\balternative"}
COMPANY_SUFFIXES = r"\b(inc|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|ag|bv|pty|group|holdings)\b\.?"


@lru_cache(maxsize=8)
def _tax(path: str):
    return load_taxonomy(path)


def taxonomy(ctx):
    return _tax(str(ctx.manifest.path(ctx.manifest.config.get("taxonomy",
                                                               "../signal-scout/skill/references/signal-taxonomy.yaml"))))


def _now(now):
    return now or datetime.now(timezone.utc)


# ---------- normalizing ----------
def norm_url(u: str | None) -> str:
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^(www\.|[a-z]{2}\.)(?=linkedin\.com)", "", u)
    u = re.sub(r"^www\.", "", u)
    return re.sub(r"[?#].*$", "", u).rstrip("/")


def norm_company(name: str | None) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"[,.()]", " ", n)
    n = re.sub(COMPANY_SUFFIXES, " ", n)
    return re.sub(r"\s+", " ", n).strip()


def norm_name(name: str | None) -> str:
    """Casefolded name that keeps letters in any script (names in Chinese, Arabic, Cyrillic never collide)."""
    t = unicodedata.normalize("NFKC", name or "").casefold()
    t = "".join(ch if (ch.isalnum() or ch.isspace() or ch in "'-") else " " for ch in t)
    return re.sub(r"\s+", " ", t).strip()


def canonical_type(t: str | None) -> str | None:
    return TYPE_ALIASES.get((t or "").strip().lower())


def normalize_row(r: dict) -> dict:
    """Map common export column names onto one shape."""
    g = lambda *ks: next((str(r[k]).strip() for k in ks if r.get(k) not in (None, "")), "")  # noqa: E731
    return {
        "platform": g("platform", "network", "source").lower() or "linkedin",
        "post_url": g("post_url", "url", "video_url", "post_link"),
        "post_title": g("post_title", "title", "video_title", "post_text", "topic"),
        "author": g("author", "creator", "page", "channel") or "company",
        "engager_name": g("engager_name", "name", "full_name", "commenter", "profile_name"),
        "engager_title": g("engager_title", "engager_headline", "headline", "title_of_engager", "job_title"),
        "engager_company": g("engager_company", "company", "company_name", "organization"),
        "engager_profile_url": g("engager_profile_url", "profile_url", "linkedin_url", "channel_url"),
        "engager_email": g("engager_email", "email").lower(),
        "engagement_type": g("engagement_type", "type", "action", "reaction_type"),
        "comment_text": g("comment_text", "comment", "text"),
        "engaged_at": g("engaged_at", "timestamp", "date", "created_at"),
    }


def engagement_id(row: dict) -> str:
    who = norm_url(row["engager_profile_url"]) or f"{norm_name(row['engager_name'])}|{norm_company(row['engager_company'])}"
    day = (row.get("engaged_at") or "")[:10]
    raw = f"{who}|{norm_url(row['post_url']) or row['post_title'].lower()}|{canonical_type(row['engagement_type'])}|{day}"
    return "eng-" + hashlib.sha1(raw.encode()).hexdigest()[:16]


# ---------- identity resolution ----------
def account_for_company(ctx, company: str) -> dict | None:
    c = norm_company(company)
    if not c:
        return None
    if "." in company and " " not in company.strip():  # looks like a domain
        a = ctx.store.account_by_domain(company.strip().lower())
        if a:
            return a
    for a in ctx.store.accounts():
        if norm_company(a.get("name")) == c:
            return a
        dom = (a.get("domain") or "").split(".")[0]
        if dom and dom == c.replace(" ", ""):
            return a
    return None


def resolve(ctx, name: str = "", company: str = "", profile_url: str = "", email: str = "") -> dict:
    """Match an engager to a contact and account. Returns method, confidence and a stable person key."""
    pu, nm = norm_url(profile_url), norm_name(name)
    contacts = ctx.store.select("contacts")
    if pu:
        for c in contacts:
            if c.get("linkedin") and norm_url(c["linkedin"]) == pu:
                return {"contact_id": c["id"], "account_id": c.get("account_id"), "method": "profile url",
                        "confidence": 0.98, "person_key": c["id"], "contact": c}
    if email:
        c = ctx.store.contact_by_email(email)
        if c:
            return {"contact_id": c["id"], "account_id": c.get("account_id"), "method": "email", "confidence": 0.95,
                    "person_key": c["id"], "contact": c}
        acct = ctx.store.account_by_domain(email.split("@")[-1])
    else:
        acct = None
    acct = acct or account_for_company(ctx, company)
    if nm:
        same = [c for c in contacts if norm_name(c.get("name")) == nm]
        if acct:
            here = [c for c in same if c.get("account_id") == acct["id"]]
            if len(here) == 1:
                return {"contact_id": here[0]["id"], "account_id": acct["id"], "method": "name + company",
                        "confidence": 0.85, "person_key": here[0]["id"], "contact": here[0]}
    key = pu or f"{nm}|{norm_company(company)}"
    if acct:
        return {"contact_id": None, "account_id": acct["id"], "method": "company only (person not in CRM)",
                "confidence": 0.6, "person_key": key, "contact": None}
    return {"contact_id": None, "account_id": None, "method": "unresolved", "confidence": 0.0, "person_key": key,
            "contact": None}


# ---------- scoring ----------
def buying_intent(text: str) -> list[str]:
    t = (text or "").lower()
    return [label for label, p in INTENT_TERMS.items() if re.search(p, t)]


def competitor_mentions(ctx, text: str) -> list[str]:
    t = (text or "").lower()
    return [c for c in profile.competitors(ctx) if re.search(r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?![a-z0-9])", t)]


def creator_weight(ctx, author: str) -> float | None:
    """Weight for whose content it was. None = not a tracked creator (ignored)."""
    tracked = ctx.manifest.config.get("tracked_creators") or [{"name": "company", "weight": 1.0}]
    a = (author or "company").strip().lower()
    comp = (profile.company(ctx).get("company") or "").lower()
    for t in tracked:
        n = str(t.get("name", "")).lower()
        if a == n or (n == "company" and (a in ("company", "", comp) or (comp and comp in a))):
            return float(t.get("weight", 1.0))
    return None


def signal_type_for(ctype: str, comment: str, repeat_views: int) -> str | None:
    if ctype == "comment":
        return "social_buying_question" if buying_intent(comment) else "social_comment"
    return {"share": "social_share", "follow": "social_follow", "reaction": "social_reaction"}.get(ctype) or (
        "content_view_repeat" if ctype == "view" and repeat_views >= 2 else None)


def persona_factor(ctx, title: str) -> tuple[float, str]:
    if not (title or "").strip():
        return 0.6, "no title"
    comp = profile.company(ctx).get("personas", {})
    pm = personas.persona_match(title, comp.get("buyer_functions", ["sales"]), comp.get("min_seniority", "manager"))
    if pm["match"]:
        return 1.0, pm["why"]
    if pm["function"] in comp.get("champion_functions", []):
        return 0.85, pm["why"] + " (possible champion)"
    return 0.6, pm["why"]


def prior_engagements(ctx, person_key: str, now: datetime, days: int) -> list[dict]:
    since = (now - timedelta(days=days)).isoformat()
    out = []
    for i in ctx.store.insights("social_engagement", since_iso=since):
        v = i.get("value") or {}
        if v.get("person_key") == person_key:
            out.append(v)
    return out


# ---------- ingest ----------
def ingest(ctx, rows: list[dict], now: datetime | None = None) -> dict:
    """Process engagement rows. Idempotent: the same person, post, type and day is counted once."""
    now = _now(now)
    tax = taxonomy(ctx)
    cfg = ctx.manifest.config
    days = int(cfg.get("repeat_window_days", 30))
    results, stats = [], {"rows": 0, "duplicates": 0, "skipped": 0, "resolved_contact": 0, "account_only": 0,
                          "unresolved": 0, "signals": 0, "proposed_contacts": 0}
    for raw in rows:
        stats["rows"] += 1
        r = normalize_row(raw)
        ctype = canonical_type(r["engagement_type"])
        cw = creator_weight(ctx, r["author"])
        when = pipeline.parse_dt(r["engaged_at"]) or now
        r["engaged_at"] = when.replace(microsecond=0).isoformat()
        if not ctype or cw is None or not (r["engager_name"] or r["engager_profile_url"] or r["engager_email"]):
            stats["skipped"] += 1
            continue
        eid = engagement_id(r)
        if ctx.store.one("SELECT id FROM insights WHERE kind='social_engagement' AND key=?", (eid,)):
            stats["duplicates"] += 1
            continue
        who = resolve(ctx, r["engager_name"], r["engager_company"], r["engager_profile_url"], r["engager_email"])
        title = r["engager_title"] or ((who.get("contact") or {}).get("title") or "")
        pf, why = persona_factor(ctx, title)
        prior = prior_engagements(ctx, who["person_key"], when, days)
        views = 1 + sum(1 for p in prior if p.get("type") == "view") if ctype == "view" else 0
        repeat = min(1.5, 1 + 0.25 * len(prior))
        intent = buying_intent(r["comment_text"]) if ctype == "comment" else []
        comps = competitor_mentions(ctx, r["comment_text"]) if ctype == "comment" else []
        strength = round(min(float(cfg.get("max_strength", 1.5)), pf * repeat * cw), 3)
        stype = signal_type_for(ctype, r["comment_text"], views)
        rec = {"eid": eid, "engaged_at": r["engaged_at"], "type": ctype, "platform": r["platform"], "author": r["author"], "post_url": r["post_url"],
               "post_title": r["post_title"], "person_key": who["person_key"], "name": r["engager_name"],
               "title": title, "company": r["engager_company"], "profile_url": r["engager_profile_url"],
               "contact_id": who["contact_id"], "account_id": who["account_id"], "method": who["method"],
               "confidence": who["confidence"], "persona": why, "repeat": len(prior), "strength": strength,
               "intent_terms": intent, "competitors": comps, "signal_type": stype,
               "points": round(TYPE_POINTS[ctype] * pf * repeat * cw * (1.5 if intent else 1.0), 2)}
        ctx.store.add_insight(ctx.manifest.id, "social_engagement", eid, rec,
                              evidence=(r["comment_text"] or "")[:500], observed_at=rec_ts(when),
                              account_id=who["account_id"])
        stats["resolved_contact" if who["contact_id"] else ("account_only" if who["account_id"] else "unresolved")] += 1
        if comps:
            ctx.store.add_insight(ctx.manifest.id, "competitor_mention", comps[0], {"source": "social comment"},
                                  evidence=r["comment_text"][:500], observed_at=rec_ts(when), account_id=who["account_id"])
        if who["account_id"] and stype and stype in tax.types:
            sig = {"id": signal_id(who["account_id"], stype, f"{who['person_key']}|{norm_url(r['post_url']) or r['post_title']}",
                                   rec["engaged_at"]),
                   "account_id": who["account_id"], "signal_type": stype, "category": tax.types[stype].category,
                   "source": f"social:{r['platform']}", "url": r["post_url"] or None, "observed_at": rec["engaged_at"],
                   "strength": strength,
                   "payload": {"title": f"{r['engager_name'] or 'Someone'} {ctype} on {r['post_title'] or 'a post'}",
                               "topic": r["post_title"], "person": r["engager_name"], "contact_id": who["contact_id"],
                               "author": r["author"]}}
            if ctx.store.add_signal(sig):
                stats["signals"] += 1
                rec["signal_id"] = sig["id"]
        rec["proposal"] = maybe_propose_contact(ctx, rec)
        if rec["proposal"]:
            stats["proposed_contacts"] += 1
        results.append(rec)
    return {"stats": stats, "results": results}


def rec_ts(d: datetime) -> str:
    return d.replace(microsecond=0).isoformat()


def is_target(ctx, account_id: str) -> bool:
    deals = [d for d in ctx.store.select("deals", "account_id=?", (account_id,)) if pipeline.is_open(d)]
    if deals:
        return True
    r = ctx.store.one("SELECT tier FROM scores WHERE account_id=? ORDER BY id DESC LIMIT 1", (account_id,))
    return bool(r and r["tier"] in ("A", "B"))


def maybe_propose_contact(ctx, rec: dict) -> int | None:
    """New buyer-persona person engaging at a target account: propose adding them to the CRM (approval)."""
    if not ctx.manifest.config.get("propose_contacts", True):
        return None
    if rec["contact_id"] or not rec["account_id"] or not rec["name"] or "not a buyer" in rec["persona"]:
        return None
    if rec["persona"] == "no title" or not is_target(ctx, rec["account_id"]):
        return None
    key = f"social_proposed:{rec['person_key']}"
    if ctx.store.get_state(key):
        return None
    acct = ctx.store.account(rec["account_id"]) or {}
    rid = ctx.request_approval("crm_contact", {
        "fields": {"name": rec["name"], "title": rec["title"], "linkedin": rec["profile_url"] or None},
        "account_crm_id": acct.get("crm_id")},
        summary=f"New person engaging at {acct.get('name')}: {rec['name']} ({rec['title']}). Add to CRM?")
    ctx.store.set_state(key, rid)
    return rid


# ---------- owners and alerts ----------
def owner_for(ctx, account_id: str | None) -> str | None:
    """CRM owner, then open-deal owner, then the same stable territory match Rep Brief uses."""
    if not account_id:
        return None
    a = ctx.store.account(account_id) or {}
    if a.get("owner"):
        return a["owner"]
    deals = [d for d in ctx.store.select("deals", "account_id=?", (account_id,)) if pipeline.is_open(d) and d.get("owner")]
    if deals:
        return deals[0]["owner"]
    owners = profile.company(ctx).get("team", {}).get("owners", [])
    if not owners or not a:
        return None
    country = (a.get("country") or "").upper()
    seg = "enterprise" if (a.get("employees") or 0) >= 1000 else "mid_market"
    pool = [o for o in owners if country in [c.upper() for c in o.get("regions", [])] and seg in o.get("segments", [seg])] \
        or [o for o in owners if seg in o.get("segments", [seg])] or owners
    return pool[int(hashlib.sha1(a["id"].encode()).hexdigest(), 16) % len(pool)]["name"]


VERB = {"comment": "commented on", "share": "shared", "follow": "followed", "reaction": "reacted to", "view": "watched"}


def alert_lines(ctx, results: list[dict]) -> dict[str, list[str]]:
    by_owner: dict[str, list[str]] = {}
    for r in results:
        if not r["account_id"] or r["type"] == "view" and not r.get("signal_id"):
            continue
        owner = owner_for(ctx, r["account_id"]) or "Unassigned"
        acct = ctx.store.account(r["account_id"]) or {}
        who = r["name"] or "Someone"
        role = f" ({r['title']})" if r["title"] else ""
        what = f"{VERB[r['type']]} \"{(r['post_title'] or 'a post')[:60]}\""
        extra = []
        if r["intent_terms"]:
            extra.append("asked a buying question")
        if r["competitors"]:
            extra.append("mentioned " + ", ".join(r["competitors"]))
        if r["repeat"]:
            extra.append(f"{r['repeat'] + 1} engagements in {ctx.manifest.config.get('repeat_window_days', 30)} days")
        if not r["contact_id"]:
            extra.append("not in CRM yet" + (f", add request #{r['proposal']}" if r.get("proposal") else ""))
        else:
            sup = suppression.reason(ctx.store, contact=ctx.store.get("contacts", r["contact_id"]))
            if sup:  # engagement still counts as an account signal, but the person is not to be contacted
                extra.append(f"DO NOT CONTACT this person ({sup})")
        line = f"- *{who}*{role} at {acct.get('name', r['account_id'])} {what}" + (f" | {'; '.join(extra)}" if extra else "")
        by_owner.setdefault(owner, []).append(line)
    return by_owner


def format_alerts(ctx, results: list[dict]) -> list[str]:
    out = []
    for owner, lines in sorted(alert_lines(ctx, results).items()):
        out.append(f"*Social Signals for {owner}* ({len(lines)})\n" + "\n".join(lines[:15]) +
                   ("\n_Timing only: do not mention reactions, follows or views to the prospect._"))
    return out


# ---------- reporting ----------
def engagements(ctx, days: int = 30, now: datetime | None = None, account_id: str | None = None) -> list[dict]:
    since = (_now(now) - timedelta(days=days)).isoformat()
    rows = ctx.store.insights("social_engagement", since_iso=since, account_id=account_id)
    return [{**(r.get("value") or {}), "observed_at": r["observed_at"]} for r in rows]


def latest_tier(ctx, account_id: str | None) -> str:
    if not account_id:
        return "unknown"
    r = ctx.store.one("SELECT tier FROM scores WHERE account_id=? ORDER BY id DESC LIMIT 1", (account_id,))
    return (r or {}).get("tier") or "unscored"


def top_engagers(ctx, days: int = 30, limit: int = 20, now: datetime | None = None) -> list[dict]:
    people: dict[str, dict] = {}
    for e in engagements(ctx, days, now):
        p = people.setdefault(e["person_key"], {"name": e.get("name"), "title": e.get("title"), "company": e.get("company"),
                                                "account_id": e.get("account_id"), "contact_id": e.get("contact_id"),
                                                "points": 0.0, "engagements": 0, "types": {}, "last": e["observed_at"]})
        p["points"] = round(p["points"] + float(e.get("points", 0)), 2)
        p["engagements"] += 1
        p["types"][e["type"]] = p["types"].get(e["type"], 0) + 1
        p["last"] = max(p["last"], e["observed_at"])
    rows = sorted(people.values(), key=lambda p: -p["points"])
    for p in rows:
        p["account_tier"] = latest_tier(ctx, p["account_id"])
        p["owner"] = owner_for(ctx, p["account_id"])
    return rows[:limit]


def creator_report(ctx, days: int = 7, now: datetime | None = None) -> dict:
    by_creator: dict[str, dict] = {}
    posts: dict[str, dict] = {}
    for e in engagements(ctx, days, now):
        tier = latest_tier(ctx, e.get("account_id"))
        icp_hit = tier in ("A", "B", "C") or bool(e.get("account_id") and owner_for(ctx, e["account_id"]))
        c = by_creator.setdefault(e.get("author") or "company", {"engagements": 0, "from_known_accounts": 0,
                                                               "from_icp_accounts": 0, "by_tier": {}, "people": set()})
        c["engagements"] += 1
        c["people"].add(e["person_key"])
        if e.get("account_id"):
            c["from_known_accounts"] += 1
        if icp_hit:
            c["from_icp_accounts"] += 1
        c["by_tier"][tier] = c["by_tier"].get(tier, 0) + 1
        pk = e.get("post_url") or e.get("post_title") or "unknown post"
        p = posts.setdefault(pk, {"post": e.get("post_title") or pk, "author": e.get("author"), "engagements": 0,
                                  "icp_engagements": 0, "accounts": set()})
        p["engagements"] += 1
        if icp_hit:
            p["icp_engagements"] += 1
        if e.get("account_id"):
            p["accounts"].add(e["account_id"])
    creators = [{"creator": k, **{kk: (len(vv) if isinstance(vv, set) else vv) for kk, vv in v.items()}}
                for k, v in by_creator.items()]
    creators.sort(key=lambda c: (-c["from_icp_accounts"], -c["engagements"]))
    top_posts = sorted(({**p, "accounts": len(p["accounts"])} for p in posts.values()),
                       key=lambda p: (-p["icp_engagements"], -p["engagements"]))[:5]
    return {"days": days, "creators": creators, "top_posts": top_posts}


def format_creator_report(rep: dict) -> str:
    if not rep["creators"]:
        return f"*Social Signals: creator report, last {rep['days']} days*\nNo engagement recorded."
    lines = [f"*Social Signals: creator report, last {rep['days']} days*"]
    for c in rep["creators"]:
        tiers = ", ".join(f"{t} {n}" for t, n in sorted(c["by_tier"].items()))
        lines.append(f"- {c['creator']}: {c['engagements']} engagements from {c['people']} people | "
                     f"{c['from_icp_accounts']} from target accounts | tiers: {tiers}")
    if rep["top_posts"]:
        lines.append("Top posts by target-account engagement:")
        for p in rep["top_posts"]:
            lines.append(f"  - {p['post'][:70]} ({p['author']}): {p['icp_engagements']} target / {p['engagements']} total, "
                         f"{p['accounts']} accounts")
    return "\n".join(lines)


def load_file(path) -> list[dict]:
    import csv
    from pathlib import Path
    p = Path(path)
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else data.get("rows", [])
    with p.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
