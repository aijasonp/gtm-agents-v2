"""Follow-Through: engagement triggers that hand prospects to the AE.

Every decision here is code: facts are counted from the email events, a RevOps-owned decision
table (config/triggers.yaml) picks the action, and the action is a fixed recipe. No model call.

  facts_for()       counts human opens, clicks, replies and steps for one person in the window
  decide()          runs the decision table on those facts
  act()             tee_up: pause automation, AE task, CRM task for approval, brief to Slack
                    notify_owner: FYI to the owner, nothing paused
  evaluate_email()  facts -> decision -> act, for one address (called on every email event)
  evaluate_recent() the same for everyone with engagement since the last sweep
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from gtm_core import engagement, pipeline, profile, rules, suppression
from gtm_core.agents import Manifest, load_module
from gtm_core.store import now_iso
from gtm_core.worktime import add_business_hours

SCHEMA = """CREATE TABLE IF NOT EXISTS teeups (
  id TEXT PRIMARY KEY, email TEXT, contact_id TEXT, account_id TEXT, owner TEXT, rule TEXT, priority TEXT,
  reason TEXT, facts TEXT, status TEXT, due_at TEXT, task_id TEXT, approvals TEXT, created_at TEXT,
  resolved_at TEXT, outcome TEXT)"""

MOTIONS = {"icp-outbound": "outbound", "event-campaigns": "event", "lead-triage": "inbound",
           "seller-follow-up": "pipeline", "follow-through": "pipeline", "rep-brief": "push_button",
           "reply-desk": "pipeline", "proposal-builder": "pipeline"}
REPLY_EVENTS = ("reply", "reply_positive", "reply_negative")


def ensure_schema(ctx) -> None:
    if not getattr(ctx.store, "_follow_through_schema", False):
        ctx.store.execute(SCHEMA)
        ctx.store._follow_through_schema = True


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


@lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> tuple[dict, dict]:
    import yaml
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return raw, rules.load_tables(path)


def trigger_config(ctx) -> tuple[dict, dict]:
    """(settings, tables) from config/triggers.yaml, reloaded when the file changes."""
    p = ctx.manifest.path(cfg(ctx, "triggers", "../../config/triggers.yaml"))
    return _load(str(p), p.stat().st_mtime)


def _peer(ctx, agent_id: str):
    """Another agent's engine (rep-brief for ownership and why-now), or None when not installed."""
    root = ctx.manifest.path(f"../{agent_id}")
    if not (root / "agent.yaml").exists():
        return None, None
    m = Manifest.load(root)
    peer = type(ctx)(**{**ctx.__dict__, "manifest": m})
    return load_module(m, "engine"), peer


def owner_for(ctx, acct: dict | None, draft: dict | None) -> str | None:
    meta = (draft or {}).get("meta") or {}
    if isinstance(meta, str):
        meta = json.loads(meta or "{}")
    if meta.get("owner"):
        return meta["owner"]
    if not acct:
        return None
    rb, peer = _peer(ctx, "rep-brief")
    if rb is None:
        return acct.get("owner")
    who, _ = rb.assigned_owner(peer, acct)
    return who


def _latest_draft(ctx, contact_id: str | None, email: str) -> dict | None:
    row = ctx.store.one("SELECT d.* FROM email_events e JOIN drafts d ON d.id=e.draft_id WHERE e.email=? AND "
                        "e.draft_id IS NOT NULL ORDER BY e.occurred_at DESC, e.id DESC LIMIT 1", (email,))
    if not row and contact_id:
        row = ctx.store.one("SELECT * FROM drafts WHERE contact_id=? AND status IN ('sent','queued') ORDER BY id DESC "
                            "LIMIT 1", (contact_id,))
    if row:
        row["meta"] = json.loads(row.get("meta") or "{}")
    return row


def _tier(ctx, account_id: str | None) -> str | None:
    if not account_id:
        return None
    r = ctx.store.one("SELECT tier FROM scores WHERE account_id=? ORDER BY id DESC LIMIT 1", (account_id,))
    return r["tier"] if r else None


def _replied_in_reply_desk(ctx, email: str, since: str) -> bool:
    try:
        return bool(ctx.store.one("SELECT id FROM replies WHERE LOWER(from_email)=? AND received_at>=? LIMIT 1",
                                  (email, since)))
    except Exception:  # Reply Desk not installed or never run: its table does not exist yet
        return False


def facts_for(ctx, email: str, now: datetime | None = None) -> dict:
    """Everything a trigger rule may test, counted from stored events. Opens are human opens only."""
    ensure_schema(ctx)
    settings, _ = trigger_config(ctx)
    now = _now(now)
    email = (email or "").strip().lower()
    window = int(settings.get("window_days", 7))
    since = (now - timedelta(days=window)).isoformat()
    ev = ctx.store.query("SELECT event, machine, occurred_at FROM email_events WHERE email=? AND occurred_at>=? "
                         "AND occurred_at<=?", (email, since, now.isoformat()))
    count = {k: 0 for k in ("open", "click", "sent", "reply")}
    last_send = None
    for e in ev:
        k = "reply" if e["event"] in REPLY_EVENTS else e["event"]
        if k == "open" and e["machine"]:
            continue
        if k in count:
            count[k] += 1
        if k == "sent" and (last_send is None or e["occurred_at"] > last_send):
            last_send = e["occurred_at"]
    contact = ctx.store.contact_by_email(email)
    acct = ctx.store.account(contact["account_id"]) if contact and contact.get("account_id") else None
    draft = _latest_draft(ctx, contact["id"] if contact else None, email)
    if not acct and draft and draft.get("account_id"):
        acct = ctx.store.account(draft["account_id"])
    open_deal = bool(acct) and any(pipeline.is_open(d) for d in ctx.store.select("deals", "account_id=?", (acct["id"],)))
    cooldown = (now - timedelta(days=int(settings.get("cooldown_days", 14)))).isoformat()
    teed = ctx.store.one("SELECT id FROM teeups WHERE email=? AND created_at>=? AND status IN ('open','actioned')",
                         (email, cooldown))
    return {
        "email": email,
        "human_opens": count["open"],
        "clicks": count["click"],
        "replied": count["reply"] > 0 or _replied_in_reply_desk(ctx, email, since),
        "steps_sent": count["sent"],
        "days_since_send": pipeline.days_since(last_send, now) if last_send else None,
        "motion": MOTIONS.get((draft or {}).get("agent"), "other"),
        "tier": _tier(ctx, acct["id"] if acct else None),
        "has_open_deal": open_deal,
        "suppressed": suppression.is_suppressed(ctx.store, email, contact),
        "teed_up": bool(teed),
        "_contact": contact, "_account": acct, "_draft": draft,
    }


def decide(ctx, facts: dict) -> rules.Result:
    _, tables = trigger_config(ctx)
    t = tables.get(cfg(ctx, "trigger_table", "engagement"))
    if t is None:
        raise rules.RuleError(f"trigger table {cfg(ctx, 'trigger_table', 'engagement')!r} not found in triggers.yaml")
    public = {k: v for k, v in facts.items() if not k.startswith("_")}
    return rules.evaluate(t, public, prefer=cfg(ctx, "rules_engine", "auto"))


def _tz(ctx) -> str:
    return profile.company(ctx).get("timezone") or cfg(ctx, "timezone", "UTC")


def brief(ctx, facts: dict, decision: dict, owner: str | None) -> dict:
    """What the AE gets: who, which account, a sayable reason to call now, and what not to say."""
    c, a = facts["_contact"] or {}, facts["_account"] or {}
    why = None
    rb, peer = _peer(ctx, "rep-brief")
    if rb is not None and a:
        why = rb.why_now(rb.account_signals(peer, a))
    return {"owner": owner, "contact": c.get("name") or facts["email"], "title": c.get("title"),
            "email": facts["email"], "phone": c.get("phone"), "account": a.get("name"), "account_id": a.get("id"),
            "why_now": why, "trigger": decision.get("reason"), "priority": decision.get("priority", "normal"),
            "do_not_say": "Never mention that they opened or clicked an email. Use the why-now line or the account."}


def _format(b: dict, due: str | None) -> str:
    lines = [f"*{'Tee-up' if due else 'FYI'} for {b['owner'] or 'unassigned'}*: {b['contact']}"
             + (f", {b['title']}" if b.get("title") else "") + (f" at {b['account']}" if b.get("account") else ""),
             f"Trigger: {b['trigger']} (priority {b['priority']})"]
    if b.get("why_now"):
        lines.append(f"Why now: {b['why_now']['say_it']}")
    if due:
        lines.append(f"Reach out by {due[:16].replace('T', ' ')} UTC. Automation is paused for this person.")
    lines.append(b["do_not_say"])
    return "\n".join(lines)


def act(ctx, facts: dict, decision: dict, now: datetime | None = None) -> dict:
    """Carry out a decision. Only `sequence_stop` runs at once (it only reduces contact); the CRM task waits
    for approval like every other write."""
    ensure_schema(ctx)
    now = _now(now)
    action = decision.get("action", "none")
    if action not in ("tee_up", "notify_owner"):
        return {"action": "none"}
    c, a, d = facts["_contact"], facts["_account"], facts["_draft"]
    owner = owner_for(ctx, a, d)
    b = brief(ctx, facts, decision, owner)
    if action == "notify_owner":
        ctx.slack.post(_format(b, None))
        ctx.audit.log("follow_through.notified", email=facts["email"], rule=decision.get("rule"), owner=owner)
        return {"action": "notify_owner", "owner": owner, "brief": b}
    due = add_business_hours(now, float(decision.get("sla_hours", 24)), _tz(ctx)).isoformat()
    tid = f"teeup:{facts['email']}:{now.date().isoformat()}"
    approvals = []
    if decision.get("pause", True):
        approvals.append(ctx.request_approval("sequence_stop", {"email": facts["email"],
                                                                "reason": f"teed up for AE: {decision.get('reason')}"},
                                              auto_safe=True))
    ctx.store.upsert("tasks", {"id": tid, "owner": owner, "account_id": (a or {}).get("id"),
                               "contact_id": (c or {}).get("id"), "title": f"Reach out to {b['contact']}"
                               + (f" at {b['account']}" if b.get("account") else ""), "due_at": due,
                               "status": "open", "source": ctx.manifest.id, "brief": b})
    approvals.append(ctx.request_approval("crm_task", {
        "subject": f"Tee-up: {b['contact']}" + (f" ({b['account']})" if b.get("account") else ""),
        "body": _format(b, due), "due_at": due[:10], "account_crm_id": (a or {}).get("crm_id"), "owner": owner},
        summary=f"{owner or 'unassigned'}: tee-up {b['contact']} ({decision.get('reason')})"))
    ctx.store.execute("INSERT INTO teeups (id, email, contact_id, account_id, owner, rule, priority, reason, facts, "
                      "status, due_at, task_id, approvals, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (f"{tid}:{decision.get('rule')}", facts["email"], (c or {}).get("id"), (a or {}).get("id"), owner,
                       decision.get("rule"), decision.get("priority", "normal"), decision.get("reason"),
                       json.dumps({k: v for k, v in facts.items() if not k.startswith("_")}, default=str), "open", due,
                       tid, json.dumps(approvals), now.isoformat()))
    ctx.slack.post(_format(b, due))
    ctx.audit.log("follow_through.teed_up", email=facts["email"], rule=decision.get("rule"), owner=owner, due=due)
    return {"action": "tee_up", "owner": owner, "due_at": due, "task_id": tid, "approvals": approvals, "brief": b}


def evaluate_email(ctx, email: str, now: datetime | None = None, apply: bool = True) -> dict:
    facts = facts_for(ctx, email, now)
    res = decide(ctx, facts)
    out = {"email": facts["email"], "facts": {k: v for k, v in facts.items() if not k.startswith("_")},
           "decision": res.as_dict()}
    if apply:
        out["result"] = act(ctx, facts, res.output, now)
    return out


def evaluate_recent(ctx, now: datetime | None = None, apply: bool = True) -> dict:
    """Everyone with an open, click or reply since the last sweep (at most one window back)."""
    ensure_schema(ctx)
    settings, _ = trigger_config(ctx)
    now = _now(now)
    floor = (now - timedelta(days=int(settings.get("window_days", 7)))).isoformat()
    since = max(ctx.store.get_state("follow_through:last_sweep") or floor, floor)
    emails = [r["email"] for r in ctx.store.query(
        "SELECT DISTINCT email FROM email_events WHERE created_at>=? AND event IN ('open','click','reply',"
        "'reply_positive','reply_negative')", (since,))]
    results = [evaluate_email(ctx, e, now, apply) for e in sorted(emails)]
    if apply:
        ctx.store.set_state("follow_through:last_sweep", now.isoformat())
    acted = [r for r in results if (r.get("result") or {}).get("action", "none") != "none"]
    return {"checked": len(results), "teed_up": sum(1 for r in acted if r["result"]["action"] == "tee_up"),
            "notified": sum(1 for r in acted if r["result"]["action"] == "notify_owner"), "results": results}


def open_teeups(ctx, owner: str | None = None, now: datetime | None = None) -> list[dict]:
    ensure_schema(ctx)
    sql, params = "SELECT * FROM teeups WHERE status='open'", []
    if owner:
        sql += " AND owner=?"
        params.append(owner)
    rows = ctx.store.query(sql + " ORDER BY due_at", params)
    n = _now(now).isoformat()
    for r in rows:
        r["overdue"] = bool(r.get("due_at") and r["due_at"] < n)
        r["facts"] = json.loads(r.get("facts") or "{}")
        r["approvals"] = json.loads(r.get("approvals") or "[]")
    return rows


def resolve_teeup(ctx, email: str, outcome: str, now: datetime | None = None) -> dict:
    """The AE acted (called, emailed, booked, disqualified). Closes the tee-up and its local task."""
    ensure_schema(ctx)
    email = (email or "").strip().lower()
    rows = ctx.store.query("SELECT id, task_id FROM teeups WHERE email=? AND status='open'", (email,))
    for r in rows:
        ctx.store.execute("UPDATE teeups SET status=?, resolved_at=?, outcome=? WHERE id=?",
                          ("actioned", _now(now).isoformat(), outcome, r["id"]))
        if r.get("task_id"):
            ctx.store.upsert("tasks", {"id": r["task_id"], "status": "done"})
    return {"email": email, "closed": len(rows), "outcome": outcome}


def stamp() -> str:
    return now_iso()
