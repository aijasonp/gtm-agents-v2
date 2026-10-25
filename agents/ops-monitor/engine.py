"""Ops Monitor engine: runtime health from the store and the job schedules. No model calls."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from croniter import croniter

from gtm_core import agents as agents_mod
from gtm_core import pipeline

STATE_KEY = "ops_monitor:status"
RANK = {"ok": 0, "warn": 1, "fail": 2}


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def _now(now):
    return now or datetime.now(timezone.utc)


def _dt(v):
    return pipeline.parse_dt(v)


def _ago(now: datetime, v) -> str:
    d = _dt(v)
    if d is None:
        return "unknown"
    mins = int((now - d).total_seconds() // 60)
    if mins < 90:
        return f"{mins} min ago"
    if mins < 60 * 48:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} days ago"


def _check(cid, check, status, detail, agent=None, **extra) -> dict:
    return {"id": cid, "check": check, "agent": agent, "status": status, "detail": detail, **extra}


def manifests_for(ctx, manifests=None) -> dict:
    return manifests if manifests is not None else agents_mod.discover(ctx.settings.agents_dir)


# ---------- jobs ----------
def job_rows(ctx, agent: str, job: str) -> list[dict]:
    return ctx.store.query("SELECT * FROM runs WHERE agent=? AND job=? ORDER BY started_at DESC", (agent, job))


def job_health(ctx, m, j: dict, now: datetime) -> list[dict]:
    grace = timedelta(minutes=int(cfg(ctx, "grace_minutes", 30)))
    due = croniter(j["cron"], now - grace).get_prev(datetime)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    nxt = croniter(j["cron"], due).get_next(datetime)
    nxt = nxt if nxt.tzinfo else nxt.replace(tzinfo=timezone.utc)
    interval = nxt - due
    rows = job_rows(ctx, m.id, j["name"])
    ok = [r for r in rows if r["status"] == "ok"]
    cid = f"job:{m.id}:{j['name']}"
    out = []
    if not rows:
        out.append(_check(cid + ":cadence", "job cadence", "warn", f"{m.id}.{j['name']} has never run (expected by {due.isoformat()[:16]})",
                          m.id, job=j["name"]))
    else:
        last_ok = _dt(ok[0]["started_at"]) if ok else None
        if last_ok and last_ok >= due - timedelta(minutes=1):
            out.append(_check(cid + ":cadence", "job cadence", "ok", f"last ok run {_ago(now, ok[0]['started_at'])}", m.id, job=j["name"]))
        else:
            missed = last_ok is None or (due - last_ok) >= interval
            status = "fail" if missed and (last_ok is None or now - last_ok >= 2 * interval + grace) else "warn"
            out.append(_check(cid + ":cadence", "job cadence", status,
                              f"{m.id}.{j['name']} missed its run due {due.isoformat()[:16]}; last ok "
                              f"{_ago(now, ok[0]['started_at']) if ok else 'never'}", m.id, job=j["name"]))
    fails = 0
    for r in rows:
        if r["status"] == "failed":
            fails += 1
        elif r["status"] == "ok":
            break
    if fails:
        err = (json.loads(rows[0].get("stats") or "{}") or {}).get("error", "") if rows[0]["status"] == "failed" else ""
        out.append(_check(cid + ":failures", "job failures", "fail" if fails >= 3 else "warn",
                          f"{m.id}.{j['name']} failed {fails} time(s) in a row" + (f": {err[:160]}" if err else ""),
                          m.id, job=j["name"], consecutive_failures=fails))
    else:
        out.append(_check(cid + ":failures", "job failures", "ok", "no recent failures", m.id, job=j["name"]))
    stuck_after = timedelta(minutes=int(cfg(ctx, "stuck_run_minutes", 60)))
    running = [r for r in rows if r["status"] == "running" and _dt(r["started_at"]) and now - _dt(r["started_at"]) > stuck_after]
    out.append(_check(cid + ":stuck", "stuck runs", "warn" if running else "ok",
                      f"run {running[0]['id']} still running since {_ago(now, running[0]['started_at'])}" if running else "none",
                      m.id, job=j["name"]))
    return out


# ---------- approvals, handoffs, budgets, spend, gate ----------
def approval_checks(ctx, now: datetime) -> list[dict]:
    out = []
    ex_min = int(cfg(ctx, "executing_minutes", 15))
    rows = ctx.store.query("SELECT id, agent, action, status, requested_at, decided_at FROM approvals "
                           "WHERE status IN ('executing','approved','pending')")
    executing = [r for r in rows if r["status"] == "executing" and _dt(r["decided_at"] or r["requested_at"])
                 and now - _dt(r["decided_at"] or r["requested_at"]) > timedelta(minutes=ex_min)]
    approved = [r for r in rows if r["status"] == "approved" and _dt(r["decided_at"] or r["requested_at"])
                and now - _dt(r["decided_at"] or r["requested_at"]) > timedelta(hours=float(cfg(ctx, "approved_hours", 2)))]
    pending = [r for r in rows if r["status"] == "pending" and _dt(r["requested_at"])
               and now - _dt(r["requested_at"]) > timedelta(hours=float(cfg(ctx, "pending_hours", 24)))]
    out.append(_check("approvals:executing", "approvals executing", "fail" if executing else "ok",
                      f"{len(executing)} action(s) stuck executing: " + ", ".join(f"#{r['id']} {r['action']}" for r in executing[:5])
                      if executing else "none", ids=[r["id"] for r in executing]))
    out.append(_check("approvals:approved", "approvals approved, not run", "warn" if approved else "ok",
                      f"{len(approved)} approved but not executed: " + ", ".join(f"#{r['id']} {r['action']}" for r in approved[:5])
                      if approved else "none", ids=[r["id"] for r in approved]))
    by_agent: dict[str, int] = {}
    for r in pending:
        by_agent[r["agent"]] = by_agent.get(r["agent"], 0) + 1
    out.append(_check("approvals:backlog", "approval backlog", "warn" if pending else "ok",
                      f"{len(pending)} pending over {cfg(ctx, 'pending_hours', 24)} h: "
                      + ", ".join(f"{a} {n}" for a, n in sorted(by_agent.items())) if pending else "none", by_agent=by_agent))
    return out


def handoff_checks(ctx, now: datetime) -> list[dict]:
    rows = ctx.store.query("SELECT id, from_agent, to_agent, kind, ref, status, created_at, payload FROM handoffs "
                           "WHERE status IN ('failed','pending','processing')")
    failed = [r for r in rows if r["status"] == "failed"]
    waiting = [r for r in rows if r["status"] in ("pending", "processing") and _dt(r["created_at"])
               and now - _dt(r["created_at"]) > timedelta(hours=float(cfg(ctx, "handoff_hours", 6)))]

    def err(r):
        try:
            return (json.loads(r["payload"] or "{}") or {}).get("_error", "")
        except json.JSONDecodeError:
            return ""
    return [
        _check("handoffs:failed", "handoffs failed", "fail" if failed else "ok",
               f"{len(failed)} failed: " + "; ".join(f"#{r['id']} {r['kind']} -> {r['to_agent']} ({err(r)[:80]})" for r in failed[:5])
               if failed else "none", ids=[r["id"] for r in failed]),
        _check("handoffs:waiting", "handoffs waiting", "warn" if waiting else "ok",
               f"{len(waiting)} waiting over {cfg(ctx, 'handoff_hours', 6)} h: "
               + ", ".join(f"#{r['id']} {r['kind']} -> {r['to_agent']}" for r in waiting[:5]) if waiting else "none",
               ids=[r["id"] for r in waiting]),
    ]


def reply_checks(ctx, now: datetime) -> list[dict]:
    """Replies stuck mid-handling or in error (Reply Desk). Skipped when Reply Desk has never run."""
    try:
        rows = ctx.store.query("SELECT id, status, created_at, reason FROM replies WHERE status IN ('handling','error')")
    except Exception:
        try:  # Postgres aborts the statement; nothing else is open in this autocommit connection
            ctx.store.conn.rollback() if ctx.store.kind == "postgres" else None
        except Exception:
            pass
        return []
    mins = int(cfg(ctx, "reply_handling_minutes", 30))
    stuck = [r for r in rows if r["status"] == "handling" and _dt(r["created_at"])
             and now - _dt(r["created_at"]) > timedelta(minutes=mins)]
    errors = [r for r in rows if r["status"] == "error"]
    return [
        _check("replies:stuck", "replies stuck handling", "warn" if stuck else "ok",
               f"{len(stuck)} stuck over {mins} min: " + ", ".join(r["id"] for r in stuck[:5]) if stuck else "none",
               ids=[r["id"] for r in stuck]),
        _check("replies:error", "replies in error", "fail" if errors else "ok",
               f"{len(errors)} in error: " + "; ".join(f"{r['id']} ({(r.get('reason') or '')[:60]})" for r in errors[:5])
               if errors else "none", ids=[r["id"] for r in errors]),
    ]


def pause_checks(ctx) -> list[dict]:
    rows = ctx.store.query("SELECT key, value FROM state WHERE key LIKE ?", ("paused%",))  # parameter: Postgres-safe
    paused = []
    for r in rows:
        try:
            if json.loads(r["value"]):
                paused.append(r["key"].split(":", 1)[1] if ":" in r["key"] else "whole runtime")
        except json.JSONDecodeError:
            continue
    return [_check("budget:paused", "budget pauses", "fail" if paused else "ok",
                   f"paused: {', '.join(sorted(paused))}" if paused else "none", paused=sorted(paused))]


def spend(ctx, manifests: dict, days: int = 1, now: datetime | None = None) -> list[dict]:
    now = _now(now)
    out = []
    for d in range(days):
        day = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        rows = ctx.store.query("SELECT agent, COALESCE(SUM(input_tokens+output_tokens),0) AS tokens, COALESCE(SUM(usd),0) AS usd, "
                               "COUNT(*) AS calls FROM token_usage WHERE ts LIKE ? GROUP BY agent", (day + "%",))
        for r in rows:
            m = manifests.get(r["agent"])
            budget = int((m.budgets or {}).get("daily_tokens", 0)) if m else 0
            out.append({"day": day, "agent": r["agent"], "tokens": int(r["tokens"]), "usd": round(float(r["usd"]), 4),
                        "calls": int(r["calls"]), "daily_budget": budget or None,
                        "pct_of_budget": round(100 * int(r["tokens"]) / budget, 1) if budget else None})
    return sorted(out, key=lambda r: (r["day"], -r["tokens"]), reverse=False)


def spend_checks(ctx, manifests: dict, now: datetime) -> list[dict]:
    warn = float(cfg(ctx, "spend_warn_pct", 80))
    out = []
    for r in spend(ctx, manifests, 1, now):
        if r["pct_of_budget"] is None:
            continue
        st = "fail" if r["pct_of_budget"] >= 100 else ("warn" if r["pct_of_budget"] >= warn else "ok")
        out.append(_check(f"spend:{r['agent']}", "token spend", st,
                          f"{r['agent']}: {r['tokens']:,} tokens today ({r['pct_of_budget']}% of {r['daily_budget']:,})", r["agent"]))
    return out


def gate_checks(ctx, now: datetime) -> list[dict]:
    since = (now - timedelta(days=7)).replace(microsecond=0).isoformat()
    rows = ctx.store.query("SELECT agent, COUNT(*) AS n, SUM(CASE WHEN gate_passed=0 THEN 1 ELSE 0 END) AS failed FROM drafts "
                           "WHERE gate_passed IS NOT NULL AND created_at>=? GROUP BY agent", (since,))
    out = []
    for r in rows:
        n, f = int(r["n"]), int(r["failed"] or 0)
        rate = round(100 * f / n, 1) if n else 0
        st = "warn" if n >= int(cfg(ctx, "gate_min_drafts", 5)) and rate >= float(cfg(ctx, "gate_fail_warn_pct", 30)) else "ok"
        out.append(_check(f"gate:{r['agent']}", "copy gate failures", st, f"{r['agent']}: {f} of {n} drafts failed the gate this week ({rate}%)",
                          r["agent"], rate=rate))
    return out


def discovery_checks(errors: dict) -> list[dict]:
    return [_check(f"load:{a}", "agent load errors", "fail", f"{a}: {e[:200]}", a) for a, e in sorted(errors.items())] or \
        [_check("load:all", "agent load errors", "ok", "all agents loaded")]


# ---------- report ----------
def report(ctx, now: datetime | None = None, manifests: dict | None = None, discovery_errors: dict | None = None) -> dict:
    now = _now(now)
    ms = manifests_for(ctx, manifests)
    errors = dict(agents_mod.DISCOVERY_ERRORS) if discovery_errors is None else discovery_errors
    checks = []
    for m in ms.values():
        if "persistent" not in (m.editions or []):
            continue
        for j in m.jobs or []:
            try:
                checks += job_health(ctx, m, j, now)
            except (ValueError, KeyError) as e:
                checks.append(_check(f"job:{m.id}:{j.get('name')}:cron", "job cadence", "fail", f"bad cron {j.get('cron')!r}: {e}", m.id))
    checks += approval_checks(ctx, now) + handoff_checks(ctx, now) + reply_checks(ctx, now) + pause_checks(ctx) \
        + spend_checks(ctx, ms, now) \
        + gate_checks(ctx, now) + discovery_checks(errors)
    worst = max((RANK[c["status"]] for c in checks), default=0)
    status = {v: k for k, v in RANK.items()}[worst]
    counts = {s: sum(1 for c in checks if c["status"] == s) for s in RANK}
    return {"as_of": now.replace(microsecond=0).isoformat(), "status": status, "counts": counts, "checks": checks,
            "problems": [c for c in sorted(checks, key=lambda c: -RANK[c["status"]]) if c["status"] != "ok"]}


def changes(ctx, rep: dict) -> dict:
    """New or changed problems and recoveries since the last check. Updates the stored statuses."""
    prev = ctx.store.get_state(STATE_KEY, {}) or {}
    cur = {c["id"]: c["status"] for c in rep["checks"]}
    new = [c for c in rep["problems"] if prev.get(c["id"]) != c["status"]]
    recovered = [cid for cid, st in prev.items() if st != "ok" and cur.get(cid, "ok") == "ok"]
    ctx.store.set_state(STATE_KEY, cur)
    return {"new": new, "recovered": recovered}


def format_alert(ch: dict) -> str:
    lines = []
    if ch["new"]:
        lines.append(f"*Ops Monitor: {len(ch['new'])} problem(s)*")
        lines += [f"- [{c['status'].upper()}] {c['check']}: {c['detail']}" for c in ch["new"]]
    if ch["recovered"]:
        lines.append("Recovered: " + ", ".join(ch["recovered"]))
    return "\n".join(lines)


def run_counts(ctx, now: datetime, hours: int = 24) -> dict:
    since = (now - timedelta(hours=hours)).replace(microsecond=0).isoformat()
    rows = ctx.store.query("SELECT status, COUNT(*) AS n FROM runs WHERE started_at>=? GROUP BY status", (since,))
    return {r["status"]: int(r["n"]) for r in rows}


def format_summary(rep: dict, runs: dict) -> str:
    c = rep["counts"]
    lines = [f"*Ops Monitor daily summary* | status {rep['status'].upper()} | ok {c['ok']}, warn {c['warn']}, fail {c['fail']}",
             f"Runs in the last 24 h: ok {runs.get('ok', 0)}, failed {runs.get('failed', 0)}, running {runs.get('running', 0)}"]
    if rep["problems"]:
        lines += [f"- [{p['status'].upper()}] {p['check']}: {p['detail']}" for p in rep["problems"][:15]]
    else:
        lines.append("All checks ok.")
    return "\n".join(lines)


# ---------- tool helpers ----------
def job_status(ctx, agent: str, now: datetime | None = None, manifests: dict | None = None) -> dict:
    now = _now(now)
    ms = manifests_for(ctx, manifests)
    m = ms.get(agent)
    if not m:
        return {"error": f"unknown agent '{agent}'. Installed: {', '.join(sorted(ms))}"}
    jobs = []
    for j in m.jobs or []:
        rows = job_rows(ctx, m.id, j["name"])
        nxt = croniter(j["cron"], now).get_next(datetime)
        fails = 0
        for r in rows:
            if r["status"] == "failed":
                fails += 1
            elif r["status"] == "ok":
                break
        jobs.append({"job": j["name"], "cron": j["cron"], "last_run": rows[0]["started_at"] if rows else None,
                     "last_status": rows[0]["status"] if rows else "never run",
                     "last_ok": next((r["started_at"] for r in rows if r["status"] == "ok"), None),
                     "consecutive_failures": fails, "next_run": (nxt if nxt.tzinfo else nxt.replace(tzinfo=timezone.utc)).isoformat()})
    return {"agent": agent, "jobs": jobs}


def stuck(ctx, now: datetime | None = None, manifests: dict | None = None) -> dict:
    now = _now(now)
    a = {c["id"]: c for c in approval_checks(ctx, now)}
    h = {c["id"]: c for c in handoff_checks(ctx, now)}
    after = timedelta(minutes=int(cfg(ctx, "stuck_run_minutes", 60)))
    runs = [r for r in ctx.store.query("SELECT id, agent, job, started_at FROM runs WHERE status='running'")
            if _dt(r["started_at"]) and now - _dt(r["started_at"]) > after]
    return {"approvals_executing": a["approvals:executing"]["ids"], "approvals_approved_not_run": a["approvals:approved"]["ids"],
            "approval_backlog": a["approvals:backlog"]["by_agent"], "handoffs_failed": h["handoffs:failed"]["ids"],
            "handoffs_waiting": h["handoffs:waiting"]["ids"], "runs_stuck": runs}
