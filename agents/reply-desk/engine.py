"""Reply Desk engine: rule-based classification and per-class actions. The model only drafts,
and only refines a low-confidence class. It can never turn an opt-out or a bounce into anything else."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from gtm_core import pipeline, profile, suppression, writer
from gtm_core.store import now_iso

SCHEMA = """CREATE TABLE IF NOT EXISTS replies (
  id TEXT PRIMARY KEY, from_email TEXT, from_name TEXT, to_email TEXT, subject TEXT, body TEXT,
  clean_body TEXT, received_at TEXT, campaign TEXT, thread_id TEXT, contact_email TEXT, contact_id TEXT,
  account_id TEXT, owner TEXT, class TEXT, category TEXT, confidence DOUBLE PRECISION, reason TEXT, follow_up_at TEXT,
  referral_name TEXT, referral_email TEXT, status TEXT, actions TEXT, handled_at TEXT, created_at TEXT)"""
COLS = ["id", "from_email", "from_name", "to_email", "subject", "body", "clean_body", "received_at", "campaign",
        "thread_id", "contact_email", "contact_id", "account_id", "owner", "class", "category", "confidence", "reason",
        "follow_up_at", "referral_name", "referral_email", "status", "actions", "handled_at", "created_at"]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
WEEKDAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}


def ensure_schema(ctx) -> None:
    if not getattr(ctx.store, "_reply_desk_schema", False):
        ctx.store.execute(SCHEMA)
        ctx.store._reply_desk_schema = True


def _now(now):
    return now or datetime.now(timezone.utc)


def reply_id(r: dict) -> str:
    """Stable id so a re-dropped or re-posted reply is never handled twice.
    Message-ID when present; else thread id plus body; else sender, body and the UTC receive time
    (sender and body only when the row has no timestamp)."""
    mid = (r.get("message_id") or r.get("Message-ID") or r.get("message-id") or "").strip().strip("<>")
    body = re.sub(r"\s+", " ", (r.get("body") or r.get("subject") or "")).strip().lower()[:2000]
    bh = hashlib.sha1(body.encode()).hexdigest()[:16]
    sender = (r.get("from_email") or "").strip().lower()
    if mid:
        key = f"mid|{mid.lower()}"
    elif (r.get("thread_id") or "").strip():
        key = f"thread|{r['thread_id'].strip()}|{sender}|{bh}"
    else:
        d = pipeline.parse_dt(r.get("received_at"))
        ts = d.astimezone(timezone.utc).replace(microsecond=0).isoformat() if d else ""
        key = f"msg|{sender}|{bh}|{ts}"
    return "rep-" + hashlib.sha1(key.encode()).hexdigest()[:12]


def save(ctx, row: dict) -> bool:
    """Insert a reply. False if it is already stored."""
    ensure_schema(ctx)
    if ctx.store.one("SELECT id FROM replies WHERE id=?", (row["id"],)):
        return False
    vals = [row.get(c) for c in COLS]
    ctx.store.execute(f"INSERT INTO replies ({', '.join(COLS)}) VALUES ({','.join('?' * len(COLS))})", vals)
    return True


def update(ctx, rid: str, **fields) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    ctx.store.execute(f"UPDATE replies SET {sets} WHERE id=?", (*fields.values(), rid))


def get(ctx, rid: str) -> dict | None:
    ensure_schema(ctx)
    r = ctx.store.one("SELECT * FROM replies WHERE id=?", (rid,))
    if r and r.get("actions"):
        r["actions"] = json.loads(r["actions"])
    return r


def select(ctx, where: str = "1=1", params=(), order: str = "received_at DESC") -> list[dict]:
    ensure_schema(ctx)
    rows = ctx.store.query(f"SELECT * FROM replies WHERE {where} ORDER BY {order}", params)
    for r in rows:
        r["actions"] = json.loads(r["actions"]) if r.get("actions") else []
    return rows


# ---------------------------------------------------------------- cleaning
QUOTE_MARKERS = [r"^on .{3,120}wrote:\s*$", r"^-{2,}\s*original message\s*-{2,}", r"^from:\s.+", r"^sent:\s.+",
                 r"^_{5,}", r"^>", r"^begin forwarded message"]
SIGNOFF = re.compile(r"^(thanks|thank you|best|regards|best regards|kind regards|cheers|sincerely|warmly)[,.!]?\s*$", re.I)


def strip_quoted(body: str) -> str:
    """Remove only quoted history and forwarded parts. Sign-offs and signatures stay (opt-outs live there too)."""
    out = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        low = line.strip().lower()
        if any(re.match(p, low) for p in QUOTE_MARKERS):
            break
        out.append(line)
    return "\n".join(out).strip()


def clean(body: str) -> str:
    """Strip quoted history, mobile footers and the signature. Deterministic."""
    lines, out = (body or "").replace("\r\n", "\n").split("\n"), []
    for line in lines:
        s = line.strip()
        low = s.lower()
        if any(re.match(p, low) for p in QUOTE_MARKERS) or low.startswith("sent from my") or s == "--":
            break
        if SIGNOFF.match(s) and out:
            break
        out.append(line)
    return "\n".join(out).strip()


# ---------------------------------------------------------------- dates
def _next_occurrence(month: int, day: int, now: datetime) -> datetime:
    year = now.year
    d = datetime(year, month, min(day, calendar.monthrange(year, month)[1]), tzinfo=timezone.utc)
    if d.date() < now.date():
        d = datetime(year + 1, month, min(day, calendar.monthrange(year + 1, month)[1]), tzinfo=timezone.utc)
    return d


def parse_return_date(text: str, now: datetime) -> datetime | None:
    """Return date in an out-of-office note: 'back on Monday, November 3', 'returning 11/3', 'until Nov 3rd'."""
    t = text.lower()
    m = re.search(r"(?:back|return(?:ing)?|until|through|in the office)\D{0,25}?"
                  r"(?:(?:mon|tues|wed|thurs|fri|sat|sun)[a-z]*,?\s+)?"
                  r"([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?", t)
    if m and m.group(1) in MONTHS:
        return _next_occurrence(MONTHS[m.group(1)], int(m.group(2)), now)
    m = re.search(r"(?:back|return(?:ing)?|until|through)\D{0,25}?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if m:
        mo, dy = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            if m.group(3):
                y = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
                return datetime(y, mo, min(dy, calendar.monthrange(y, mo)[1]), tzinfo=timezone.utc)
            return _next_occurrence(mo, dy, now)
    m = re.search(r"(?:back|return(?:ing)?)\D{0,15}?(?:on\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", t)
    if m:
        ahead = (WEEKDAYS[m.group(1)] - now.weekday()) % 7 or 7
        return (now + timedelta(days=ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def parse_later_date(text: str, now: datetime, default_days: int = 90) -> tuple[datetime, str]:
    """When to follow up for a 'not now': next quarter, next year, in March, Q2, in 3 months."""
    t = text.lower()
    q_now = (now.month - 1) // 3
    if re.search(r"next quarter|next q\b", t):
        q = q_now + 1
        y = now.year + q // 4
        return datetime(y, (q % 4) * 3 + 1, 1, tzinfo=timezone.utc), "next quarter"
    m = re.search(r"\bq([1-4])\b", t)
    if m:
        q = int(m.group(1)) - 1
        y = now.year if q > q_now else now.year + 1
        return datetime(y, q * 3 + 1, 1, tzinfo=timezone.utc), f"Q{q + 1}"
    if re.search(r"next year|new year", t):
        return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc), "next year"
    if re.search(r"next month", t):
        y, mo = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        return datetime(y, mo, 1, tzinfo=timezone.utc), "next month"
    m = re.search(r"in\s+(\d{1,2}|a|one|two|three|six)\s+(week|month)s?", t)
    if m:
        n = {"a": 1, "one": 1, "two": 2, "three": 3, "six": 6}.get(m.group(1)) or int(m.group(1))
        days = n * (7 if m.group(2) == "week" else 30)
        return (now + timedelta(days=days)).replace(microsecond=0), f"in {n} {m.group(2)}(s)"
    for name, num in MONTHS.items():
        if len(name) > 3 and re.search(rf"\b(?:in|after|until|around)\s+(?:early\s+|late\s+|mid\s+)?{name}\b", t):
            return _next_occurrence(num, 1, now), name.title()
    return (now + timedelta(days=default_days)).replace(microsecond=0), f"default {default_days} days"


# ---------------------------------------------------------------- classification
BOUNCE_FROM = re.compile(r"mailer-daemon|postmaster|mail delivery|delivery subsystem", re.I)
BOUNCE = [r"delivery status notification", r"undeliverable", r"address not found", r"mailbox (?:unavailable|not found|full)",
          r"delivery (?:has )?failed", r"recipient address rejected", r"user unknown", r"\b55[0-4] [0-9.]+",
          r"message (?:could not|wasn'?t) (?:be )?delivered", r"no such user"]
UNSUB = [r"\bunsubscribe me\b", r"^\s*unsubscribe\.?\s*$", r"\bremove me\b", r"\btake me off\b", r"\bstop (?:emailing|contacting|sending)",
         r"\bdo not (?:contact|email|reach)", r"\bdon'?t (?:contact|email) me", r"\bopt(?:-| )?out\b", r"^\s*stop\.?\s*$",
         r"\bplease remove\b", r"\bdelete my (?:data|information|details)", r"\bremove (?:my|this) (?:email|address)",
         r"\bunder (?:gdpr|ccpa|casl)\b", r"\bcease (?:all )?(?:contact|communication)", r"\bnot to (?:contact|email) me",
         r"\bno more (?:e-?mails|messages|outreach)\b", r"\bremove (?:me |us )?from (?:your |the |this )?(?:list|mailing list|emails?)",
         r"\bstop (?:the )?e-?mails?\b", r"\bunsubscribe\b(?!\s*link)", r"\bdarme de baja\b", r"\bdarse de baja\b",
         r"\bd[ée]sabonner\b", r"\bd[ée]sinscri(?:re|vez)\b", r"\babmelden\b", r"\bkeine (?:weiteren )?e-?mails\b",
         r"\bcancelar (?:la )?suscripci[oó]n\b", r"\bdescadastr"]
UNSUB_FOOTER = re.compile(r"click (?:here )?to unsubscribe|to unsubscribe,? click|unsubscribe link|manage (?:your )?preferences", re.I)
OOO = [r"out of (?:the )?office", r"\bon (?:vacation|holiday|leave|pto|parental leave|maternity leave|paternity leave)",
       r"away from (?:my )?(?:desk|email|the office)", r"automatic reply", r"auto-?reply", r"limited (?:access to )?email",
       r"currently (?:traveling|travelling|away)", r"i am (?:out|away) (?:until|through)"]
REFERRAL = [r"not the right (?:person|contact)", r"wrong person", r"no longer (?:with|at|work)", r"(?:has )?left the company",
            r"you (?:should|may want to|might want to) (?:talk|speak|reach out|connect)", r"(?:the )?(?:best|right) person (?:is|would be|to talk)",
            r"i'?(?:ve|m) (?:cc'?d|copied|copying|looping in|cc'?ing)", r"(?:please )?(?:contact|try|reach out to|email) (?:my colleague|[A-Z][a-z]+)",
            r"handles? (?:this|that|these)", r"forwarded (?:this|your (?:note|email)) to"]
LATER = [r"\bnot (?:right )?now\b", r"next (?:quarter|year|month)", r"\bq[1-4]\b", r"(?:circle|check|reach|come) back (?:in|after|next)",
         r"revisit (?:in|after|next|this)", r"later (?:this|in the) year", r"\bin (?:\d{1,2}|a|two|three|six) (?:weeks?|months?)",
         r"budget (?:freeze|cycle|is set)", r"timing (?:isn'?t|is not) right", r"\bafter (?:the new year|q[1-4]|our)",
         r"\b(?:in|after|until) (?:early |late |mid )?(?:january|february|march|april|may|june|july|august|september|october|november|december)\b"]
NEG = r"(?<!not )(?<!n't )(?<!no )"
POSITIVE = [r"\blet'?s (?:talk|chat|connect|set (?:it|something|a time) up|do it|find (?:a )?time|meet)",
            r"\b(?:happy|glad|open|keen) to (?:chat|talk|connect|meet|learn|hear|take a look|see)",
            r"\bsend (?:me |us |over )*(?:a (?:couple|few) of |a few |some |two |2 |a couple )?(?:times|slots|options|availability|an invite|a calendar)",
            r"\bwhat (?:times|does your calendar)",
            r"\bbook (?:a|some) time", r"\bsounds (?:good|interesting|great)", NEG + r"\binterested\b", r"\btell me more\b",
            r"\bworks for me\b", r"\bfree (?:on|at|next)\b", r"\bhow about (?:mon|tue|wed|thu|fri)", r"\bset up (?:a|some) time",
            r"^\s*(?:yes|sure|absolutely|definitely)\b",
            r"^\s*(?:hi|hey|hello|thanks)[^\n,.!]{0,30}[,.!]\s*(?:yes|sure|absolutely|definitely)\b", r"\b(?:this is|that'?s) timely\b", r"\bi'?d like to (?:see|learn|talk)", r"\bgrab (?:a|some) time"]
MEETING = [r"\b(?:monday|tuesday|wednesday|thursday|friday)\b.*\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
           r"\bsent (?:you )?an invite\b", r"\bbooked\b"]
OBJECTIONS = {
    "competitor": [r"already (?:use|using|have|work with|partnered)", r"happy with (?:our|the|what)", r"\bwe use\b",
                   r"signed with", r"under contract", r"locked in", r"went with (?:another|a different)"],
    "price": [r"too expensive", r"\bno budget\b", r"budget (?:is )?(?:tight|gone|spent)", r"\bcost(?:s)? too\b", r"can'?t afford",
              r"cheaper", r"pricing is"],
    "timing": [r"bad timing", r"too busy", r"swamped", r"not a priority", r"bandwidth", r"other priorities"],
    "no_need": [r"not interested", r"\bno need\b", r"don'?t need", r"not a (?:fit|match)", r"not relevant", r"^\s*no,? thanks?\b",
                r"\bno thank you\b", r"we'?re (?:good|all set|set)", r"\bpass\b", r"doesn'?t apply"],
}
QUESTION = re.compile(r"\?|^(?:how|what|does|do|can|is|are|who|which|where|why|when)\b", re.I | re.M)
CONF = {"bounce": 0.97, "unsubscribe": 0.97, "out_of_office": 0.92, "referral": 0.85, "not_now": 0.82, "positive": 0.85,
        "objection": 0.8, "question": 0.55, "neutral": 0.4}


def _hit(pats, text, flags=re.I | re.M):
    for p in pats:
        m = re.search(p, text, flags)
        if m:
            return m.group(0)
    return None


def _referral(text: str, sender: str) -> tuple[str | None, str | None]:
    emails = [e for e in EMAIL_RE.findall(text) if e.lower() != (sender or "").lower()]
    name = None
    m = re.search(r"(?:talk to|speak (?:with|to)|contact|reach out to|try|email|connect with|cc'?d|copied|looping in|"
                  r"person is|person would be|handles this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text)
    if m and m.group(1).split()[0].lower() not in {"me", "our", "my", "the", "him", "her", "them", "us"}:
        name = m.group(1)
    return name, (emails[0].lower() if emails else None)


def classify(text: str, subject: str = "", from_email: str = "", now: datetime | None = None,
             not_now_default_days: int = 90, ooo_default_days: int = 7) -> dict:
    """Rule-based class with the rule that fired. Raw text is cleaned first."""
    now = _now(now)
    raw = text or ""
    body = clean(raw)
    full = f"{subject}\n{body}"
    out = {"class": "neutral", "category": None, "confidence": CONF["neutral"], "reason": "no rule matched",
           "follow_up_at": None, "referral_name": None, "referral_email": None, "clean_body": body}

    def done(cls, reason, **kw):
        out.update({"class": cls, "confidence": CONF[cls], "reason": reason, **kw})
        return out

    if BOUNCE_FROM.search(from_email or "") or _hit(BOUNCE, f"{subject}\n{raw}"):  # raw on purpose: DSNs quote the original
        found = [e.lower() for e in EMAIL_RE.findall(raw) if not BOUNCE_FROM.search(e)]
        return done("bounce", "delivery failure", bounced_email=found[0] if found else None)
    # Opt-outs are checked on everything the person wrote (quoted history removed, nothing else cut),
    # so a request after a sign-off line still counts. Footer unsubscribe links do not.
    unsub_text = UNSUB_FOOTER.sub(" ", f"{subject}\n{strip_quoted(raw)}")
    hit = _hit(UNSUB, unsub_text)
    if hit:
        return done("unsubscribe", f"opt-out request: '{hit.strip()}'")
    hit = _hit(OOO, f"{subject}\n{raw}")
    if hit:
        ret = parse_return_date(raw, now)
        until = ret or (now + timedelta(days=ooo_default_days)).replace(microsecond=0)
        return done("out_of_office", f"auto-reply: '{hit}'" + ("" if ret else f" (no return date, assume {ooo_default_days} days)"),
                    follow_up_at=until.isoformat())
    hit = _hit(REFERRAL, body)
    if hit:
        name, email = _referral(body, from_email)
        cat = "left_company" if re.search(r"no longer|left the company", body, re.I) else "referral"
        return done("referral", f"points elsewhere: '{hit}'", category=cat, referral_name=name, referral_email=email)
    pos = _hit(POSITIVE, body)
    later = _hit(LATER, body)
    if later and not (pos and not re.search(r"next|later|after|q[1-4]|in \w+ (?:weeks?|months?)", later, re.I)):
        when, label = parse_later_date(body, now, not_now_default_days)
        return done("not_now", f"later: '{later}' -> {label}", follow_up_at=when.isoformat())
    for cat, pats in OBJECTIONS.items():
        h = _hit(pats, body)
        if h and not (pos and cat in ("competitor", "timing")):
            return done("objection", f"{cat}: '{h}'", category=cat)
    if pos:
        return done("positive", f"interest: '{pos.strip()}'", category="meeting" if _hit(MEETING, body) else "interest")
    if QUESTION.search(body):
        return done("question", "asks a question")
    return out


def refine_with_model(ctx, r: dict, text: str) -> dict:
    """Only for low-confidence classes. A model can add an opt-out (stopping is safe) but never remove one."""
    if r["class"] in ("bounce", "unsubscribe") or r["confidence"] >= float(ctx.manifest.config.get("low_confidence", 0.6)):
        return r
    got = writer.extract(ctx, "Classify this sales email reply.", text,
                         '{"class": "positive|objection|not_now|question|referral|unsubscribe|neutral", '
                         '"category": "price|competitor|timing|no_need|null", "evidence": "quote"}', max_tokens=300)
    if not isinstance(got, dict) or got.get("class") not in CONF or got.get("class") in ("bounce", "out_of_office"):
        return r
    r = {**r, "class": got["class"], "category": got.get("category") if got.get("category") != "null" else None,
         "confidence": 0.7, "reason": f"model: {str(got.get('evidence') or '')[:120]}"}
    if r["class"] == "not_now":
        when, _ = parse_later_date(text, datetime.now(timezone.utc))
        r["follow_up_at"] = when.isoformat()
    return r


# ---------------------------------------------------------------- owner and contact
def resolve(ctx, email: str) -> dict:
    email = (email or "").lower()
    contact = ctx.store.contact_by_email(email) if email else None
    domain = email.split("@", 1)[1] if "@" in email else ""
    acct = None
    if contact and contact.get("account_id"):
        acct = ctx.store.account(contact["account_id"])
    if not acct and domain:
        acct = ctx.store.account_by_domain(domain)
    owner, how = None, None
    if contact and contact.get("owner"):
        owner, how = contact["owner"], "contact owner"
    elif acct and acct.get("owner"):
        owner, how = acct["owner"], "account owner"
    if not owner and acct:
        deals = [d for d in ctx.store.select("deals", "account_id=?", (acct["id"],)) if pipeline.is_open(d)]
        if deals and deals[0].get("owner"):
            owner, how = deals[0]["owner"], "open deal owner"
    if not owner:
        for d in ctx.store.drafts(limit=500):
            if (contact and d.get("contact_id") == contact["id"]) or (acct and d.get("account_id") == acct["id"]):
                if (d.get("meta") or {}).get("owner"):
                    owner, how = d["meta"]["owner"], f"{d['agent']} draft owner"
                    break
    if not owner and email:
        lead = next(iter(ctx.store.select("leads", "LOWER(email)=?", (email,))), None)
        if lead and lead.get("owner"):
            owner, how = lead["owner"], "lead owner"
    if not owner:
        owner = ctx.manifest.config.get("default_owner") or next(
            (o["name"] for o in profile.company(ctx).get("team", {}).get("owners", [])), None)
        how = "default owner"
    return {"contact": contact, "account": acct, "owner": owner, "owner_source": how}


def add_business_hours(start: datetime, hours: float, tz: str = "UTC", window=(9, 17)) -> datetime:
    from zoneinfo import ZoneInfo
    z = ZoneInfo(tz)
    t = start.astimezone(z)
    remaining = timedelta(hours=hours)
    open_h, close_h = window
    for _ in range(30 * 24):
        if t.weekday() >= 5 or t.hour >= close_h:
            t = (t + timedelta(days=1)).replace(hour=open_h, minute=0, second=0, microsecond=0)
            continue
        if t.hour < open_h:
            t = t.replace(hour=open_h, minute=0, second=0, microsecond=0)
        end_of_day = t.replace(hour=close_h, minute=0, second=0, microsecond=0)
        if t + remaining <= end_of_day:
            return (t + remaining).astimezone(timezone.utc)
        remaining -= end_of_day - t
        t = (t + timedelta(days=1)).replace(hour=open_h, minute=0, second=0, microsecond=0)
    return (start + timedelta(hours=hours)).astimezone(timezone.utc)


# ---------------------------------------------------------------- drafting
def _first(name: str | None, email: str) -> str:
    if name and name.strip():
        return name.strip().split()[0]
    local = (email or "").split("@")[0].split(".")[0]
    return local.capitalize() if local.isalpha() else "there"


def _vp(ctx) -> dict:
    vps = profile.company(ctx).get("value_props", [])
    return vps[0] if vps else {}


def _lc(s: str) -> str:
    s = (s or "").strip().rstrip(".")
    return s[:1].lower() + s[1:] if s else s


def templates(ctx, r: dict, kind: str, extra: dict) -> str:
    snd = profile.sender(ctx)
    first = _first(r.get("from_name"), r.get("from_email"))
    subj = r.get("subject") or "our conversation"
    subj = subj if subj.lower().startswith("re:") else f"Re: {subj}"
    link = snd.get("calendar_link")
    sign = snd.get("name", "")
    vp = _vp(ctx)
    if kind == "positive":
        tail = f" Or pick a slot here: {link}" if link else ""
        return (f"Subject: {subj}\nHi {first},\n\nThanks for getting back to me. Would Tuesday or Wednesday next week "
                f"work for 20 minutes?{tail}\n\n{sign}")
    if kind == "objection":
        cat = extra.get("category")
        if cat == "price":
            body = (f"Fair point on cost. Most teams weigh it against the time spent on one problem: {_lc(vp.get('pain'))}. "
                    "Worth 15 minutes to see if the math works for you?")
        elif cat == "competitor":
            comp = extra.get("competitor") or "your current tool"
            body = (f"Makes sense if {comp} is working. Teams often keep it and add us for one thing: "
                    f"{_lc(vp.get('outcome'))}. Open to a short side-by-side next week?")
        elif cat == "timing":
            body = "Understood, I will leave it here for now. Is it all right if I check back next quarter?"
        else:
            tail = f" If it ever moves up your list, my calendar is here: {link}" if link else ""
            body = f"Thanks for the straight answer. I will close this out on my side.{tail}"
        return f"Subject: {subj}\nHi {first},\n\n{body}\n\n{sign}"
    if kind == "referral":
        ref_first = _first(extra.get("referral_name"), extra.get("referral_email") or "")
        by = r.get("from_name") or "Your colleague"
        one = profile.company(ctx).get("one_liner", "")
        return (f"Subject: {by.split()[0]} suggested I get in touch\nHi {ref_first},\n\n{by} mentioned you are the right "
                f"person for this. {one}\n\nWorth 15 minutes next week?\n\n{sign}")
    if kind == "question":
        return (f"Subject: {subj}\nHi {first},\n\nGood question. {extra.get('answer', '').rstrip('.')}.\n\n"
                f"Happy to walk through it. Does Tuesday or Wednesday work for 15 minutes?\n\n{sign}")
    return ""


def answer_from_company(ctx, question: str) -> str | None:
    """Only answer from facts in company.yaml. Needs two meaningful words in common, else no answer."""
    comp = profile.company(ctx)
    words = {w for w in re.findall(r"[a-z]{4,}", question.lower())} - {"what", "does", "your", "with", "have", "this",
                                                                         "that", "how", "about", "would", "could", "they"}
    facts = [comp.get("one_liner", "")] + [v.get("outcome", "") for v in comp.get("value_props", [])] + \
            [f"Compared with {c['name']}: {c.get('positioning', '')}" for c in comp.get("competitors", []) if isinstance(c, dict)]
    best, score = None, 0
    for f in facts:
        overlap = len(words & set(re.findall(r"[a-z]{4,}", f.lower())))
        if overlap > score:
            best, score = f, overlap
    return best if score >= 2 else None


def draft(ctx, r: dict, kind: str, extra: dict):
    comp = profile.company(ctx)
    facts = {"their_reply": r.get("clean_body"), "their_name": r.get("from_name"), "class": r.get("class"),
             "category": extra.get("category"), "sender": profile.sender(ctx), "our_company": comp.get("company"),
             "value_props": comp.get("value_props", []), "proof_points": comp.get("proof_points", []), **extra}
    instr = {"positive": "Reply to an interested buyer. Thank them in one line, propose two times or the calendar link. One ask.",
             "objection": "Answer the objection in two sentences using only the facts, then one soft ask. No pressure.",
             "referral": "Short intro email to the person they referred us to. Name who referred us. One ask.",
             "question": "Answer their question using only the given answer fact, then one ask for a short call."}[kind]
    return writer.write(ctx, f"reply email ({kind})", facts, instr, templates(ctx, r, kind, extra),
                        max_words=int(ctx.manifest.config.get("max_words", 110)))


# ---------------------------------------------------------------- handling
def _competitor_in(ctx, text: str) -> str | None:
    for c in profile.competitors(ctx):
        if re.search(r"(?<![a-z])" + re.escape(c.lower()) + r"(?![a-z])", text.lower()):
            return c
    return None


def handle(ctx, rid: str, now: datetime | None = None) -> dict:
    """Classify and act on one reply. Claimed atomically: a second call does nothing."""
    ensure_schema(ctx)
    now = _now(now)
    if not ctx.store.execute("UPDATE replies SET status=? WHERE id=? AND status=?", ("handling", rid, "new")):
        r = get(ctx, rid) or {}
        return {"reply_id": rid, "skipped": f"already handled (status {r.get('status')})", "class": r.get("class")}
    r = get(ctx, rid)
    cfg = ctx.manifest.config
    c = classify(r.get("body") or "", r.get("subject") or "", r.get("from_email") or "", now,
                 int(cfg.get("not_now_default_days", 90)), int(cfg.get("ooo_default_days", 7)))
    c = refine_with_model(ctx, c, c["clean_body"] or r.get("body") or "")
    who_email = (c.get("bounced_email") if c["class"] == "bounce" else None) or r.get("from_email")
    res = resolve(ctx, who_email)
    contact, acct, owner = res["contact"], res["account"], res["owner"]
    r.update({k: c.get(k) for k in ("class", "category", "confidence", "reason", "follow_up_at", "referral_name",
                                     "referral_email", "clean_body")})
    acts, appr = [], []
    crm = {"account_crm_id": (acct or {}).get("crm_id"), "owner": owner}
    cid = (contact or {}).get("id") or (who_email or "").lower()
    name = r.get("from_name") or (contact or {}).get("name") or who_email
    stamp = now.replace(microsecond=0).isoformat()

    def local_contact(**fields):
        base = {"id": cid, "email": (who_email or "").lower(), "account_id": (acct or {}).get("id")}
        if contact:
            base = {"id": contact["id"]}
        ctx.store.upsert("contacts", {**base, **fields})
        acts.append(f"local: {', '.join(fields)}")

    def ask(action, payload, summary=""):
        appr.append(ctx.request_approval(action, payload, summary=summary))
        acts.append(action)

    def stop(reason):
        # Stopping only reduces contact, so it runs at once (still logged in the approval queue).
        appr.append(ctx.request_approval("sequence_stop", {"email": (who_email or "").lower(), "reason": reason,
                                                           "meta": {"reply_id": rid}}, auto_safe=True))
        acts.append("sequence_stop")

    def queue_draft(kind, extra, subject_line, due, to=None):
        to = (to or who_email or "").lower()
        if suppression.is_suppressed(ctx.store, to):
            acts.append(f"no draft: {to} must not be contacted")
            return None
        d = draft(ctx, r, kind, extra)
        did = ctx.store.add_draft(ctx.manifest.id, f"reply_{kind}", d.body, subject=d.subject, gate_score=d.score,
                                  gate_passed=d.passed, source=d.source, account_id=(acct or {}).get("id"),
                                  contact_id=cid, meta={"reply_id": rid, "owner": owner, "to": to})
        if d.passed:
            rid2 = ctx.request_approval("crm_task", {"subject": subject_line, "due_at": due, **crm,
                                                     "body": f"Draft #{did} (gate {d.score}/40)\n\nSubject: {d.subject}\n\n{d.body}"},
                                        summary=f"{owner}: {subject_line} (draft #{did}, gate {d.score}/40)")
            appr.append(rid2)
            acts.append("crm_task (send drafted reply)")
            ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", rid2, did))
        else:
            ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("needs_rewrite", did))
            ask("crm_task", {"subject": f"Write reply to {name} (draft failed copy check)", "due_at": due, **crm,
                             "body": f"{r['class']}: {r['clean_body'][:600]}"})
        return {**d.as_dict(), "draft_id": did}

    out_draft = None
    cls = c["class"]
    sla_due = add_business_hours(now, float(cfg.get("positive_sla_hours", 2)), cfg.get("timezone", "UTC"),
                                 tuple(cfg.get("business_hours", [9, 17]))).replace(microsecond=0).isoformat()
    if cls == "unsubscribe":
        local_contact(do_not_contact=True, do_not_contact_at=stamp, do_not_contact_reason=c["reason"])
        sup = suppression.suppress(ctx.store, who_email, f"opt-out: {c['reason']}"[:200], by=ctx.manifest.id)
        if sup.get("rejected_approvals"):
            acts.append(f"rejected pending sends {sup['rejected_approvals']}")
        stop("opt-out")
        if (contact or {}).get("crm_id"):
            ask("contact_update", {"crm_id": contact["crm_id"],
                                   "fields": {cfg.get("crm_fields", {}).get("opt_out", "gtm_do_not_contact"): True}})
        if acct:
            ctx.store.add_outcome(acct["id"], "reply_negative", source="reply-desk", observed_at=stamp)
    elif cls == "bounce":
        local_contact(email_invalid=True, email_invalid_at=stamp)
        sup = suppression.suppress(ctx.store, who_email, "bounce", by=ctx.manifest.id)
        if sup.get("rejected_approvals"):
            acts.append(f"rejected pending sends {sup['rejected_approvals']}")
        stop("bounce")
        ask("crm_task", {"subject": f"Fix bounced email for {name}", "body": c["reason"], "due_at": sla_due, **crm})
    elif cls == "out_of_office":
        local_contact(ooo_until=c["follow_up_at"])
    elif cls == "referral":
        stop("referral" if c["category"] == "referral" else "left company")
        if c["category"] == "left_company":
            local_contact(left_company=True)
        if c["referral_email"]:
            ref_dom = c["referral_email"].split("@", 1)[1]
            ref_acct = ctx.store.account_by_domain(ref_dom) or acct
            if not ctx.store.contact_by_email(c["referral_email"]):
                ctx.store.upsert("contacts", {"id": c["referral_email"], "email": c["referral_email"], "name": c["referral_name"],
                                              "account_id": (ref_acct or {}).get("id"), "referred_by": who_email})
                ask("crm_contact", {"fields": {"name": c["referral_name"], "email": c["referral_email"]},
                                    "account_crm_id": (ref_acct or {}).get("crm_id")})
            out_draft = queue_draft("referral", {"referral_name": c["referral_name"], "referral_email": c["referral_email"]},
                                    f"Send intro to {c['referral_name'] or c['referral_email']} (referred by {name})", sla_due,
                                    to=c["referral_email"])
        elif c["referral_name"]:
            ctx.handoffs.send("enrichment", "enrich_request", f"{c['referral_name']}@{(acct or {}).get('domain') or ''}",
                              {"name": c["referral_name"], "domain": (acct or {}).get("domain"), "account_id": (acct or {}).get("id"),
                               "fields": ["email", "phone", "title"], "reason": f"referred by {name}"})
            acts.append("handoff: enrich_request")
            ask("crm_task", {"subject": f"Find contact details for {c['referral_name']} (referred by {name})", "due_at": sla_due,
                             "body": r["clean_body"][:600], **crm})
        else:
            ask("crm_task", {"subject": f"Find the right person at {(acct or {}).get('name') or 'account'} (from {name})",
                             "due_at": sla_due, "body": r["clean_body"][:600], **crm})
    elif cls == "positive":
        stop("replied: interested")
        ask("crm_task", {"subject": f"Interested reply from {name}: respond by {sla_due[11:16]} UTC", "due_at": sla_due,
                         "body": r["clean_body"][:800], **crm},
            summary=f"{owner}: {name} replied interested")
        out_draft = queue_draft("positive", {"category": c["category"]}, f"Send reply to {name} (interested)", sla_due)
        try:
            ctx.slack.post(f":fire: *Reply Desk*: {name} ({(acct or {}).get('name') or who_email}) replied interested. "
                           f"Owner {owner}, respond by {sla_due[11:16]} UTC.\n> {r['clean_body'][:200]}")
        except Exception as e:
            ctx.audit.log("slack.error", error=str(e)[:200])
        if acct:
            ctx.store.add_outcome(acct["id"], "meeting" if c["category"] == "meeting" else "reply_positive",
                                  source="reply-desk", observed_at=stamp)
    elif cls == "objection":
        extra = {"category": c["category"], "competitor": _competitor_in(ctx, r["clean_body"])}
        out_draft = queue_draft("objection", extra, f"Answer {c['category']} objection from {name}", sla_due)
        if acct:
            ctx.store.add_outcome(acct["id"], "bad_fit" if c["category"] == "no_need" and re.search(
                r"not a (?:fit|match)|not relevant|doesn'?t apply", r["clean_body"], re.I) else "reply_negative",
                source="reply-desk", observed_at=stamp)
        if c["category"] in ("no_need",):
            stop("replied: not interested")
    elif cls == "not_now":
        stop("replied: not now")
        ask("crm_task", {"subject": f"Re-engage {name} ({c['reason'].split('-> ')[-1]})", "due_at": c["follow_up_at"][:10],
                         "body": r["clean_body"][:600], **crm})
    elif cls == "question":
        ans = answer_from_company(ctx, r["clean_body"])
        if ans:
            out_draft = queue_draft("question", {"answer": ans}, f"Answer question from {name}", sla_due)
        else:
            ask("crm_task", {"subject": f"Answer question from {name} (not covered by approved facts)", "due_at": sla_due,
                             "body": r["clean_body"][:800], **crm})
    status = "needs_review" if cls == "neutral" else "handled"
    ctx.store.add_insight(ctx.manifest.id, "reply", cls, {"category": c["category"], "owner": owner, "email": who_email,
                                                          "reply_id": rid, "follow_up_at": c["follow_up_at"]},
                          r["clean_body"][:500], stamp, account_id=(acct or {}).get("id"))
    update(ctx, rid, contact_email=(who_email or "").lower(), contact_id=cid, account_id=(acct or {}).get("id"), owner=owner,
           **{"class": cls}, category=c["category"], confidence=c["confidence"], reason=c["reason"],
           follow_up_at=c["follow_up_at"], referral_name=c["referral_name"], referral_email=c["referral_email"],
           clean_body=c["clean_body"], status=status, actions=json.dumps(acts), handled_at=stamp)
    return {"reply_id": rid, "from": who_email, "name": name, "account": (acct or {}).get("name"), "owner": owner,
            "owner_source": res["owner_source"], "class": cls, "category": c["category"], "confidence": c["confidence"],
            "reason": c["reason"], "follow_up_at": c["follow_up_at"], "actions": acts, "approvals": appr,
            "draft": out_draft, "status": status}


def ingest_row(ctx, r: dict, now: datetime | None = None) -> str | None:
    r = {k: (str(v) if v is not None and not isinstance(v, str) else v) for k, v in r.items()}
    row = {k: (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k in COLS}
    if not row.get("from_email") or not (row.get("body") or row.get("subject")):
        return None
    row["from_email"] = row["from_email"].lower()
    rid = row.get("id") or reply_id({**r, "from_email": row["from_email"]})  # before defaulting the timestamp
    d = pipeline.parse_dt(row.get("received_at"))
    row["received_at"] = (d.astimezone(timezone.utc) if d else _now(now)).replace(microsecond=0).isoformat()
    row["id"] = rid
    row.update({"status": "new", "created_at": now_iso()})
    return row["id"] if save(ctx, row) else None


ORDER = {"positive": 0, "referral": 1, "objection": 2, "question": 3, "not_now": 4, "neutral": 5, "unsubscribe": 6,
         "bounce": 7, "out_of_office": 8}


def digest(owner: str, rows: list[dict]) -> str:
    counts = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    head = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(counts.items(), key=lambda kv: ORDER.get(kv[0], 9)))
    lines = [f"*Reply Desk for {owner}: {len(rows)} replies today* ({head})"]
    for r in sorted(rows, key=lambda r: ORDER.get(r["class"], 9)):
        if r["class"] in ("bounce", "out_of_office", "unsubscribe"):
            continue
        what = {"positive": "answer today (draft queued)", "objection": f"{r.get('category')} objection: review the drafted answer",
                "referral": "intro or lookup queued", "question": "answer the question", "not_now": f"follow up {(r.get('follow_up_at') or '')[:10]}",
                "neutral": "read and decide"}.get(r["class"], "")
        lines.append(f"- {r.get('from_name') or r['from_email']} | {r['class'].replace('_', ' ')} | {what}")
    handled = sum(counts.get(k, 0) for k in ("bounce", "out_of_office", "unsubscribe"))
    if handled:
        lines.append(f"_Handled for you: {handled} (bounces, out of office, opt-outs)._")
    return "\n".join(lines)
