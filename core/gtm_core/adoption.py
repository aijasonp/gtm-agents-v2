"""Rep adoption: who on the sales team actually uses the agents, and whether users win more.

Usage comes from two places, both already in the customer's database:
  approvals     every approval decision a named person made (decided_by), so history counts from day one
  rep_activity  everything else a rep does with the agents: Slack questions, push-button runs, tool calls from
                an MCP client or a browser extension (`record`)
Automatic decisions (autonomy:*, operator, api tokens with no person) never count as a rep using the agents.

Actors are matched to reps by Slack id (configured, or cached after the bot looked it up by email), email or name
from config/company.yaml `team.owners`.
Every number here is computed in code; nothing is estimated.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .pipeline import is_lost, is_won, parse_dt
from .store import Store, now_iso

SCHEMA = """CREATE TABLE IF NOT EXISTS rep_activity (
  id {AUTOID}, actor TEXT NOT NULL, action TEXT NOT NULL, agent TEXT, ref TEXT, at TEXT NOT NULL)"""
INDEX = "CREATE INDEX IF NOT EXISTS ix_rep_activity_at ON rep_activity(at)"


def ensure(store: Store) -> None:
    if not getattr(store, "_adoption_schema", False):
        autoid = "INTEGER PRIMARY KEY AUTOINCREMENT" if store.kind == "sqlite" else "BIGSERIAL PRIMARY KEY"
        store.execute(SCHEMA.replace("{AUTOID}", autoid))
        store.execute(INDEX)
        store._adoption_schema = True


def record(store: Store, actor: str, action: str, agent: str = "", ref: str = "", at: str | None = None) -> None:
    """Log one rep action. Never raises: adoption tracking must not break the work it measures."""
    try:
        if not actor or _is_system(actor):
            return
        ensure(store)
        store.insert("INSERT INTO rep_activity (actor, action, agent, ref, at) VALUES (?,?,?,?,?)",
                     (actor, action, agent, str(ref)[:200], at or now_iso()))
    except Exception:
        pass


def _is_system(actor: str) -> bool:
    a = (actor or "").strip().lower()
    return a in ("operator", "system", "scheduler", "") or a.startswith("autonomy:")


class Roster:
    """Maps actor strings (slack:U012, api:sam@x, Sam Rivera) to rep names."""

    def __init__(self, owners: list[dict]):
        self.names = [o["name"] for o in owners if o.get("name")]
        self._map: dict[str, str] = {}
        for o in owners:
            for k in ("name", "email", "slack_id"):
                if o.get(k):
                    self._map[str(o[k]).strip().lower()] = o["name"]

    def rep(self, actor: str | None) -> str | None:
        if not actor or _is_system(actor):
            return None
        a = actor.strip().lower()
        if a in self._map:
            return self._map[a]
        if ":" in a:
            return self._map.get(a.split(":", 1)[1].strip())
        return None


def events(store: Store, roster: Roster, start: datetime, end: datetime) -> list[tuple[str, str, datetime]]:
    """(rep, action, at) for every rep action in [start, end)."""
    ensure(store)
    out = []
    for r in store.query("SELECT decided_by, decided_at, action FROM approvals WHERE decided_by IS NOT NULL"):
        at, rep = parse_dt(r.get("decided_at")), roster.rep(r.get("decided_by"))
        if rep and at and start <= at < end:
            out.append((rep, "approval:" + (r.get("action") or ""), at))
    for r in store.query("SELECT actor, action, at FROM rep_activity"):
        at, rep = parse_dt(r.get("at")), roster.rep(r.get("actor"))
        if rep and at and start <= at < end:
            out.append((rep, r.get("action") or "", at))
    return out


def counts(evts, start: datetime, end: datetime) -> dict[str, int]:
    c: dict[str, int] = {}
    for rep, _, at in evts:
        if start <= at < end:
            c[rep] = c.get(rep, 0) + 1
    return c


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def report(store: Store, owners: list[dict], deals: list[dict], now: datetime, window_days: int = 30,
           min_actions: int = 3, lookback_days: int = 90, min_cohort: int = 5) -> dict:
    """Adoption, retention and the win-rate gap between reps who used the agents and reps who did not.

    active          a rep with at least `min_actions` actions in the window
    adoption        active reps / reps on the team (current window)
    retention       reps active in both the previous and the current window / reps active in the previous one
    cohorts         each deal closed (won or lost) in the lookback goes to `users` when its owner was active in the
                    `window_days` before its close date, else to `non_users`; win rate by count in each cohort
    """
    owners = [{**o, "slack_id": o.get("slack_id") or (store.get_state(f"slack_id:{o['email'].lower()}") if o.get("email")
                                                       else None)} for o in owners]
    roster = Roster(owners)
    w = timedelta(days=window_days)
    earliest = now - max(timedelta(days=lookback_days) + w, 2 * w)
    evts = events(store, roster, earliest, now + timedelta(seconds=1))
    cur = counts(evts, now - w, now + timedelta(seconds=1))
    prev = counts(evts, now - 2 * w, now - w)
    active_now = {r for r, n in cur.items() if n >= min_actions}
    active_prev = {r for r, n in prev.items() if n >= min_actions}
    team = roster.names
    reps = [{"rep": r, "actions": cur.get(r, 0), "previous_actions": prev.get(r, 0), "active": r in active_now,
             "was_active": r in active_prev} for r in team]
    reps.sort(key=lambda x: (-x["actions"], x["rep"]))

    by_rep_events: dict[str, list[datetime]] = {}
    for rep, _, at in evts:
        by_rep_events.setdefault(rep, []).append(at)
    name_of = {n.lower(): n for n in team}
    cohorts = {"users": {"won": 0, "lost": 0, "won_amount": 0.0}, "non_users": {"won": 0, "lost": 0, "won_amount": 0.0}}
    closers: dict[str, bool] = {}
    for d in deals:
        if not (is_won(d) or is_lost(d)):
            continue
        cd = parse_dt(d.get("close_date"))
        if not cd or not (now - timedelta(days=lookback_days) <= cd <= now):
            continue
        owner = name_of.get((d.get("owner") or "").strip().lower())
        if not owner:
            continue
        end = cd + timedelta(days=1)
        n = sum(1 for at in by_rep_events.get(owner, []) if end - w <= at < end)
        side = "users" if n >= min_actions else "non_users"
        c = cohorts[side]
        if is_won(d):
            c["won"] += 1
            c["won_amount"] = round(c["won_amount"] + float(d.get("amount") or 0), 2)
            closers[owner] = closers.get(owner, False) or side == "users"
        else:
            c["lost"] += 1
    for c in cohorts.values():
        c["closed"] = c["won"] + c["lost"]
        c["win_rate"] = _rate(c["won"], c["closed"])
    u, nu = cohorts["users"]["win_rate"], cohorts["non_users"]["win_rate"]
    lift = round((u - nu) * 100, 1) if u is not None and nu is not None else None
    small = min(cohorts["users"]["closed"], cohorts["non_users"]["closed"]) < min_cohort
    return {
        "as_of": now.replace(microsecond=0).isoformat(), "window_days": window_days, "min_actions": min_actions,
        "team": len(team), "active": len(active_now), "adoption": _rate(len(active_now), len(team)),
        "previously_active": len(active_prev), "retained": len(active_now & active_prev),
        "retention": _rate(len(active_now & active_prev), len(active_prev)),
        "actions": sum(cur.get(r, 0) for r in team), "reps": reps,
        "lookback_days": lookback_days, "cohorts": cohorts, "win_rate_lift_pts": lift,
        "small_sample": small, "min_cohort": min_cohort,
        "closers": len(closers), "closers_using": sum(1 for v in closers.values() if v),
    }


def format_report(r: dict) -> str:
    pct = lambda v: f"{round(v * 100)}%" if v is not None else "n/a"
    c = r["cohorts"]
    lines = [f"Adoption (last {r['window_days']} days, active = {r['min_actions']}+ actions): "
             f"{r['active']} of {r['team']} reps ({pct(r['adoption'])}) | retention {pct(r['retention'])} "
             f"({r['retained']} of {r['previously_active']}) | {r['actions']} actions",
             f"Win rate, deals closed in {r['lookback_days']} days: users {pct(c['users']['win_rate'])} "
             f"({c['users']['won']}/{c['users']['closed']}) vs non-users {pct(c['non_users']['win_rate'])} "
             f"({c['non_users']['won']}/{c['non_users']['closed']})"
             + (f" | lift {'+' if r['win_rate_lift_pts'] > 0 else ''}{r['win_rate_lift_pts']} pts"
                if r["win_rate_lift_pts"] is not None else "")
             + (f" | sample under {r['min_cohort']} deals in a cohort" if r["small_sample"] else ""),
             f"Closers using the agents: {r['closers_using']} of {r['closers']}"]
    idle = [x["rep"] for x in r["reps"] if not x["active"]]
    if idle:
        lines.append("Not active: " + ", ".join(idle))
    return "\n".join(lines)
