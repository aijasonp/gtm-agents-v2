"""Slack commands that never touch a model, so they answer instantly and work when the model is down.

  help                         what the bot understands
  stop [scope ...] [-- reason] STOP everything, or only some scopes (an agent id, an action, or a motion such
                               as cold). Any allowed user may stop: stopping only reduces risk.
  resume                       lift STOP (admins only)
  status                       STOP state, approvals waiting, jobs run and failed in the last 24 hours,
                               failing health checks
  approvals [agent]            what is waiting for approval
  approve 12 [13 ...]          approve (approvers only)
  reject 12 [13 ...]           reject (approvers only)
  run <agent> <job>            run a job now (admins only). STOP still holds it.

Who is who (Slack user ids, comma-separated):
  GTM_SLACK_APPROVERS  may approve and reject
  GTM_SLACK_ADMINS     may resume and run jobs (defaults to the approvers)
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

HELP = """*Commands* (instant, no model):
- `status`: STOP state, approvals waiting, jobs in the last 24 hours, failing checks
- `approvals [agent]`: what is waiting
- `approve 12` / `reject 12, 13`: decide (approvers)
- `stop` or `stop cold` or `stop icp-outbound -- reason`: pause everything or one scope (anyone allowed)
- `resume`: lift STOP (admins)
- `run <agent> <job>`: run a job now (admins)
Anything else is a question for the agents, for example "what is stalled in Stage 1 for Sam?"."""

CMD = re.compile(r"^\s*(help|status|approvals|approve|reject|stop|resume|run)\b(.*)$", re.I | re.S)


def _ids(env: str) -> set[str]:
    return {u.strip() for u in os.environ.get(env, "").split(",") if u.strip()}


def approvers() -> set[str]:
    return _ids("GTM_SLACK_APPROVERS")


def admins() -> set[str]:
    return _ids("GTM_SLACK_ADMINS") or approvers()


def is_command(text: str) -> bool:
    m = CMD.match(text or "")
    if not m:
        return False
    verb, rest = m.group(1).lower(), m.group(2).strip()
    if verb in ("approve", "reject"):
        return bool(re.fullmatch(r"#?\d+(?:\s*[, ]\s*#?\d+)*", rest))
    if verb == "run":
        return len(rest.split()) == 2
    if verb in ("help", "status", "resume"):
        return rest == ""
    if verb == "approvals":
        return len(rest.split()) <= 1
    return True  # stop with any scope or reason


def handle(text: str, user: str, store, settings=None, manifests: dict | None = None, runner=None) -> str | None:
    """Reply for a command, or None when the text is not a command (the model answers it)."""
    if not is_command(text):
        return None
    m = CMD.match(text)
    verb, rest = m.group(1).lower(), m.group(2).strip()
    if verb == "help":
        return HELP
    if verb in ("approve", "reject"):
        return _decide(store, user, verb == "approve", rest)
    if verb == "approvals":
        return _approvals(store, rest or None)
    if verb == "stop":
        return _stop(store, user, rest)
    if verb == "resume":
        if user not in admins():
            return "Only admins can resume. Ask an admin to add your Slack ID to GTM_SLACK_ADMINS."
        from .autonomy import resume
        r = resume(store, f"slack:{user}")
        if r.get("still_stopped_by"):
            return f"STOP lifted here, but it is still on from {r['still_stopped_by']}. Clear that too."
        return "Resumed. Jobs and approved actions run again." if r.get("resumed") else "STOP was not on."
    if verb == "status":
        return _status(store, settings, manifests)
    if verb == "run":
        if user not in admins():
            return "Only admins can run jobs. Ask an admin to add your Slack ID to GTM_SLACK_ADMINS."
        agent, job = rest.split()
        return _run(settings, manifests, agent, job, runner)
    return None


def _decide(store, user: str, approve: bool, rest: str) -> str:
    if user not in approvers():
        return "Only approvers can do that. Ask an admin to add your Slack ID to GTM_SLACK_APPROVERS."
    from .approvals import Approvals
    out = []
    for rid in [int(x) for x in re.findall(r"\d+", rest)]:
        try:
            Approvals(store, "core").decide(rid, approve, by=f"slack:{user}")
            out.append(f"#{rid} {'approved' if approve else 'rejected'}")
        except (KeyError, ValueError) as e:
            out.append(f"#{rid}: {e}")
    return "; ".join(out) + ". Approved actions run on the next scheduled execute."


def _approvals(store, agent: str | None, limit: int = 20) -> str:
    sql, params = "SELECT id, agent, action, payload, requested_at FROM approvals WHERE status='pending'", []
    if agent:
        sql += " AND agent=?"
        params.append(agent)
    rows = store.query(sql + " ORDER BY id LIMIT ?", (*params, limit + 1))
    if not rows:
        return "Nothing is waiting for approval" + (f" from {agent}." if agent else ".")
    lines = [f"*{min(len(rows), limit)} waiting*" + (" (showing the first 20)" if len(rows) > limit else "")]
    for r in rows[:limit]:
        try:
            p = json.loads(r["payload"] or "{}")
        except json.JSONDecodeError:
            p = {}
        summary = p.get("_summary") or p.get("summary") or ((p.get("contact") or {}).get("email")) or ""
        lines.append(f"#{r['id']} {r['agent']}: {r['action']}" + (f" ({str(summary)[:90]})" if summary else ""))
    lines.append("Reply `approve <id>` or `reject <id>`.")
    return "\n".join(lines)


def _stop(store, user: str, rest: str) -> str:
    reason = ""
    if "--" in rest:
        rest, reason = (x.strip() for x in rest.split("--", 1))
    scopes = [s for s in re.split(r"[,\s]+", rest) if s] or None
    from .autonomy import stop
    st = stop(store, f"slack:{user}", reason, scopes)
    what = "everything" if st["scopes"] == ["all"] else ", ".join(st["scopes"])
    return f"STOP is on for {what}. Sends, CRM writes and jobs in scope are held. `resume` lifts it (admins)."


def _status(store, settings, manifests) -> str:
    from .autonomy import current
    lines = []
    try:
        st = current().stop_state(store)
    except Exception as e:
        st = {"scopes": ["unknown"], "source": f"unreadable ({str(e)[:80]})"}
    lines.append(f"STOP: on for {', '.join(st['scopes'])} ({st['source']})" if st else "STOP: off")
    n = store.one("SELECT COUNT(*) AS n FROM approvals WHERE status='pending'")
    lines.append(f"Approvals waiting: {n['n'] if n else 0}")
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    runs = store.query("SELECT status, COUNT(*) AS n FROM runs WHERE started_at>=? GROUP BY status", (since,))
    by = {r["status"]: r["n"] for r in runs}
    lines.append(f"Jobs, last 24h: {by.get('ok', 0)} ok, {by.get('failed', 0)} failed, {by.get('running', 0)} running")
    failed = store.query("SELECT agent, job, finished_at FROM runs WHERE status='failed' AND started_at>=? "
                         "ORDER BY finished_at DESC LIMIT 5", (since,))
    for f in failed:
        lines.append(f"- failed: {f['agent']}.{f['job']} at {str(f['finished_at'])[:16]}")
    if manifests and "ops-monitor" in manifests and settings is not None:
        try:
            from .agents import Context, load_module
            ctx = Context.build(settings, manifests["ops-monitor"], store=store)
            rep = load_module(ctx.manifest, "engine").report(ctx)
            bad = rep.get("problems") or []
            if bad:
                lines.append(f"Health checks needing attention: {len(bad)}")
                lines += [f"- {c.get('status')}: {c.get('detail', c.get('check'))}"[:160] for c in bad[:5]]
            else:
                lines.append("Health checks: all ok")
        except Exception as e:
            lines.append(f"Health checks: could not run ({type(e).__name__})")
    return "\n".join(lines)


def _run(settings, manifests, agent: str, job: str, runner=None) -> str:
    if not manifests or agent not in manifests:
        return f"No agent named {agent}. Agents: {', '.join(sorted(manifests or {}))}"
    jobs = [j["name"] for j in manifests[agent].jobs]
    if job not in jobs:
        return f"{agent} has no job {job}. Jobs: {', '.join(jobs) or 'none'}"
    if runner is None:
        from .scheduler import run_job as runner
    try:
        res = runner(settings, manifests[agent], job)
    except Exception as e:
        return f"{agent}.{job} failed: {type(e).__name__}: {str(e)[:200]}"
    if res.get("skipped"):
        return f"{agent}.{job} held: {res['skipped']}"
    brief = {k: v for k, v in res.items() if isinstance(v, (int, float, str)) and len(str(v)) < 80}
    return f"{agent}.{job} done" + (": " + ", ".join(f"{k} {v}" for k, v in list(brief.items())[:8]) if brief else ".")
