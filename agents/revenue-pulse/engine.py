"""Revenue Pulse engine: every number computed from the store. The model only writes the summary bullets."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from gtm_core import adoption as adoption_core
from gtm_core import meddpicc, pipeline, profile, writer

STATE_KEY = "revenue_pulse:last"
DEFAULT_ORDER = ["discovery", "qualification", "evaluation", "proposal", "negotiation", "commit"]


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    return yaml.safe_load(open(path).read()) or {}


def stages(ctx) -> dict:
    return _yaml(str(ctx.manifest.path(ctx.manifest.config.get("stages", "skill/references/stage-probabilities.yaml"))))


def stage_key(ctx, stage: str | None) -> str:
    return meddpicc.stage_key(stage, stages(ctx).get("stage_aliases"))


def _now(now):
    return now or datetime.now(timezone.utc)


def quarter_bounds(now: datetime) -> tuple[datetime, datetime]:
    q = (now.month - 1) // 3
    start = datetime(now.year, 3 * q + 1, 1, tzinfo=timezone.utc)
    end = datetime(now.year + (1 if q == 3 else 0), 1 if q == 3 else 3 * q + 4, 1, tzinfo=timezone.utc)
    return start, end


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    end = datetime(now.year + (1 if now.month == 12 else 0), 1 if now.month == 12 else now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def amt(d: dict) -> float:
    try:
        return float(d.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _sum(deals) -> float:
    return round(sum(amt(d) for d in deals), 2)


def weighted(ctx, deals: list[dict]) -> float:
    return pipeline.weighted(deals, stages(ctx).get("probabilities"), stage_key=lambda s: stage_key(ctx, s))


def slip_info(history: list[dict], start: datetime) -> dict | None:
    """Close date now vs at the start of the period. None when it did not move later."""
    snaps = [h for h in history if pipeline.parse_dt(h.get("close_date"))]
    if len(snaps) < 2:
        return None
    before = [h for h in snaps if (pipeline.parse_dt(h.get("snapshot_at")) or start) < start]
    during = [h for h in snaps if (pipeline.parse_dt(h.get("snapshot_at")) or start) >= start]
    if not during:
        return None
    base = before[-1] if before else during[0]
    cur = snaps[-1]
    old, new = pipeline.parse_dt(base["close_date"]), pipeline.parse_dt(cur["close_date"])
    if new > old:
        return {"from": base["close_date"][:10], "to": cur["close_date"][:10], "days": (new - old).days}
    return None


def stage_moves(ctx, history: list[dict], start: datetime) -> list[dict]:
    order = stages(ctx).get("order", DEFAULT_ORDER)
    out = []
    for frm, to, at in pipeline.stage_changes(history):
        if (pipeline.parse_dt(at) or start) < start:
            continue
        a, b = stage_key(ctx, frm), stage_key(ctx, to)
        direction = "forward" if order.index(b) > order.index(a) else ("back" if order.index(b) < order.index(a) else "same")
        if "closed" in (to or "").lower() or "won" in (to or "").lower() or "lost" in (to or "").lower():
            direction = "closed"
        out.append({"from": frm, "to": to, "at": at, "direction": direction})
    return out


def idle_days(d: dict, now: datetime) -> int | None:
    return pipeline.days_since(d.get("last_activity_at") or d.get("stage_entered_at") or d.get("created_at"), now)


def latest_inspections(ctx) -> dict[str, dict]:
    out = {}
    for ins in ctx.store.insights("deal_inspection"):  # newest first
        out.setdefault(ins["key"], {**(ins.get("value") or {}), "observed_at": ins["observed_at"]})
    return out


def risks(ctx, open_deals: list[dict], slipped_ids: set, now: datetime, limit: int = 5) -> list[dict]:
    insp = latest_inspections(ctx)
    out = []
    for d in open_deals:
        i = insp.get(d["id"])
        if i:
            drivers = i.get("flags") or []
            out.append({"deal_id": d["id"], "name": d.get("name"), "owner": d.get("owner"), "amount": amt(d),
                        "risk": int(i.get("risk", 0)), "recommendation": i.get("recommendation"),
                        "why": "; ".join(drivers[:2]), "source": "deal-inspection"})
            continue
        score, why = 0, []
        idle = idle_days(d, now)
        if idle is not None and idle > int(ctx.manifest.config.get("stale_days", 14)):
            score += 30; why.append(f"no activity {idle} days")
        if d["id"] in slipped_ids:
            score += 30; why.append("close date slipped this week")
        tc = pipeline.days_until(d.get("close_date"), now)
        if tc is not None and tc < 0:
            score += 25; why.append("close date passed")
        if not (d.get("next_step") or "").strip():
            score += 15; why.append("no next step")
        out.append({"deal_id": d["id"], "name": d.get("name"), "owner": d.get("owner"), "amount": amt(d),
                    "risk": score, "recommendation": None, "why": "; ".join(why), "source": "rules"})
    out.sort(key=lambda r: (-r["risk"], -r["amount"]))
    return [r for r in out if r["risk"] > 0][:limit]


def pulse(ctx, now: datetime | None = None, period_days: int | None = None, owner: str = "",
          stale_days: int | None = None) -> dict:
    now = _now(now)
    cfg = ctx.manifest.config
    period_days = int(period_days or cfg.get("period_days", 7))
    stale_days = int(stale_days or cfg.get("stale_days", 14))
    start = now - timedelta(days=period_days)
    qs, qe = quarter_bounds(now)
    ms, me = month_bounds(now)

    deals = ctx.store.select("deals")
    if owner:
        deals = [d for d in deals if (d.get("owner") or "").lower() == owner.lower()]
    open_ = [d for d in deals if pipeline.is_open(d)]
    won = [d for d in deals if pipeline.is_won(d)]
    lost = [d for d in deals if pipeline.is_lost(d)]

    quota = float(profile.company(ctx).get("team", {}).get("quarter_quota") or 0) if not owner else 0.0
    won_qtd = _sum(d for d in won if pipeline.in_period(d.get("close_date"), qs, qe))
    remaining = max(quota - won_qtd, 0.0) if quota else None
    q_pipe = _sum(d for d in open_ if (pipeline.parse_dt(d.get("close_date")) or qe) < qe)
    coverage = round(q_pipe / remaining, 2) if remaining else None

    created = [d for d in deals if pipeline.in_period(d.get("created_at"), start, now)]
    won_p = [d for d in won if pipeline.in_period(d.get("close_date"), start, now)]
    lost_p = [d for d in lost if pipeline.in_period(d.get("close_date"), start, now)]
    win_rate = round(len(won_p) / (len(won_p) + len(lost_p)), 2) if (won_p or lost_p) else None

    slipped, moves = [], []
    for d in open_:
        h = ctx.store.deal_history(d["id"])
        s = slip_info(h, start)
        if s:
            slipped.append({"deal_id": d["id"], "name": d.get("name"), "owner": d.get("owner"), "amount": amt(d), **s})
        for mv in stage_moves(ctx, h, start):
            moves.append({"deal_id": d["id"], "name": d.get("name"), **mv})
    slipped.sort(key=lambda s: -s["amount"])

    stale = []
    for d in open_:
        idle = idle_days(d, now)
        if idle is not None and idle > stale_days:
            stale.append({"deal_id": d["id"], "name": d.get("name"), "owner": d.get("owner"), "amount": amt(d),
                          "days_idle": idle, "stage": d.get("stage")})
    stale.sort(key=lambda s: -s["days_idle"])

    closing: dict[str, float] = {}
    for d in open_:
        if pipeline.in_period(d.get("close_date"), ms, me):
            k = (d.get("forecast_category") or "uncategorized").lower()
            closing[k] = round(closing.get(k, 0) + amt(d), 2)

    overdue = {}
    for t in ctx.store.select("tasks", "status=?", ("open",)):
        due = pipeline.parse_dt(t.get("due_at"))
        if due and due < now:
            overdue[t.get("owner") or "Unassigned"] = overdue.get(t.get("owner") or "Unassigned", 0) + 1

    owners = sorted({d.get("owner") or "Unassigned" for d in deals})
    slipped_by = {}
    for s in slipped:
        slipped_by[s["owner"] or "Unassigned"] = slipped_by.get(s["owner"] or "Unassigned", 0) + 1
    by_owner = []
    for o in owners:
        od = [d for d in open_ if (d.get("owner") or "Unassigned") == o]
        by_owner.append({"owner": o, "open_deals": len(od), "open_pipeline": _sum(od), "weighted": weighted(ctx, od),
                         "won_qtd": _sum(d for d in won if (d.get("owner") or "Unassigned") == o
                                         and pipeline.in_period(d.get("close_date"), qs, qe)),
                         "stale": sum(1 for s in stale if (s["owner"] or "Unassigned") == o),
                         "slipped": slipped_by.get(o, 0), "overdue_tasks": overdue.get(o, 0)})
    by_owner.sort(key=lambda r: -r["open_pipeline"])

    out = {
        "as_of": now.replace(microsecond=0).isoformat(), "period_days": period_days, "owner": owner or None,
        "open_deals": len(open_), "open_pipeline": _sum(open_), "weighted_pipeline": weighted(ctx, open_),
        "quarter": {"start": qs.date().isoformat(), "end": qe.date().isoformat(), "quota": quota or None,
                    "won_qtd": won_qtd, "remaining": remaining, "pipeline": q_pipe, "coverage": coverage},
        "created": {"count": len(created), "amount": _sum(created)},
        "won": {"count": len(won_p), "amount": _sum(won_p), "deals": [d.get("name") for d in won_p]},
        "lost": {"count": len(lost_p), "amount": _sum(lost_p), "deals": [d.get("name") for d in lost_p]},
        "win_rate": win_rate,
        "slipped": {"count": len(slipped), "amount": _sum(slipped), "deals": slipped},
        "stage_moves": {"forward": sum(1 for m in moves if m["direction"] == "forward"),
                        "back": sum(1 for m in moves if m["direction"] == "back"), "moves": moves},
        "stale": {"days": stale_days, "count": len(stale), "amount": _sum(stale), "deals": stale},
        "closing_this_month": closing, "overdue_tasks": overdue, "by_owner": by_owner,
        "top_risks": risks(ctx, open_, {s["deal_id"] for s in slipped}, now, int(cfg.get("top_risks", 5))),
    }
    out["wow"] = deltas(out, ctx.store.get_state(STATE_KEY)) if not owner else {}
    return out


WOW_KEYS = {"open_pipeline": lambda p: p["open_pipeline"], "weighted_pipeline": lambda p: p["weighted_pipeline"],
            "coverage": lambda p: p["quarter"]["coverage"], "won_qtd": lambda p: p["quarter"]["won_qtd"],
            "stale_count": lambda p: p["stale"]["count"]}


def snapshot(p: dict) -> dict:
    return {"as_of": p["as_of"], **{k: f(p) for k, f in WOW_KEYS.items()}}


def deltas(p: dict, prev: dict | None) -> dict:
    if not prev:
        return {}
    out = {}
    for k, f in WOW_KEYS.items():
        cur, old = f(p), prev.get(k)
        if cur is not None and old is not None:
            out[k] = round(cur - old, 2)
    out["since"] = prev.get("as_of")
    return out


def money(v) -> str:
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _delta(v) -> str:
    if v is None:
        return ""
    return f" ({'+' if v >= 0 else '-'}${abs(v):,.0f})"


def fallback_summary(p: dict) -> str:
    q = p["quarter"]
    cov = "quota met" if q["quota"] and not q["remaining"] else (f"{q['coverage']}x coverage" if q["coverage"] is not None else "no quota set")
    b = [f"- Open pipeline {money(p['open_pipeline'])}, weighted {money(p['weighted_pipeline'])}; {cov} on {money(q['remaining'])} remaining.",
         f"- This week: {p['created']['count']} created, {p['won']['count']} won ({money(p['won']['amount'])}), "
         f"{p['lost']['count']} lost ({money(p['lost']['amount'])}).",
         f"- {p['slipped']['count']} deals slipped ({money(p['slipped']['amount'])}); {p['stale']['count']} stale over {p['stale']['days']} days."]
    if p["top_risks"]:
        r = p["top_risks"][0]
        b.append(f"- Biggest risk: {r['name']} ({r['owner']}), risk {r['risk']}: {r['why'] or 'see Deal Inspection'}.")
    else:
        b.append("- No open deals flagged at risk.")
    top = p["by_owner"][0] if p["by_owner"] else None
    od = sum(p["overdue_tasks"].values())
    b.append(f"- {od} overdue tasks across the team" + (f"; largest book: {top['owner']} at {money(top['open_pipeline'])}." if top else "."))
    return "\n".join(b)


def summary(ctx, p: dict) -> tuple[str, str]:
    facts = {k: p[k] for k in ("open_pipeline", "weighted_pipeline", "quarter", "created", "won", "lost", "win_rate",
                               "wow", "closing_this_month", "overdue_tasks")}
    facts["slipped"] = {"count": p["slipped"]["count"], "amount": p["slipped"]["amount"],
                        "deals": [{k: s[k] for k in ("name", "owner", "amount", "days")} for s in p["slipped"]["deals"][:5]]}
    facts["stale"] = {"count": p["stale"]["count"], "amount": p["stale"]["amount"]}
    facts["top_risks"] = p["top_risks"]
    facts["by_owner"] = p["by_owner"]
    return writer.narrate(ctx, "Write exactly 5 bullets (start each with '- ') summarizing this week's revenue position "
                          "for sales leadership: where we stand, what changed, the biggest risk, and the one or two "
                          "actions that matter most. Use only the numbers given, formatted as given.",
                          facts, fallback_summary(p), max_words=140)


def format_pulse(p: dict, summary_text: str = "") -> str:
    q, w = p["quarter"], p.get("wow") or {}
    when = datetime.fromisoformat(p["as_of"]).strftime("%b %d").replace(" 0", " ")
    cov = "quota met" if q["quota"] and not q["remaining"] else (f"{q['coverage']}x" if q["coverage"] is not None else "n/a")
    lines = [f"*Revenue Pulse | week ending {when}*" + (f" | {p['owner']}" if p.get("owner") else ""),
             f"Pipeline: {money(p['open_pipeline'])} open{_delta(w.get('open_pipeline'))} | weighted "
             f"{money(p['weighted_pipeline'])}{_delta(w.get('weighted_pipeline'))}"]
    if q["quota"]:
        lines.append(f"Quarter: won {money(q['won_qtd'])} of {money(q['quota'])} | remaining {money(q['remaining'])} | coverage {cov}")
    wr = f"{int(round(p['win_rate'] * 100))}%" if p["win_rate"] is not None else "n/a"
    lines.append(f"This week: created {p['created']['count']} ({money(p['created']['amount'])}) | won {p['won']['count']} "
                 f"({money(p['won']['amount'])}) | lost {p['lost']['count']} ({money(p['lost']['amount'])}) | win rate {wr}")
    if p["slipped"]["count"]:
        lines.append(f"Slipped {p['slipped']['count']} ({money(p['slipped']['amount'])}): "
                     + "; ".join(f"{s['name']} +{s['days']}d" for s in p["slipped"]["deals"][:3]))
    else:
        lines.append("Slipped: none")
    lines.append(f"Stage moves: {p['stage_moves']['forward']} forward, {p['stage_moves']['back']} back | "
                 f"Stale over {p['stale']['days']} days: {p['stale']['count']} ({money(p['stale']['amount'])})")
    if p["closing_this_month"]:
        lines.append("Closing this month: " + ", ".join(f"{k} {money(v)}" for k, v in sorted(p["closing_this_month"].items())))
    if p["top_risks"]:
        lines.append("Top risks:")
        lines += [f"{i}. {r['name']} ({r['owner']}) risk {r['risk']}" + (f": {r['why']}" if r["why"] else "")
                  for i, r in enumerate(p["top_risks"], 1)]
    if p["by_owner"] and not p.get("owner"):
        lines.append("By owner:")
        lines += [f"- {o['owner']}: open {money(o['open_pipeline'])} | weighted {money(o['weighted'])} | won QTD "
                  f"{money(o['won_qtd'])} | stale {o['stale']} | slipped {o['slipped']} | overdue tasks {o['overdue_tasks']}"
                  for o in p["by_owner"]]
    if p.get("adoption"):
        lines += ["Agent adoption:", adoption_core.format_report(p["adoption"])]
    if summary_text:
        lines += ["Summary:", summary_text]
    return "\n".join(lines)


# ---------- adoption: who uses the agents, and do users win more ----------
def adoption(ctx, now: datetime | None = None, **overrides) -> dict:
    """Rep adoption, retention and user vs non-user win rate (gtm_core.adoption). Settings from `adoption` in
    agent.yaml, overridable per call."""
    cfg = {**{"window_days": 30, "min_actions": 3, "lookback_days": 90, "min_cohort": 5},
           **(ctx.manifest.config.get("adoption") or {}), **{k: int(v) for k, v in overrides.items() if v}}
    owners = (profile.company(ctx).get("team") or {}).get("owners") or []
    return adoption_core.report(ctx.store, owners, ctx.store.select("deals"), _now(now), **cfg)


# ---------- daily GTM report: the whole funnel, yesterday ----------
def _count(ctx, sql: str, params=()) -> int:
    r = ctx.store.one(sql, params)
    return int(r["n"] or 0) if r else 0


def daily(ctx, now: datetime | None = None, days: int = 1) -> dict:
    """Top to bottom for the last `days` (default yesterday's 24 hours): leads, signals, new tier A accounts,
    outbound drafted and sent, email engagement (human opens), meetings held, deals created, moved, won, lost,
    and what is waiting on a human. Every number comes from the store."""
    from gtm_core import engagement
    now = _now(now)
    start = now - timedelta(days=days)
    s, e = start.isoformat(), now.isoformat()
    leads = ctx.store.select("leads", "received_at>=? AND received_at<?", (s, e))
    by_src: dict[str, int] = {}
    for l in leads:
        by_src[l.get("source") or "unknown"] = by_src.get(l.get("source") or "unknown", 0) + 1
    signals = _count(ctx, "SELECT COUNT(*) AS n FROM signals WHERE created_at>=? AND created_at<?", (s, e))
    # Tier A now that were not tier A in the previous sweep
    runs = ctx.store.query("SELECT DISTINCT run_id, MAX(created_at) AS at FROM scores GROUP BY run_id ORDER BY at DESC LIMIT 2")
    new_a = []
    if runs:
        cur = {r["account_id"]: r["tier"] for r in ctx.store.query("SELECT account_id, tier FROM scores WHERE run_id=?", (runs[0]["run_id"],))}
        prev = {r["account_id"]: r["tier"] for r in ctx.store.query("SELECT account_id, tier FROM scores WHERE run_id=?", (runs[1]["run_id"],))} if len(runs) > 1 else {}
        if runs[0]["at"] >= s:
            new_a = sorted(a for a, t in cur.items() if t == "A" and prev.get(a) != "A")
    drafted = _count(ctx, "SELECT COUNT(*) AS n FROM drafts WHERE kind='first_touch' AND created_at>=? AND created_at<?", (s, e))
    ev = ctx.store.query("SELECT event, machine, COUNT(*) AS n FROM email_events WHERE occurred_at>=? AND occurred_at<? "
                         "GROUP BY event, machine", (s, e))
    evc: dict[str, int] = {}
    for r in ev:
        if r["event"] == "open" and r["machine"]:
            evc["machine_open"] = evc.get("machine_open", 0) + r["n"]
        else:
            evc[r["event"]] = evc.get(r["event"], 0) + r["n"]
    week = engagement.rates(engagement.threads(ctx.store, (now - timedelta(days=7)).isoformat()))
    meetings = _count(ctx, "SELECT COUNT(*) AS n FROM meetings WHERE started_at>=? AND started_at<?", (s, e))
    deals = ctx.store.select("deals")
    created = [d for d in deals if pipeline.in_period(d.get("created_at"), start, now)]
    def closed_in(v) -> bool:  # close dates are usually date-only: compare by calendar day
        cd = pipeline.parse_dt(v)
        return cd is not None and start.date() <= cd.date() < now.date() if len(str(v or "")) <= 10 else \
            pipeline.in_period(v, start, now)
    won = [d for d in deals if pipeline.is_won(d) and closed_in(d.get("close_date"))]
    lost = [d for d in deals if pipeline.is_lost(d) and closed_in(d.get("close_date"))]
    moves = []
    for d in deals:
        if pipeline.is_open(d):
            moves += [{"name": d.get("name"), **m} for m in stage_moves(ctx, ctx.store.deal_history(d["id"]), start)]
    pending = ctx.store.query("SELECT agent, COUNT(*) AS n FROM approvals WHERE status='pending' GROUP BY agent")
    return {"from": s, "to": e,
            "leads": {"count": len(leads), "by_source": by_src},
            "signals_added": signals, "new_tier_a": new_a,
            "outbound": {"sequences_drafted": drafted, "sent": evc.get("sent", 0), "human_opens": evc.get("open", 0),
                         "machine_opens": evc.get("machine_open", 0), "clicks": evc.get("click", 0),
                         "replies": evc.get("reply", 0) + evc.get("reply_positive", 0) + evc.get("reply_negative", 0),
                         "positive_replies": evc.get("reply_positive", 0), "bounces": evc.get("bounce", 0),
                         "unsubscribes": evc.get("unsubscribe", 0)},
            "email_7d": week,
            "meetings_held": meetings,
            "deals": {"created": {"count": len(created), "amount": _sum(created)},
                      "won": {"count": len(won), "amount": _sum(won), "deals": [d.get("name") for d in won]},
                      "lost": {"count": len(lost), "amount": _sum(lost), "deals": [d.get("name") for d in lost]},
                      "stage_moves": {"forward": sum(1 for m in moves if m["direction"] == "forward"),
                                      "back": sum(1 for m in moves if m["direction"] == "back")}},
            "approvals_pending": {r["agent"]: r["n"] for r in pending}}


def format_daily(r: dict) -> str:
    o, d, w = r["outbound"], r["deals"], r["email_7d"]
    day = r["to"][:10]
    rate = (f" | 7-day: {w['open_rate']:.0%} open, {w['reply_rate']:.0%} reply over {w['sends']} sends"
            if w["sends"] else "")
    lines = [f"*Daily GTM report* | {day}",
             f"Leads: {r['leads']['count']}" + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(r['leads']['by_source'].items())) + ")"
                                                 if r['leads']['by_source'] else ""),
             f"Signals: {r['signals_added']} | New tier A: {', '.join(r['new_tier_a']) or 'none'}",
             f"Outbound: {o['sequences_drafted']} drafted, {o['sent']} sent, {o['human_opens']} opens, {o['replies']} replies "
             f"({o['positive_replies']} positive), {o['bounces']} bounces{rate}",
             f"Meetings held: {r['meetings_held']}",
             f"Deals: {d['created']['count']} created ({money(d['created']['amount'])}), {d['won']['count']} won "
             f"({money(d['won']['amount'])}), {d['lost']['count']} lost, {d['stage_moves']['forward']} moved forward, "
             f"{d['stage_moves']['back']} moved back"]
    if r["approvals_pending"]:
        lines.append("Waiting on approval: " + ", ".join(f"{a} {n}" for a, n in sorted(r["approvals_pending"].items())))
    return "\n".join(lines)
