"""Daily Book: every rep gets a full, ranked list of people to work today, warm and cold, every business day.

The book is a quota, not a list. Each rep has `slots` (25 to 50) split by `warm_ratio`. Warm comes from the
CRM and engagement; cold comes from owned signals (Signal Sourcing, Signal Scout). When one pool runs short
the other backfills; when both run short the gap is reported, never padded with people below the bar.
Everything here is code: pools, order, conflicts and the split. No model call.

Warm pool, in priority order (config `warm_order`):
  engaged        human opens or clicks in the last 14 days, no reply, not with an AE yet
  quiet_deal     open deal past its stage's stale days: the deal's primary contact
  champion_moved a past champion who joined a new account (champion_joined signal)
  inbound        an inbound lead not yet worked after inbound_days
  event          attended an event, no meeting since
  social         engaged with company or influencer content (Social Signals)
  recycle        closed-lost more than recycle_days ago: buyers on that account
Cold pool: the rep's accounts ranked by Signal Scout, accounts on today's Signal Sourcing send list first,
with buyers picked by Rep Brief's rules. Accounts with no buyer on file can be filled from a hosted MCP
people search (config/mcp.yaml people_search) when `fill_contacts` is on.

Never in a book: opted out or bounced, touched in recent_touch_days, already in a live follow-up cadence or
tee-up, an open deal owned by someone else, an inbound thread in progress, an account below the ICP floor or
tier X, or more than max_per_account people from one account.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from gtm_core import pipeline, profile, suppression
from gtm_core.agents import Manifest, load_module
from gtm_core.scoring import icp_fit
from gtm_core.store import now_iso

SCHEMA = """CREATE TABLE IF NOT EXISTS daily_book (
  id TEXT PRIMARY KEY, book_date TEXT, owner TEXT, rank INTEGER, pool TEXT, source TEXT, reason TEXT,
  contact_id TEXT, email TEXT, name TEXT, title TEXT, account_id TEXT, company TEXT, why_now TEXT, action TEXT,
  status TEXT, approval_id INTEGER, created_at TEXT)"""
WARM_ORDER = ["engaged", "quiet_deal", "champion_moved", "inbound", "event", "social", "recycle"]


def ensure_schema(ctx) -> None:
    if not getattr(ctx.store, "_daily_book_schema", False):
        ctx.store.execute(SCHEMA)
        ctx.store._daily_book_schema = True


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _peer(ctx, agent_id: str):
    root = ctx.manifest.path(f"../{agent_id}")
    if not (root / "agent.yaml").exists():
        return None, None
    m = Manifest.load(root)
    return load_module(m, "engine"), type(ctx)(**{**ctx.__dict__, "manifest": m})


def owners(ctx) -> list[dict]:
    return profile.company(ctx).get("team", {}).get("owners", [])


def plan(ctx, owner: str) -> tuple[int, int]:
    """(slots, warm target) for a rep: their own `book` settings in company.yaml, else the agent's defaults.
    Slots are held to 25..50 unless `allow_small_books` (tests, pilots)."""
    o = next((x for x in owners(ctx) if x["name"] == owner), {})
    b = o.get("book") or {}
    slots = int(b.get("slots", cfg(ctx, "slots", 40)))
    if not cfg(ctx, "allow_small_books", False):
        slots = max(25, min(50, slots))
    ratio = float(b.get("warm_ratio", cfg(ctx, "warm_ratio", 0.5)))
    return slots, round(slots * max(0.0, min(1.0, ratio)))


# ---------- exclusions ----------
def _busy(ctx, email: str) -> str | None:
    """With an AE or in a live cadence already (Follow-Through)."""
    for sql, why in (("SELECT id FROM teeups WHERE email=? AND status='open'", "already teed up for an AE"),
                     ("SELECT id FROM cadence WHERE email=? AND status IN ('active','awaiting_ae')", "in a follow-up cadence")):
        try:
            if ctx.store.one(sql, (email,)):
                return why
        except Exception:  # Follow-Through not installed or never run
            pass
    return None


def blocked(ctx, rb, rb_ctx, acct: dict | None, contact: dict, owner: str, now: datetime,
            source: str = "") -> str | None:
    """Why this person cannot be in today's book, or None. Engaged contacts were emailed recently by design (the
    action is a call or LinkedIn), and inbound or event leads are the open thread themselves."""
    email = (contact.get("email") or "").lower()
    if not email:
        return "no email"
    row = ctx.store.get("contacts", contact["contact_id"]) if contact.get("contact_id") else None
    if suppression.is_suppressed(ctx.store, email, row):
        return "opted out, bounced or do-not-contact"
    busy = _busy(ctx, email)
    if busy:
        return busy
    if row and source != "engaged":
        t = rb.touched_recently(rb_ctx, row, (acct or {}).get("id"), now)
        if t:
            return t
    if acct:
        skip = ("account contacted recently",) + (("inbound lead in progress",) if source in ("inbound", "event") else ())
        why = [w for w in rb.conflicts(rb_ctx, acct, owner, None, now) if not w.startswith(skip)]
        if why:
            return why[0]
    return None


def _contact_dict(c: dict) -> dict:
    return {"contact_id": c.get("id"), "email": (c.get("email") or "").lower(), "name": c.get("name"),
            "title": c.get("title"), "account_id": c.get("account_id")}


# ---------- warm pool ----------
def warm_pool(ctx, rb, rb_ctx, owner: str, now: datetime) -> list[dict]:
    out = []
    since14 = _iso(now - timedelta(days=int(cfg(ctx, "engaged_days", 14))))
    mine = {a["id"]: a for a in rb.rep_accounts(rb_ctx, owner)}

    def add(pool: str, c: dict, reason: str, at: str | None = None):
        if c.get("account_id") in mine or pool in ("quiet_deal", "inbound", "event"):
            out.append({"pool": "warm", "source": pool, "reason": reason, "at": at or "", **_contact_dict(c)})

    # engaged: human opens or clicks, no reply
    rows = ctx.store.query("SELECT email, SUM(CASE WHEN event='click' THEN 1 ELSE 0 END) AS clicks, "
                           "SUM(CASE WHEN event='open' AND machine=0 THEN 1 ELSE 0 END) AS opens, MAX(occurred_at) AS last "
                           "FROM email_events WHERE occurred_at>=? GROUP BY email", (since14,))
    for r in rows:
        if not (r["opens"] or r["clicks"]):
            continue
        if ctx.store.one("SELECT id FROM email_events WHERE email=? AND event IN ('reply','reply_positive','reply_negative')",
                         (r["email"],)):
            continue
        c = ctx.store.contact_by_email(r["email"])
        if c:
            add("engaged", c, f"{r['opens']} opens, {r['clicks']} clicks in {cfg(ctx, 'engaged_days', 14)} days (timing only)",
                r["last"])
    # quiet deals
    stale = rb.cfg(rb_ctx, "idle_days", 14)
    sf, sf_ctx = _peer(ctx, "seller-follow-up")
    for d in ctx.store.select("deals", "owner=?", (owner,)):
        if not pipeline.is_open(d):
            continue
        idle = pipeline.days_since(d.get("last_activity_at") or d.get("stage_entered_at") or d.get("created_at"), now)
        if idle is None or idle < int(stale):
            continue
        pc = sf.primary_contact(sf_ctx, d) if sf else None
        if pc:
            out.append({"pool": "warm", "source": "quiet_deal", "reason": f"{d['name']} quiet {idle} days ({d.get('stage')})",
                        "at": d.get("last_activity_at") or "", **_contact_dict(pc)})
    # champions who moved
    for s in ctx.store.query("SELECT * FROM signals WHERE signal_type='champion_joined' AND observed_at>=?",
                             (_iso(now - timedelta(days=120)),)):
        p = json.loads(s.get("payload") or "{}")
        c = ctx.store.get("contacts", p["contact_id"]) if p.get("contact_id") else None
        if not c and p.get("person"):
            c = next(iter(ctx.store.select("contacts", "LOWER(name)=? AND account_id=?",
                                           ((p["person"] or "").lower(), s["account_id"]))), None)
        if c:
            add("champion_moved", c, f"past champion now at {(mine.get(s['account_id']) or {}).get('name') or s['account_id']}",
                s["observed_at"])
    # inbound not worked
    cutoff = _iso(now - timedelta(days=int(cfg(ctx, "inbound_days", 3))))
    for ld in ctx.store.select("leads", "owner=? AND status IN ('new','routed') AND received_at<=?", (owner, cutoff)):
        c = ctx.store.contact_by_email(ld.get("email") or "") or {"id": ld.get("contact_id"), "email": ld.get("email"),
                                                                    "name": ld.get("name"), "title": ld.get("title"),
                                                                    "account_id": ld.get("account_id")}
        if ld.get("source") == "event":
            if ld.get("attended") and not ctx.store.one("SELECT id FROM meetings WHERE account_id=? AND started_at>=?",
                                                        (ld.get("account_id"), ld.get("received_at"))):
                out.append({"pool": "warm", "source": "event", "reason": f"attended {ld.get('event')}, no meeting since",
                            "at": ld.get("received_at") or "", **_contact_dict(c)})
            continue
        out.append({"pool": "warm", "source": "inbound", "reason": f"inbound {ld.get('source') or 'lead'} not worked",
                    "at": ld.get("received_at") or "", **_contact_dict(c)})
    # social engagement
    for i in ctx.store.insights("social_engagement", since_iso=since14):
        v = i.get("value") or {}
        c = ctx.store.get("contacts", v["contact_id"]) if v.get("contact_id") else None
        if c:
            add("social", c, "engaged with company content", i.get("observed_at"))
    # closed-lost recycle
    rec = _iso(now - timedelta(days=int(cfg(ctx, "recycle_days", 90))))
    for d in ctx.store.select("deals", "owner=?", (owner,)):
        if pipeline.is_lost(d) and (d.get("close_date") or d.get("last_activity_at") or "") <= rec:
            a = ctx.store.account(d["account_id"]) if d.get("account_id") else None
            if a:
                for p in rb.pick_contacts(rb_ctx, a, now, 1):
                    out.append({"pool": "warm", "source": "recycle", "reason": f"closed-lost {d['name']}: check timing",
                                "at": d.get("close_date") or "", **p, "account_id": a["id"]})
    order = {k: i for i, k in enumerate(cfg(ctx, "warm_order", WARM_ORDER))}
    out.sort(key=lambda r: (order.get(r["source"], 99), -_day(r["at"])))  # pool order, then most recent first
    return out


def _day(at: str | None) -> int:
    try:
        return int((at or "")[:10].replace("-", ""))
    except ValueError:
        return 0


# ---------- cold pool ----------
def _sourced_today(ctx, now) -> list[str]:
    ss, ss_ctx = _peer(ctx, "signal-sourcing")
    if ss is None:
        return []
    try:
        return [b["account_id"] for b in ss.dispatch(ss_ctx, now)["batch"]]
    except Exception as e:
        ctx.audit.log("daily_book.dispatch_error", error=str(e)[:200])
        return []


def fill_contacts(ctx, acct: dict) -> list[dict]:
    """Buyers for an account with none on file, from a hosted MCP people search (stored locally, never in the CRM)."""
    if not cfg(ctx, "fill_contacts", False):
        return []
    from gtm_core.connectors.mcp_remote import McpConfig, McpError
    mc = McpConfig.load()
    if mc.ready("people_search"):
        return []
    titles = profile.company(ctx).get("personas", {}).get("search_titles") or cfg(ctx, "search_titles", [])
    try:
        got = mc.run("people_search", {"domain": acct.get("domain"), "titles": titles, "limit": 5},
                     getattr(ctx, "mcp_factory", None)).get("people") or []
    except McpError as e:
        ctx.audit.log("daily_book.fill_error", account=acct["id"], error=str(e)[:200])
        return []
    added = []
    for p in got:
        email = (p.get("email") or "").lower()
        if "@" not in email:
            continue
        cid = f"mcp:{email}"
        ctx.store.upsert("contacts", {"id": cid, "account_id": acct["id"], "name": p.get("name"), "email": email,
                                      "title": p.get("title"), "linkedin": p.get("linkedin_url") or p.get("linkedin"),
                                      "source": "mcp:people_search"})
        added.append(cid)
    return added


def cold_pool(ctx, rb, rb_ctx, owner: str, now: datetime, sourced: list[str]) -> list[dict]:
    scores = rb.latest_scores(rb_ctx)
    floor = float(cfg(ctx, "icp_floor", 30))
    rows = []
    for a in rb.rep_accounts(rb_ctx, owner):
        sc = scores.get(a["id"]) or {}
        if sc.get("tier") == "X":
            continue
        fit, reasons = icp_fit(a, rb.icp(rb_ctx))
        if reasons and reasons[0].startswith("excluded industry"):
            continue
        if not sc and fit < floor:
            continue
        if rb.open_deals(rb_ctx, a["id"]):
            continue
        sigs = rb.account_signals(rb_ctx, a, now)
        wn = rb.why_now(sigs)
        if not (sc or a["id"] in sourced):
            continue
        rows.append((a, sc, wn, a["id"] in sourced))
    # sourced today first, then Signal Scout score, then accounts with a sayable why-now line
    rows.sort(key=lambda x: (not x[3], -float(x[1].get("score") or 0), x[2] is None))
    out = []
    per = int(cfg(ctx, "max_per_account", 3))
    for a, sc, wn, src in rows:
        picks = rb.pick_contacts(rb_ctx, a, now, per)
        if not picks and fill_contacts(ctx, a):
            picks = rb.pick_contacts(rb_ctx, a, now, per)
        for p in picks:
            out.append({"pool": "cold", "source": "sourced_signal" if src else "signal_scout",
                        "reason": (wn or {}).get("say_it") or f"tier {sc.get('tier') or '?'} account, score {sc.get('score')}",
                        "why_now": (wn or {}).get("say_it"), "at": "", **p, "account_id": a["id"]})
    return out


# ---------- the book ----------
def build(ctx, owner: str, now: datetime | None = None) -> dict:
    ensure_schema(ctx)
    now = _now(now)
    rb, rb_ctx = _peer(ctx, "rep-brief")
    if rb is None:
        raise RuntimeError("Daily Book needs the rep-brief agent installed")
    slots, warm_target = plan(ctx, owner)
    sourced = _sourced_today(ctx, now)
    per = int(cfg(ctx, "max_per_account", 3))
    seen, per_acct, held = set(), {}, []

    def take(pool_rows: list[dict], n: int) -> list[dict]:
        got = []
        for r in pool_rows:
            if len(got) >= n:
                break
            e = r.get("email") or ""
            if not e or e in seen:
                continue
            acct = ctx.store.account(r["account_id"]) if r.get("account_id") else None
            if acct and per_acct.get(acct["id"], 0) >= per:
                continue
            why = blocked(ctx, rb, rb_ctx, acct, r, owner, now, r["source"])
            if why:
                held.append({"email": e, "source": r["source"], "why": why})
                seen.add(e)
                continue
            seen.add(e)
            if acct:
                per_acct[acct["id"]] = per_acct.get(acct["id"], 0) + 1
                r["company"] = acct.get("name")
            got.append(r)
        return got

    warm_all, cold_all = warm_pool(ctx, rb, rb_ctx, owner, now), cold_pool(ctx, rb, rb_ctx, owner, now, sourced)
    warm = take(warm_all, warm_target)
    cold = take(cold_all, slots - warm_target)
    backfill = {"warm_from_cold": 0, "cold_from_warm": 0}
    if len(warm) < warm_target:
        extra = take(cold_all, warm_target - len(warm))
        backfill["warm_from_cold"] = len(extra)
        cold += extra
    if len(cold) < slots - warm_target:
        extra = take(warm_all, (slots - warm_target) - len(cold))
        backfill["cold_from_warm"] = len(extra)
        warm += extra
    rows = warm + cold
    day = now.date().isoformat()
    ctx.store.execute("DELETE FROM daily_book WHERE book_date=? AND owner=? AND status='open'", (day, owner))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["action"] = _action(r)
        ctx.store.execute("INSERT INTO daily_book (id, book_date, owner, rank, pool, source, reason, contact_id, email, name, "
                          "title, account_id, company, why_now, action, status, created_at) VALUES "
                          "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                          (f"{day}:{owner}:{r['email']}", day, owner, i, r["pool"], r["source"], r["reason"],
                           r.get("contact_id"), r["email"], r.get("name"), r.get("title"), r.get("account_id"),
                           r.get("company"), r.get("why_now"), r["action"], "open", now_iso()))
    short = slots - len(rows)
    return {"owner": owner, "date": day, "slots": slots, "warm_target": warm_target, "filled": len(rows),
            "warm": len([r for r in rows if r["pool"] == "warm"]), "cold": len([r for r in rows if r["pool"] == "cold"]),
            "shortfall": max(0, short), "backfill": backfill, "rows": rows, "held_out": held,
            "pools": {"warm_candidates": len(warm_all), "cold_candidates": len(cold_all)}}


def _action(r: dict) -> str:
    return {"engaged": "call or LinkedIn; email only with a new reason (never mention the opens)",
            "quiet_deal": "re-engage with the deal's next step",
            "champion_moved": "congratulate and reconnect",
            "inbound": "respond to the inbound request",
            "event": "follow up on the event with one takeaway",
            "social": "engage on their content, then a short note",
            "recycle": "check whether timing changed since the loss",
            "sourced_signal": "first touch on the sourced signal",
            "signal_scout": "first touch on the account's best signal"}.get(r["source"], "reach out")


def predraft(ctx, book: dict, now: datetime | None = None) -> dict:
    """Queue first-touch sequences for cold rows through ICP Outbound, each waiting for the AE's approval."""
    if not cfg(ctx, "predraft_cold", True):
        return {"queued": 0}
    ob, ob_ctx = _peer(ctx, "icp-outbound")
    if ob is None:
        return {"queued": 0}
    queued = 0
    for r in book["rows"]:
        if r["pool"] != "cold" or ob.already_drafted(ob_ctx, r.get("contact_id") or ""):
            continue
        acct = ctx.store.account(r["account_id"])
        res = ob.draft_sequence(ob_ctx, acct, {"contact_id": r.get("contact_id"), "email": r["email"], "name": r.get("name"),
                                               "title": r.get("title")}, now, queue=True)
        if res.get("approval"):
            ctx.store.execute("UPDATE daily_book SET approval_id=? WHERE id=?",
                              (res["approval"], f"{book['date']}:{book['owner']}:{r['email']}"))
            queued += 1
    return {"queued": queued}


def format_book(b: dict) -> str:
    head = (f"*Daily book for {b['owner']}* ({b['date']}): {b['filled']} of {b['slots']} "
            f"({b['warm']} warm, {b['cold']} cold)")
    if b["shortfall"]:
        head += f". Short by {b['shortfall']}: not enough people clear the bar today."
    lines = [head]
    for r in b["rows"][:12]:
        lines.append(f"{r['rank']}. {r.get('name') or r['email']}" + (f", {r['title']}" if r.get("title") else "")
                     + (f" at {r['company']}" if r.get("company") else "") + f": {r['action']}")
    if len(b["rows"]) > 12:
        lines.append(f"...and {len(b['rows']) - 12} more (`my_book`).")
    return "\n".join(lines)
