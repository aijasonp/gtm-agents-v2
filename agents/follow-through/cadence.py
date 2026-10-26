"""The cadence ledger: every contact in an active motion holds one next touch with a due time.

All of it is code. config/cadences.yaml says which motions exist, their steps, who drafts each step and when
each is due. The sweep (every 15 minutes) does five things in order:

  1. start     find new motions: external meetings, event attendance, tee-ups, proposals sent
  2. stop      end motions on a reply, a new meeting, a closed deal or an opt-out
  3. advance   a step is done when the evidence shows the touch happened, then the next step's clock starts
  4. draft     steps this agent owns are drafted ahead of time and queued for the AE to confirm
  5. escalate  a step past due (or a draft the AE has not confirmed) runs the escalation ladder once per level

`coverage()` is the guarantee check: every open deal has a contact in a motion or a dated next step, and no
motion is past due without a draft waiting on the AE.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from gtm_core import pipeline, profile, sequences, suppression, writer
from gtm_core.agents import load_module
from gtm_core.store import now_iso
from gtm_core.workflows import get_waits
from gtm_core.worktime import add_business_days, add_business_hours

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS cadence (
      id TEXT PRIMARY KEY, motion TEXT, email TEXT, contact_id TEXT, account_id TEXT, deal_id TEXT, owner TEXT,
      start_ref TEXT, started_at TEXT, step_index INTEGER, step_id TEXT, step_opened_at TEXT, next_touch_at TEXT,
      status TEXT, last_touch_at TEXT, last_touch_kind TEXT, draft_id INTEGER, approval_id INTEGER, ae_owns INTEGER,
      stop_reason TEXT, history TEXT, updated_at TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_cadence_status ON cadence(status, next_touch_at)",
    "CREATE INDEX IF NOT EXISTS ix_cadence_email ON cadence(email, status)",
    """CREATE TABLE IF NOT EXISTS cadence_touches (
      id TEXT PRIMARY KEY, email TEXT, kind TEXT, note TEXT, by TEXT, touched_at TEXT)""",
]
ACTIVE, AWAITING, DONE, STOPPED = "active", "awaiting_ae", "done", "stopped"
LIVE = (ACTIVE, AWAITING)
REPLIES = ("reply", "reply_positive", "reply_negative")


def ensure_schema(ctx) -> None:
    if not getattr(ctx.store, "_cadence_schema", False):
        for s in SCHEMA:
            ctx.store.execute(s)
        ctx.store._cadence_schema = True


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _dt(s) -> datetime | None:
    return pipeline.parse_dt(s)


@lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> dict:
    data = yaml.safe_load(Path(path).read_text()) or {}
    for name, m in (data.get("motions") or {}).items():
        if not m.get("steps"):
            raise ValueError(f"cadences.yaml: motion {name} has no steps")
        for s in m["steps"]:
            if not s.get("id") or not s.get("due"):
                raise ValueError(f"cadences.yaml: motion {name} has a step without id or due")
    return data


def config(ctx) -> dict:
    p = ctx.manifest.path(ctx.manifest.config.get("cadences", "../../config/cadences.yaml"))
    return _load(str(p), p.stat().st_mtime)


def motion(ctx, name: str) -> dict:
    m = (config(ctx).get("motions") or {}).get(name)
    if not m:
        raise KeyError(f"motion {name!r} is not in cadences.yaml")
    return m


def tz(ctx) -> str:
    return profile.company(ctx).get("timezone") or ctx.manifest.config.get("timezone", "UTC")


def step_due(ctx, step: dict, base: datetime, override: str | None = None) -> datetime:
    d = step.get("due") or {}
    if d.get("from_teeup") and override:
        return _dt(override)
    if "hours" in d:
        return add_business_hours(base, float(d["hours"]), tz(ctx))
    if "business_days" in d:
        return add_business_days(base, int(d["business_days"]), tz(ctx))
    raise ValueError(f"step {step.get('id')}: due needs hours, business_days or from_teeup")


def _row(r: dict | None) -> dict | None:
    if r:
        r = dict(r)
        r["history"] = json.loads(r.get("history") or "[]")
    return r


def get(ctx, cid: str) -> dict | None:
    ensure_schema(ctx)
    return _row(ctx.store.one("SELECT * FROM cadence WHERE id=?", (cid,)))


def live_for(ctx, email: str) -> list[dict]:
    ensure_schema(ctx)
    return [_row(r) for r in ctx.store.query("SELECT * FROM cadence WHERE email=? AND status IN (?,?)",
                                             (email.lower(), *LIVE))]


def _save(ctx, row: dict) -> None:
    cols = ["id", "motion", "email", "contact_id", "account_id", "deal_id", "owner", "start_ref", "started_at",
            "step_index", "step_id", "step_opened_at", "next_touch_at", "status", "last_touch_at", "last_touch_kind",
            "draft_id", "approval_id", "ae_owns", "stop_reason", "history", "updated_at"]
    row = {**row, "history": json.dumps(row.get("history") or [], default=str), "updated_at": now_iso()}
    ups = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    ctx.store.execute(f"INSERT INTO cadence ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(id) DO UPDATE SET {ups}", [row.get(c) for c in cols])


def _waits(ctx):
    return get_waits(ctx.store)


def wkey(row: dict) -> str:
    """Waits are per step, so a step escalates once and the next step starts clean."""
    return f"{row['id']}#{row['step_id']}"


# ---------- 1. start ----------
def start(ctx, name: str, email: str, started_at: datetime, ref: str, owner: str | None = None,
          contact_id: str | None = None, account_id: str | None = None, deal_id: str | None = None,
          due_override: str | None = None) -> dict | None:
    """Begin a motion (idempotent per motion, start ref and email). A newer motion for the same person
    supersedes an older live one, so a person is only ever in one cadence."""
    ensure_schema(ctx)
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    cid = f"{name}:{ref}:{email}"
    if ctx.store.one("SELECT id FROM cadence WHERE id=?", (cid,)):
        return None
    for old in live_for(ctx, email):
        if old["started_at"] and old["started_at"] > _iso(started_at):
            return None  # a later motion already owns this person
        _stop(ctx, old, f"superseded by {name}")
    m = motion(ctx, name)
    first = m["steps"][0]
    due = step_due(ctx, first, started_at, due_override)
    row = {"id": cid, "motion": name, "email": email, "contact_id": contact_id, "account_id": account_id,
           "deal_id": deal_id, "owner": owner, "start_ref": ref, "started_at": _iso(started_at), "step_index": 0,
           "step_id": first["id"], "step_opened_at": _iso(started_at), "next_touch_at": _iso(due), "status": ACTIVE,
           "ae_owns": 0, "history": [{"at": _iso(started_at), "event": "started", "motion": name, "ref": ref}]}
    _save(ctx, row)
    ctx.audit.log("cadence.started", id=cid, motion=name, due=row["next_touch_at"])
    return row


def _peer(ctx, agent_id: str):
    eng = load_module(ctx.manifest, "engine")
    return eng._peer(ctx, agent_id)


def _owner(ctx, acct: dict | None, deal: dict | None = None, fallback: str | None = None) -> str | None:
    if deal and deal.get("owner"):
        return deal["owner"]
    if fallback:
        return fallback
    return load_module(ctx.manifest, "engine").owner_for(ctx, acct, None)


def discover(ctx, now: datetime | None = None) -> list[str]:
    """Start motions for everything that happened in the lookback window. Returns the cadence ids started."""
    ensure_schema(ctx)
    now = _now(now)
    since = _iso(now - timedelta(days=int(ctx.manifest.config.get("lookback_days", 14))))
    started = []
    names = set(config(ctx).get("motions") or {})
    sf, sf_ctx = _peer(ctx, "seller-follow-up")
    if "post_meeting" in names:
        for mt in ctx.store.select("meetings", "started_at>=? AND started_at<=?", (since, _iso(now))):
            deal = ctx.store.get("deals", mt["deal_id"]) if mt.get("deal_id") else None
            if deal and not pipeline.is_open(deal):
                continue
            acct = ctx.store.account(mt["account_id"]) if mt.get("account_id") else None
            buyers = sf.buyer_attendees(sf_ctx, mt.get("attendees"), mt.get("account_id")) if sf else []
            for b in buyers:
                if b.get("email"):
                    r = start(ctx, "post_meeting", b["email"], _dt(mt["started_at"]), f"meeting-{mt['id']}",
                              _owner(ctx, acct, deal, mt.get("owner")), b.get("contact_id"), mt.get("account_id"),
                              mt.get("deal_id"))
                    if r:
                        started.append(r["id"])
    for lead in ctx.store.select("leads", "source=? AND event IS NOT NULL AND received_at>=? AND received_at<=?",
                                 ("event", since, _iso(now))):
        name = "event_attended" if lead.get("attended") else "event_missed"
        if name not in names or not lead.get("registered", True):
            continue
        acct = ctx.store.account(lead["account_id"]) if lead.get("account_id") else None
        r = start(ctx, name, lead["email"], _dt(lead["received_at"]), f"event-{lead['event']}",
                  _owner(ctx, acct, None, lead.get("owner")), lead.get("contact_id"), lead.get("account_id"))
        if r:
            started.append(r["id"])
    if "teed_up" in names:
        load_module(ctx.manifest, "engine").ensure_schema(ctx)
        for t in ctx.store.query("SELECT * FROM teeups WHERE created_at>=?", (since,)):
            r = start(ctx, "teed_up", t["email"], _dt(t["created_at"]), f"teeup-{t['id']}", t.get("owner"),
                      t.get("contact_id"), t.get("account_id"), due_override=t.get("due_at"))
            if r:
                started.append(r["id"])
    if "proposal_out" in names:
        for d in ctx.store.query("SELECT * FROM drafts WHERE kind='proposal' AND status='sent' AND created_at>=?", (since,)):
            c = ctx.store.get("contacts", d["contact_id"]) if d.get("contact_id") else None
            deal = ctx.store.get("deals", d["deal_id"]) if d.get("deal_id") else None
            if c and c.get("email"):
                acct = ctx.store.account(d["account_id"]) if d.get("account_id") else None
                r = start(ctx, "proposal_out", c["email"], _dt(d["created_at"]), f"proposal-{d['id']}",
                          _owner(ctx, acct, deal), c["id"], d.get("account_id"), d.get("deal_id"))
                if r:
                    started.append(r["id"])
    return started


# ---------- 2. stop ----------
def _close_pending(ctx, row: dict, why: str) -> None:
    """The step's email is no longer wanted: close its approval if nobody decided it yet (an approved one is
    refused at send time because the cadence moved on)."""
    if row.get("approval_id"):
        n = ctx.store.execute("UPDATE approvals SET status='rejected', decided_at=?, decided_by=?, result=? "
                              "WHERE id=? AND status='pending'",
                              (now_iso(), "follow-through:cadence", json.dumps({"closed": why}), row["approval_id"]))
        if n and row.get("draft_id"):
            ctx.store.execute("UPDATE drafts SET status='rejected' WHERE id=? AND status IN ('queued','draft')",
                              (row["draft_id"],))


def _stop(ctx, row: dict, why: str, status: str = STOPPED, now: datetime | None = None) -> None:
    _close_pending(ctx, row, why)
    row["status"], row["stop_reason"] = status, why
    row["history"].append({"at": _iso(_now(now)), "event": status, "why": why})
    _save(ctx, row)
    w = _waits(ctx)
    for kind in ("touch", "approval"):
        w.cancel(kind, wkey(row), why)
    ctx.audit.log("cadence.stopped", id=row["id"], why=why)


def stop_reason(ctx, row: dict) -> str | None:
    m = motion(ctx, row["motion"])
    stops = set(m.get("stop_on") or [])
    email, since = row["email"], row["started_at"]
    if "suppressed" in stops:
        c = ctx.store.get("contacts", row["contact_id"]) if row.get("contact_id") else ctx.store.contact_by_email(email)
        if suppression.is_suppressed(ctx.store, email, c):
            return "opted out, bounced or do-not-contact"
    if "reply" in stops:
        q = ",".join("?" * len(REPLIES))
        if ctx.store.one(f"SELECT id FROM email_events WHERE email=? AND event IN ({q}) AND occurred_at>?",
                         (email, *REPLIES, since)):
            return "replied: Reply Desk owns the response"
        try:
            if ctx.store.one("SELECT id FROM replies WHERE LOWER(from_email)=? AND received_at>?", (email, since)):
                return "replied: Reply Desk owns the response"
        except Exception:
            pass
    if "meeting" in stops:
        for mt in ctx.store.select("meetings", "started_at>?", (since,)):
            if f"meeting-{mt['id']}" == row["start_ref"]:
                continue
            att = mt.get("attendees") or []
            text = json.dumps(att).lower() if not isinstance(att, str) else att.lower()
            if email in text or (row.get("contact_id") and row["contact_id"] in text):
                return f"new meeting {mt.get('title') or mt['id']}"
    if "deal_closed" in stops and row.get("deal_id"):
        d = ctx.store.get("deals", row["deal_id"])
        if d and not pipeline.is_open(d):
            return f"deal closed ({d.get('status') or d.get('stage')})"
    return None


# ---------- 3. advance ----------
def log_touch(ctx, email: str, kind: str = "manual", note: str = "", by: str = "ae",
              now: datetime | None = None) -> dict:
    ensure_schema(ctx)
    t = _iso(_now(now))
    email = (email or "").strip().lower()
    ctx.store.execute("INSERT INTO cadence_touches (id, email, kind, note, by, touched_at) VALUES (?,?,?,?,?,?)",
                      (f"{email}:{t}:{kind}", email, kind, note[:500], by, t))
    return {"email": email, "kind": kind, "touched_at": t}


def evidence(ctx, row: dict, step: dict) -> tuple[str, str] | None:
    """(touched_at, how) for the first sign this step's touch happened strictly after it opened, else None.
    Strictly after: the touch that advanced the previous step opened this one at that same instant."""
    since, email = _iso(_dt(row["step_opened_at"])), row["email"]
    hits = []
    e = ctx.store.one("SELECT occurred_at FROM email_events WHERE email=? AND event='sent' AND occurred_at>? "
                      "ORDER BY occurred_at LIMIT 1", (email, since))
    if e:
        hits.append((e["occurred_at"], "email sent"))
    t = ctx.store.one("SELECT touched_at, kind FROM cadence_touches WHERE email=? AND touched_at>? ORDER BY touched_at "
                      "LIMIT 1", (email, since))
    if t:
        hits.append((t["touched_at"], f"logged ({t['kind']})"))
    if row.get("contact_id"):
        d = ctx.store.one("SELECT created_at FROM drafts WHERE contact_id=? AND status='sent' AND created_at>? "
                          "ORDER BY created_at LIMIT 1", (row["contact_id"], since))
        if d:
            hits.append((d["created_at"], "draft sent"))
        tk = next((x for x in ctx.store.select("tasks", "contact_id=? AND status='done'", (row["contact_id"],))
                   if x.get("updated_at") and _iso(_dt(x["updated_at"])) > since), None)
        if tk:
            hits.append((tk["updated_at"], "task done"))
    if step.get("kind") and step.get("drafter") not in ("follow-through", "ae"):
        # a peer agent's draft for this step: the AE confirming it (approval) is the touch
        q = ("SELECT d.id, a.decided_at FROM drafts d JOIN approvals a ON a.id=d.approval_id WHERE d.kind=? AND "
             "a.status IN ('approved','executing','executed') AND a.decided_at>? AND (d.contact_id=? OR d.meta LIKE ?)")
        r = ctx.store.one(q, (step["kind"], since, row.get("contact_id") or "", f"%{email}%"))
        if r:
            hits.append((r["decided_at"], f"{step['kind']} confirmed"))
    if row.get("deal_id") and row["motion"] in ("post_meeting", "proposal_out"):
        d = ctx.store.get("deals", row["deal_id"])
        if d and d.get("last_activity_at") and _iso(_dt(d["last_activity_at"])) > since:
            hits.append((_iso(_dt(d["last_activity_at"])), "deal activity"))
    return min(hits) if hits else None


def _advance(ctx, row: dict, touched_at: str, how: str) -> None:
    m = motion(ctx, row["motion"])
    w = _waits(ctx)
    w.resolve("touch", wkey(row), how)
    w.resolve("approval", wkey(row), how)
    _close_pending(ctx, row, f"step already touched: {how}")
    row["history"].append({"at": touched_at, "event": "touched", "step": row["step_id"], "how": how})
    row["last_touch_at"], row["last_touch_kind"] = touched_at, how
    nxt = int(row["step_index"]) + 1
    if nxt >= len(m["steps"]):
        row["status"], row["stop_reason"], row["next_touch_at"] = DONE, "cadence complete", None
        row["history"].append({"at": touched_at, "event": "done"})
    else:
        step = m["steps"][nxt]
        row.update({"step_index": nxt, "step_id": step["id"], "step_opened_at": touched_at,
                    "next_touch_at": _iso(step_due(ctx, step, _dt(touched_at))), "status": ACTIVE,
                    "draft_id": None, "approval_id": None, "ae_owns": 0})
    _save(ctx, row)


# ---------- 4. draft ----------
def _facts(ctx, row: dict, step: dict) -> dict:
    c = (ctx.store.get("contacts", row["contact_id"]) if row.get("contact_id") else None) \
        or ctx.store.contact_by_email(row["email"]) or {}
    a = ctx.store.account(row["account_id"]) if row.get("account_id") else None
    d = ctx.store.get("deals", row["deal_id"]) if row.get("deal_id") else None
    facts = {"contact_name": c.get("name"), "contact_title": c.get("title"), "company": (a or {}).get("name"),
             "motion": motion(ctx, row["motion"]).get("description", row["motion"]), "step": step["id"],
             "touches_so_far": sum(1 for h in row["history"] if h.get("event") == "touched")}
    if d:
        facts["deal"] = {"name": d.get("name"), "stage": d.get("stage"), "next_step": d.get("next_step")}
    sf, sf_ctx = _peer(ctx, "seller-follow-up")
    if sf and d:
        mt = sf.last_meeting(sf_ctx, d["id"])
        if mt:
            facts["last_call"] = {"title": mt.get("title"), "date": (mt.get("started_at") or "")[:10],
                                  "points": sf.summary_points(mt.get("summary"))[:4]}
    rb, rb_ctx = _peer(ctx, "rep-brief")
    if rb and a:
        wn = rb.why_now(rb.account_signals(rb_ctx, a))
        if wn:
            facts["reason_now"] = wn["say_it"]
    return facts


def _template(facts: dict, step: dict) -> str:
    first = (facts.get("contact_name") or "there").split(" ")[0]
    lines = {
        "check_in": "Wanted to make sure you have what you need from our call. Is the next step we agreed still on track?",
        "value_add": "One thing that may help your team" + (f": {facts['reason_now']}." if facts.get("reason_now")
                                                           else " as you work through this.") + " Worth a look?",
        "next_step": "Could we lock the next step we discussed? Two times that work this week: Tuesday or Thursday afternoon.",
        "bump": "Picking up from the event: would a 20-minute call to compare notes for your team be useful?",
        "last_touch": "I will leave it here for now. If the session notes would help, I am glad to send them.",
        "second_touch": (facts.get("reason_now") or "Following my note") + ". Would a short call next week make sense?",
        "third_touch": "I will not keep writing. If timing changes, reply here and I will pick it up.",
        "confirm_received": "Checking that the proposal reached you. Happy to walk through it in 15 minutes if useful.",
        "decision_check": "What is left to decide on the proposal, and who else should weigh in?",
        "last_check": "Is this still a priority this quarter? A yes or no either way helps me plan.",
    }
    body = lines.get(step["id"], "Following up on our last conversation. Is there anything you need from me?")
    subj = {"confirm_received": "Proposal", "decision_check": "Proposal next step"}.get(step["id"], "Next step")
    return f"Subject: {subj}\n\nHi {first},\n\n{body}"


def draft_step(ctx, row: dict, step: dict, now: datetime | None = None) -> dict:
    """Write this step's email from facts only (template floor), gate it, and queue it for the owner to confirm."""
    facts = _facts(ctx, row, step)
    d = writer.write(ctx, "follow-up email from an account executive", facts,
                     (step.get("ask") or "Short follow-up with one clear ask.") +
                     " Never mention email opens, clicks or tracking.", _template(facts, step),
                     max_words=int(ctx.manifest.config.get("max_words", 110)))
    did = ctx.store.add_draft(ctx.manifest.id, f"cadence_{step['id']}", d.body, subject=d.subject, gate_score=d.score,
                              gate_passed=d.passed, source=d.source, account_id=row.get("account_id"),
                              deal_id=row.get("deal_id"), contact_id=row.get("contact_id"),
                              meta={"owner": row.get("owner"), "cadence_id": row["id"], "step": step["id"],
                                    "to": row["email"]})
    out = {"draft_id": did, "gate": d.score, "passed": d.passed, "approval": None}
    if not d.passed:
        ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("needs_rewrite", did))
        row["ae_owns"] = 1  # nothing gate-passing to send: the AE writes this touch, we still watch the clock
        row["history"].append({"at": _iso(_now(now)), "event": "draft_failed_gate", "step": step["id"], "fix": d.fix})
        _save(ctx, row)
        return out
    c = ctx.store.contact_by_email(row["email"]) or {}
    a = ctx.store.account(row["account_id"]) if row.get("account_id") else {}
    rid = ctx.request_approval("pipeline_email", {
        "contact": {"email": row["email"], "name": c.get("name"), "company": (a or {}).get("name")},
        "subject": d.subject, "body": d.body, "draft_id": did, "owner": row.get("owner"), "approver": row.get("owner"),
        "cadence_id": row["id"], "cadence": row["motion"], "motion": "pipeline", "step": step["id"]},
        summary=f"{row.get('owner') or 'unassigned'}: confirm {step['id']} to {c.get('name') or row['email']} "
                f"(due {row['next_touch_at'][:16].replace('T', ' ')} UTC, gate {d.score}/40)")
    ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", rid, did))
    row.update({"draft_id": did, "approval_id": rid, "status": AWAITING})
    row["history"].append({"at": _iso(_now(now)), "event": "drafted", "step": step["id"], "approval": rid})
    _save(ctx, row)
    cfg = config(ctx)
    deadline = max(_dt(row["next_touch_at"]), add_business_hours(_now(now), float(cfg.get("approval_sla_hours", 4)),
                                                                   tz(ctx)))
    _waits(ctx).open("approval", wkey(row), deadline, cfg.get("escalation"), row.get("owner"),
                     {"email": row["email"], "step": step["id"], "approval_id": rid})
    out["approval"] = rid
    return out


def _approval_state(ctx, row: dict) -> str | None:
    if not row.get("approval_id"):
        return None
    a = ctx.store.one("SELECT status FROM approvals WHERE id=?", (row["approval_id"],))
    return a["status"] if a else None


# ---------- 5. escalate ----------
def manager(ctx) -> str | None:
    t = profile.company(ctx).get("team", {})
    m = t.get("manager")
    return (m.get("name") if isinstance(m, dict) else m) or None


def escalate(ctx, w: dict) -> dict:
    who = w.get("owner") if w.get("notify") == "owner" else (manager(ctx) or "sales manager")
    if w["subject"].startswith("held:"):
        row = {"email": w["payload"].get("email"), "motion": "outbound sequence", "step_id": f"step {w['payload'].get('step')}"}
    else:
        row = get(ctx, w["subject"].split("#", 1)[0]) or {}
    what = "confirm the drafted email" if w["kind"] == "approval" else "make the touch"
    late = "due" if w["escalation_level"] == 0 else "overdue"
    msg = (f":alarm_clock: *Follow-up {late}* for {who}: {what} to {row.get('email')} "
           f"({row.get('motion')}, step {row.get('step_id')}), deadline {w['deadline_at'][:16].replace('T', ' ')} UTC")
    if w.get("notify") != "owner":
        msg += f". Owner: {w.get('owner') or 'unassigned'}."
    ctx.slack.post(msg)
    ctx.audit.log("cadence.escalated", id=w["subject"], kind=w["kind"], level=w["escalation_level"], to=who)
    return {"id": w["subject"], "kind": w["kind"], "level": w["escalation_level"], "to": who}


# ---------- held sequence steps (sequence_release: per_step) ----------
def release_held(ctx, now: datetime | None = None) -> dict:
    """Queue each due held step as one `sequence_step` approval for its owner, unless the person replied,
    opted out or is now with an AE."""
    now = _now(now)
    queued = cancelled = 0
    cfg = config(ctx)
    for h in sequences.due(ctx.store, now):
        email = h["email"]
        why = None
        if suppression.is_suppressed(ctx.store, email, ctx.store.contact_by_email(email)):
            why = "opted out, bounced or do-not-contact"
        elif ctx.store.one("SELECT id FROM email_events WHERE email=? AND event IN (?,?,?) AND occurred_at>=?",
                           (email, *REPLIES, h["created_at"])):
            why = "replied"
        else:
            load_module(ctx.manifest, "engine").ensure_schema(ctx)
            if ctx.store.one("SELECT id FROM teeups WHERE email=? AND status='open'", (email,)):
                why = "with the AE (tee-up)"
        if why:
            sequences.mark(ctx.store, h["id"], sequences.CANCELLED, why)
            cancelled += 1
            continue
        rid = ctx.request_approval("sequence_step", {
            "held_id": h["id"], "contact": h["contact"], "subject": h["subject"], "body": h["body"],
            "draft_id": h["draft_id"], "owner": h["owner"], "approver": h["owner"], "step": f"step_{h['step_index'] + 1}",
            "campaign": h["meta"].get("campaign"), "motion": "outbound"},
            summary=f"{h['owner'] or 'unassigned'}: confirm step {h['step_index'] + 1} to {h['contact'].get('name') or email}")
        sequences.mark(ctx.store, h["id"], sequences.QUEUED, approval_id=rid)
        _waits(ctx).open("approval", f"held:{h['id']}", add_business_hours(now, float(cfg.get("approval_sla_hours", 4)),
                                                                            tz(ctx)),
                         cfg.get("escalation"), h["owner"], {"email": email, "step": h["step_index"] + 1})
        queued += 1
    return {"queued": queued, "cancelled": cancelled}


def _resolve_held_waits(ctx) -> None:
    for w in _waits(ctx).list("approval"):
        if not w["subject"].startswith("held:"):
            continue
        h = ctx.store.one("SELECT status, approval_id FROM held_steps WHERE id=?", (w["subject"][5:],))
        a = ctx.store.one("SELECT status FROM approvals WHERE id=?", (h["approval_id"],)) if h and h["approval_id"] else None
        if not h or h["status"] != sequences.QUEUED or (a and a["status"] != "pending"):
            _waits(ctx).resolve("approval", w["subject"], (a or {}).get("status") or (h or {}).get("status") or "gone")


# ---------- the sweep ----------
def sweep(ctx, now: datetime | None = None) -> dict:
    ensure_schema(ctx)
    now = _now(now)
    cfg = config(ctx)
    started = discover(ctx, now)
    held = release_held(ctx, now)
    _resolve_held_waits(ctx)
    stats = {"started": len(started), "stopped": 0, "advanced": 0, "drafted": 0, "missed": 0, "escalated": [],
             "held_queued": held["queued"], "held_cancelled": held["cancelled"]}
    rows = [_row(r) for r in ctx.store.query("SELECT * FROM cadence WHERE status IN (?,?) ORDER BY next_touch_at", LIVE)]
    ahead = float(cfg.get("draft_ahead_hours", 16))
    grace = float(cfg.get("grace_hours", 4))
    w = _waits(ctx)
    for row in rows:
        why = stop_reason(ctx, row)
        if why:
            _stop(ctx, row, why, now=now)
            stats["stopped"] += 1
            continue
        m = motion(ctx, row["motion"])
        step = m["steps"][int(row["step_index"])]
        ev = evidence(ctx, row, step)
        if ev:
            _advance(ctx, row, ev[0], ev[1])
            stats["advanced"] += 1
            row = get(ctx, row["id"])
            if row["status"] == DONE:
                continue
            step = m["steps"][int(row["step_index"])]
        due = _dt(row["next_touch_at"])
        state = _approval_state(ctx, row)
        if row["status"] == AWAITING and state == "rejected":
            row.update({"status": ACTIVE, "ae_owns": 1, "approval_id": None})  # the AE will write it
            row["history"].append({"at": _iso(now), "event": "draft_rejected", "step": step["id"]})
            _save(ctx, row)
            w.resolve("approval", wkey(row), "rejected by AE")
        drafts_here = step.get("drafter") == "follow-through" and not row.get("ae_owns")
        if drafts_here and row["status"] == ACTIVE and now >= _draft_time(ctx, due, ahead):
            if draft_step(ctx, row, step, now).get("approval"):
                stats["drafted"] += 1
            row = get(ctx, row["id"])
        if row["status"] == ACTIVE and now >= add_business_hours(due, grace, tz(ctx)) and not w.get("touch", wkey(row)):
            w.open("touch", wkey(row), add_business_hours(due, grace, tz(ctx)), cfg.get("escalation"),
                   row.get("owner"), {"email": row["email"], "step": row["step_id"]})
            stats["missed"] += 1
    for item in w.due(now):
        if item["kind"] in ("touch", "approval"):
            stats["escalated"].append(escalate(ctx, item))
    return stats


def _draft_time(ctx, due: datetime, ahead_hours: float) -> datetime:
    """`ahead_hours` business hours before the due time (walks back hour by hour inside working time)."""
    t = due
    left = ahead_hours
    while left > 0:
        t -= timedelta(hours=1)
        lt = t.astimezone(__import__("zoneinfo").ZoneInfo(tz(ctx)))
        if lt.weekday() < 5 and 9 <= lt.hour < 17:
            left -= 1
    return t


# ---------- the guarantee ----------
def coverage(ctx, now: datetime | None = None) -> dict:
    """Gaps that break the no-gaps promise: open deals with nobody in a motion and no dated next step, and live
    motions past due with no draft waiting on the AE."""
    ensure_schema(ctx)
    now = _now(now)
    sf, sf_ctx = _peer(ctx, "seller-follow-up")
    gaps = []
    for d in ctx.store.select("deals"):
        if not pipeline.is_open(d):
            continue
        live = ctx.store.one("SELECT id FROM cadence WHERE deal_id=? AND status IN (?,?)", (d["id"], *LIVE))
        nsd = _dt(d.get("next_step_date"))
        if not live and not (nsd and nsd >= now):
            pc = sf.primary_contact(sf_ctx, d) if sf else None
            gaps.append({"type": "deal_without_follow_up", "deal": d["name"], "owner": d.get("owner"),
                         "contact": (pc or {}).get("email"), "fix": "start a motion or set a dated next step"})
    for r in ctx.store.query("SELECT * FROM cadence WHERE status=? AND next_touch_at<?", (ACTIVE, _iso(now))):
        gaps.append({"type": "touch_past_due", "email": r["email"], "motion": r["motion"], "step": r["step_id"],
                     "owner": r.get("owner"), "due": r["next_touch_at"], "fix": "make the touch or log it"})
    live = ctx.store.one("SELECT COUNT(*) AS n FROM cadence WHERE status IN (?,?)", LIVE)["n"]
    awaiting = ctx.store.one("SELECT COUNT(*) AS n FROM cadence WHERE status=?", (AWAITING,))["n"]
    return {"live": live, "awaiting_ae": awaiting, "gaps": gaps, "ok": not gaps}


def schedule(ctx, owner: str | None = None, days: int = 7, now: datetime | None = None) -> list[dict]:
    """Every next touch in the coming `days`, soonest first, for one owner or everyone."""
    ensure_schema(ctx)
    until = _iso(_now(now) + timedelta(days=days))
    sql, p = "SELECT * FROM cadence WHERE status IN (?,?) AND next_touch_at<=?", [*LIVE, until]
    if owner:
        sql += " AND owner=?"
        p.append(owner)
    return [{k: r.get(k) for k in ("email", "owner", "motion", "step_id", "next_touch_at", "status", "approval_id")}
            for r in ctx.store.query(sql + " ORDER BY next_touch_at", p)]
