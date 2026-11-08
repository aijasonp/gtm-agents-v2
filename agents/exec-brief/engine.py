"""Exec Brief engine. Every number is computed here from warehouse rows; the model only writes one line.

Flow: load rows -> compute every metric once -> pick five per executive -> build a json-render card spec
-> render to Slack blocks -> deliver. The company snapshot takes the best and worst metric per department.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from gtm_core import pipeline, writer

STATE_KEY = "exec_brief:snapshot"
ROLES = ("ceo", "cso", "cmo", "channel")
DEPARTMENTS = {"sales": "Sales", "marketing": "Marketing", "partners": "Partners",
               "customer_success": "Customer Success"}
GOOD, WATCH, BAD = "good", "watch", "bad"
DOT = {GOOD: ":large_green_circle:", WATCH: ":large_yellow_circle:", BAD: ":red_circle:", None: ":white_circle:"}
WATCH_BAND = 0.10   # within 10% of pace or target is "watch", worse is "bad"


# ---------------------------------------------------------------- config and data

def config(ctx) -> dict:
    p = ctx.manifest.path(ctx.manifest.config.get("brief", "../../config/exec_brief.yaml"))
    return yaml.safe_load(Path(p).read_text()) or {}


def _now(now):
    return now or datetime.now(timezone.utc)


def load_rows(ctx, cfg: dict | None = None) -> dict[str, list[dict]]:
    """Rows for opportunities, leads, renewals and deal_registrations from the configured source."""
    cfg = cfg or config(ctx)
    src = (os.environ.get("EXEC_BRIEF_SOURCE") or cfg.get("source") or "fixtures").lower()
    names = ("opportunities", "leads", "renewals", "deal_registrations")
    if src == "snowflake":
        from gtm_core.sources import snowflake
        rows = snowflake.query_many({n: (cfg.get("snowflake") or {}).get("queries", {}).get(n, "") for n in names})
    elif src == "store":
        rows = {n: [] for n in names}
        rows["opportunities"] = [{**d, "status": (d.get("status") or "open").lower()} for d in ctx.store.select("deals")]
    else:
        path = Path(os.environ.get("EXEC_BRIEF_FIXTURES") or cfg.get("fixtures_path") or "data/sample/exec_brief.yaml")
        if not path.is_absolute() and not path.exists():
            path = Path(__file__).resolve().parents[2] / path
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        rows = {n: list(data.get(n) or []) for n in names}
    return {n: rows.get(n) or [] for n in names}


# ---------------------------------------------------------------- math helpers

def amt(r: dict, key: str = "amount") -> float:
    try:
        return float(r.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def quarter_bounds(now: datetime):
    q = (now.month - 1) // 3
    start = datetime(now.year, 3 * q + 1, 1, tzinfo=timezone.utc)
    end = datetime(now.year + (1 if q == 3 else 0), 1 if q == 3 else 3 * q + 4, 1, tzinfo=timezone.utc)
    return start, end


def month_bounds(now: datetime):
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    end = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _elapsed(now, start, end) -> float:
    return max(0.0, min(1.0, (now - start).total_seconds() / (end - start).total_seconds()))


def _in(v, start, end) -> bool:
    d = pipeline.parse_dt(v)
    return bool(d and start <= d < end)


def _ratio(a, b):
    return round(a / b, 4) if b else None


def money(v) -> str:
    if v is None:
        return "n/a"
    sign, v = ("-" if v < 0 else ""), abs(v)
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.2f}M".replace(".00M", "M")
    if v >= 10_000:
        return f"{sign}${v / 1000:,.0f}K"
    return f"{sign}${v:,.0f}"


def pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def fmt(v, kind: str) -> str:
    if v is None:
        return "n/a"
    return {"money": money, "pct": pct, "x": lambda x: f"{x:.1f}x"}.get(kind, lambda x: f"{x:,.0f}")(v)


def _status(score):
    if score is None:
        return None
    return GOOD if score >= 0 else WATCH if score >= -WATCH_BAND else BAD


def metric(key, label, dept, value, kind, better="up", target=None, paced=None, prev=None, detail="", items=None):
    """One metric. `paced` is the target scaled to time elapsed (QTD and MTD targets); `target` is the full target.
    Score is how far ahead (+) or behind (-) of pace or target, signed so higher is always better."""
    goal = paced if paced is not None else target
    score = None
    if goal is not None and value is not None:
        if better == "up":
            score = (value / goal - 1) if goal else (0.0 if value == 0 else 1.0)
        else:  # lower is better: at or under the ceiling is good
            score = (1 - value / goal) if goal else (0.0 if value == 0 else -1.0)
    elif prev is not None and value is not None:
        base = abs(prev) or 1
        score = (value - prev) / base * (1 if better == "up" else -1)
    delta = None if prev is None or value is None else round(value - prev, 4)
    return {"key": key, "label": label, "dept": dept, "value": value, "kind": kind, "better": better,
            "target": target, "paced": paced, "prev": prev, "delta": delta,
            "score": None if score is None else round(score, 4), "status": _status(score),
            "display": fmt(value, kind), "detail": detail, "items": items or []}


# ---------------------------------------------------------------- metrics

def compute(rows: dict, cfg: dict, prev: dict | None = None, now: datetime | None = None) -> dict:
    """Every metric, keyed. `prev` is yesterday's stored snapshot (metric values and open deal state)."""
    now = _now(now)
    prev = prev or {}
    pv = prev.get("metrics") or {}
    t, st = cfg.get("targets") or {}, cfg.get("settings") or {}
    qs, qe = quarter_bounds(now)
    ms, me = month_bounds(now)
    fq, fm = _elapsed(now, qs, qe), _elapsed(now, ms, me)
    stale_days, sla = int(st.get("stale_days", 14)), float(st.get("sla_hours", 24))
    late = [c.lower() for c in st.get("late_stage_categories", ["commit", "best_case"])]
    window = int(st.get("renewal_window_days", 90))

    opps = [o for o in rows.get("opportunities", []) if (o.get("type") or "new").lower() != "renewal"]
    status = lambda o: (o.get("status") or "open").lower()  # noqa: E731
    open_ = [o for o in opps if status(o) == "open"]
    won_q = [o for o in opps if status(o) == "won" and _in(o.get("close_date"), qs, now + timedelta(seconds=1))]
    lost_q = [o for o in opps if status(o) == "lost" and _in(o.get("close_date"), qs, now + timedelta(seconds=1))]
    open_q = [o for o in open_ if _in(o.get("close_date"), datetime.min.replace(tzinfo=timezone.utc), qe)]
    created_q = [o for o in opps if _in(o.get("created_at"), qs, now + timedelta(seconds=1))]
    src = lambda o: (o.get("source") or "other").lower()  # noqa: E731
    cat = lambda o: (o.get("forecast_category") or "").lower().replace(" ", "_")  # noqa: E731
    tot = lambda xs: round(sum(amt(o) for o in xs), 2)  # noqa: E731
    deal = lambda o, why="": {"name": o.get("name") or o.get("id"), "owner": o.get("owner") or "",  # noqa: E731
                              "amount": amt(o), "why": why}
    out: dict[str, dict] = {}

    def add(m):
        out[m["key"]] = m

    def pace(key):
        return round(t[key] * fq, 2) if t.get(key) is not None else None

    # Sales and CEO
    plan = t.get("bookings_plan_qtr")
    booked = tot(won_q)
    add(metric("bookings_qtd", "Bookings QTD", "sales", booked, "money", target=plan, paced=pace("bookings_plan_qtr"),
               prev=pv.get("bookings_qtd"),
               detail=f"of {money(plan)} plan, {pct(_ratio(booked, plan))} attained" if plan else ""))
    commit_open = tot([o for o in open_q if cat(o) == "commit"])
    fc = round(booked + commit_open, 2)
    add(metric("forecast_vs_plan", "Won + commit vs plan", "sales", _ratio(fc, plan), "pct", target=1.0 if plan else None,
               prev=pv.get("forecast_vs_plan"), detail=f"{money(fc)} of {money(plan)}" if plan else ""))
    remaining = max((plan or 0) - booked, 0)
    q_pipe = tot(open_q)
    cov = round(q_pipe / remaining, 2) if remaining else None
    add(metric("pipeline_coverage", "Coverage, rest of quarter", "sales", cov, "x", target=t.get("coverage"),
               prev=pv.get("pipeline_coverage"),
               detail=f"{money(q_pipe)} open vs {money(remaining)} left" if remaining else "plan met"))
    created = tot(created_q)
    add(metric("pipeline_created_qtd", "Pipeline created QTD", "sales", created, "money",
               target=t.get("pipeline_created_qtr"), paced=pace("pipeline_created_qtr"), prev=pv.get("pipeline_created_qtd"),
               detail=f"pace {money(pace('pipeline_created_qtr'))}" if t.get("pipeline_created_qtr") else ""))
    commit_items = sorted((deal(o) for o in open_q if cat(o) == "commit"), key=lambda d: -d["amount"])
    add(metric("commit_qtr", "Commit this quarter", "sales", commit_open, "money", prev=pv.get("commit_qtr"),
               detail=f"{len(commit_items)} deals", items=commit_items[:3]))

    prev_open = prev.get("open") or {}
    slipped = []
    for o in open_ + [o for o in opps if status(o) == "lost"]:
        was = prev_open.get(str(o.get("id")))
        if not was or not _in(was.get("close_date"), qs, qe):
            continue
        if status(o) == "lost":
            slipped.append(deal(o, "closed lost"))
        elif not _in(o.get("close_date"), datetime.min.replace(tzinfo=timezone.utc), qe):
            slipped.append(deal(o, f"moved to {str(o.get('close_date'))[:10]}"))
    slipped.sort(key=lambda d: -d["amount"])
    add(metric("slipped_out_1d", "Slipped out of quarter, last day", "sales", round(sum(d["amount"] for d in slipped), 2),
               "money", better="down", target=0, detail=f"{len(slipped)} deals", items=slipped[:3]))
    stalled = sorted((deal(o, f"{pipeline.days_since(o.get('last_activity_at'), now)}d quiet") for o in open_q
                      if cat(o) in late and (pipeline.days_since(o.get("last_activity_at"), now) or 10 ** 6) > stale_days),
                     key=lambda d: -d["amount"])
    add(metric("stalled_late_stage", f"Late-stage deals quiet {stale_days}+ days", "sales",
               round(sum(d["amount"] for d in stalled), 2), "money", better="down", target=0,
               prev=pv.get("stalled_late_stage"), detail=f"{len(stalled)} deals", items=stalled[:3]))
    wr = _ratio(tot(won_q), tot(won_q) + tot(lost_q))
    add(metric("win_rate_qtd", "Win rate QTD ($)", "sales", wr, "pct", target=t.get("win_rate"), prev=pv.get("win_rate_qtd"),
               detail=f"{len(won_q)} won, {len(lost_q)} lost"))

    # Marketing
    leads = rows.get("leads", [])
    mqls_m = [r for r in leads if _in(r.get("mql_at"), ms, now + timedelta(seconds=1))]
    add(metric("mqls_mtd", "MQLs month to date", "marketing", len(mqls_m), "count", target=t.get("mqls_month"),
               paced=round(t["mqls_month"] * fm, 2) if t.get("mqls_month") is not None else None, prev=pv.get("mqls_mtd"),
               detail=f"pace {round(t['mqls_month'] * fm)} of {t['mqls_month']}" if t.get("mqls_month") else ""))
    d90 = now - timedelta(days=90)
    m90 = [r for r in leads if _in(r.get("mql_at"), d90, now + timedelta(seconds=1))]
    s90 = [r for r in m90 if r.get("sql_at")]
    add(metric("mql_to_sql_90d", "MQL to SQL, last 90 days", "marketing", _ratio(len(s90), len(m90)), "pct",
               target=t.get("mql_to_sql"), prev=pv.get("mql_to_sql_90d"), detail=f"{len(s90)} of {len(m90)} MQLs"))
    mk = tot([o for o in created_q if src(o) == "marketing"])
    add(metric("marketing_pipeline_qtd", "Marketing-sourced pipeline QTD", "marketing", mk, "money",
               target=t.get("marketing_pipeline_qtr"), paced=pace("marketing_pipeline_qtr"),
               prev=pv.get("marketing_pipeline_qtd"),
               detail=f"pace {money(pace('marketing_pipeline_qtr'))}" if t.get("marketing_pipeline_qtr") else ""))
    add(metric("marketing_share_qtd", "Marketing share of new pipeline", "marketing", _ratio(mk, created), "pct",
               target=t.get("marketing_share"), prev=pv.get("marketing_share_qtd"), detail=f"of {money(created)} created"))
    due = [r for r in leads if _in(r.get("mql_at"), now - timedelta(days=7), now - timedelta(hours=sla))]
    fast = [r for r in due if (lambda a, b: a and b and (b - a).total_seconds() <= sla * 3600)(
        pipeline.parse_dt(r.get("mql_at")), pipeline.parse_dt(r.get("first_touch_at")))]
    add(metric("speed_to_lead", f"MQLs touched within {sla:g}h, last 7 days", "marketing", _ratio(len(fast), len(due)),
               "pct", target=t.get("speed_to_lead"), prev=pv.get("speed_to_lead"), detail=f"{len(fast)} of {len(due)}"))

    # Partners
    pp = tot([o for o in created_q if src(o) == "partner"])
    add(metric("partner_pipeline_qtd", "Partner-sourced pipeline QTD", "partners", pp, "money",
               target=t.get("partner_pipeline_qtr"), paced=pace("partner_pipeline_qtr"), prev=pv.get("partner_pipeline_qtd"),
               detail=f"pace {money(pace('partner_pipeline_qtr'))}" if t.get("partner_pipeline_qtr") else ""))
    pb = tot([o for o in won_q if src(o) == "partner"])
    add(metric("partner_bookings_qtd", "Partner-sourced bookings QTD", "partners", pb, "money",
               target=t.get("partner_bookings_qtr"), paced=pace("partner_bookings_qtr"), prev=pv.get("partner_bookings_qtd"),
               detail=f"of {money(t.get('partner_bookings_qtr'))} target" if t.get("partner_bookings_qtr") else ""))
    regs = rows.get("deal_registrations") or []
    if regs:
        when = [r.get("submitted_at") for r in regs]
        basis = "deal registrations"
    else:
        when = [o.get("created_at") for o in opps if src(o) == "partner"]
        basis = "partner-sourced opportunities"
    last7 = sum(_in(w, now - timedelta(days=7), now + timedelta(seconds=1)) for w in when)
    prior7 = sum(_in(w, now - timedelta(days=14), now - timedelta(days=7)) for w in when)
    add(metric("deal_regs_7d", "New deal registrations, last 7 days", "partners", last7, "count", prev=prior7,
               detail=f"{prior7} the 7 days before ({basis})"))
    open_all = tot(open_)
    add(metric("partner_share_open", "Partner share of open pipeline", "partners",
               _ratio(tot([o for o in open_ if src(o) == "partner"]), open_all), "pct", target=t.get("partner_share"),
               prev=pv.get("partner_share_open"), detail=f"of {money(open_all)} open"))
    active = {(o.get("partner") or "").strip() for o in opps
              if src(o) == "partner" and o.get("partner") and _in(o.get("created_at"), now - timedelta(days=90),
                                                                    now + timedelta(seconds=1))}
    add(metric("active_partners_90d", "Partners sourcing pipeline, last 90 days", "partners", len(active), "count",
               target=t.get("active_partners"), prev=pv.get("active_partners_90d")))

    # Customer success
    ren = rows.get("renewals", [])
    closed_r = [r for r in ren if (r.get("status") or "").lower() in ("renewed", "churned", "downsell")
                and _in(r.get("renewal_date"), qs, now + timedelta(seconds=1))]
    base = sum(amt(r, "arr") for r in closed_r)
    kept = sum(min(amt(r, "renewed_arr"), amt(r, "arr")) for r in closed_r)
    add(metric("grr_qtd", "Gross retention QTD", "customer_success", _ratio(kept, base), "pct", target=t.get("grr"),
               prev=pv.get("grr_qtd"), detail=f"{money(kept)} kept of {money(base)} up for renewal"))
    add(metric("nrr_qtd", "Net retention QTD", "customer_success",
               _ratio(sum(amt(r, "renewed_arr") for r in closed_r), base), "pct", target=t.get("nrr"),
               prev=pv.get("nrr_qtd")))
    risk = sorted(({"name": r.get("account"), "owner": "", "amount": amt(r, "arr"),
                    "why": f"renews {str(r.get('renewal_date'))[:10]}, health red"} for r in ren
                   if (r.get("status") or "open").lower() == "open" and (r.get("health") or "").lower() == "red"
                   and _in(r.get("renewal_date"), now, now + timedelta(days=window))), key=lambda d: -d["amount"])
    add(metric("renewal_arr_at_risk", f"Renewal ARR at risk, next {window} days", "customer_success",
               round(sum(d["amount"] for d in risk), 2), "money", better="down", target=0,
               prev=pv.get("renewal_arr_at_risk"), detail=f"{len(risk)} red-health accounts", items=risk[:3]))
    due_r = [r for r in ren if (r.get("status") or "open").lower() == "open"
             and _in(r.get("renewal_date"), now, now + timedelta(days=window))]
    add(metric("renewals_due", f"Renewal ARR due, next {window} days", "customer_success",
               round(sum(amt(r, "arr") for r in due_r), 2), "money", prev=pv.get("renewals_due"),
               detail=f"{len(due_r)} renewals"))
    for m in out.values():
        if m["key"] == "renewals_due":  # volume, not performance: shown, never ranked best or worst
            m["score"], m["status"] = None, None
    return {"as_of": now.isoformat(), "metrics": out}


def snapshot(rows: dict, computed: dict) -> dict:
    """What tomorrow's run compares against: today's metric values and each open deal's close date."""
    open_ = {str(o.get("id")): {"close_date": str(o.get("close_date") or "")[:10], "amount": amt(o)}
             for o in rows.get("opportunities", []) if (o.get("status") or "open").lower() == "open"}
    return {"as_of": computed["as_of"], "metrics": {k: m["value"] for k, m in computed["metrics"].items()},
            "open": open_}


# ---------------------------------------------------------------- selection

def brief_metrics(computed: dict, cfg: dict, role: str) -> list[dict]:
    keys = (cfg.get("briefs") or {}).get(role) or []
    if len(keys) != 5:
        raise ValueError(f"exec brief '{role}' must list exactly 5 metrics, has {len(keys)}")
    return [computed["metrics"][k] for k in keys]


def department_extremes(computed: dict, cfg: dict) -> list[dict]:
    """Best and worst ranked metric per department. Ties keep config order."""
    depts = (cfg.get("company") or {}).get("departments") or list(DEPARTMENTS)
    out = []
    for d in depts:
        ms = [m for m in computed["metrics"].values() if m["dept"] == d and m["score"] is not None]
        if not ms:
            out.append({"dept": d, "name": DEPARTMENTS.get(d, d.title()), "best": None, "worst": None})
            continue
        best = max(ms, key=lambda m: m["score"])
        worst = min(ms, key=lambda m: m["score"])
        out.append({"dept": d, "name": DEPARTMENTS.get(d, d.title()), "best": best,
                    "worst": worst if worst is not best else None})
    return out


# ---------------------------------------------------------------- words

def _delta_text(m) -> str:
    if m["delta"] is None or m["delta"] == 0:
        return ""
    arrow = "up" if m["delta"] > 0 else "down"
    if m["kind"] == "money":
        return f"{arrow} {money(abs(m['delta']))}"
    if m["kind"] == "pct":
        return f"{arrow} {abs(m['delta']) * 100:.0f} pts"
    if m["kind"] == "x":
        return f"{arrow} {abs(m['delta']):.1f}x"
    return f"{arrow} {abs(m['delta']):,.0f}"


NO_DELTA = {"deal_regs_7d"}  # compared with the prior 7 days in its detail, not with the last run


def metric_line(m) -> str:
    parts = [m["display"]]
    if m["kind"] == "x" and m["target"] is not None:
        parts.append(f"target {fmt(m['target'], 'x')}")
    elif m["kind"] == "pct" and m["target"] is not None and m["key"] != "forecast_vs_plan":
        parts.append(f"target {pct(m['target'])}")
    elif m["kind"] == "count" and m["target"] is not None and m["paced"] is None:
        parts.append(f"target {fmt(m['target'], 'count')}")
    if m["detail"]:
        parts.append(m["detail"])
    d = "" if m["key"] in NO_DELTA else _delta_text(m)
    if d:
        parts.append(f"{d} since last run")
    return ", ".join(parts)


def fallback_read(ms: list[dict]) -> str:
    ranked = [m for m in ms if m["score"] is not None]
    if not ranked:
        return "No targets set yet, so nothing is ranked."
    best, worst = max(ranked, key=lambda m: m["score"]), min(ranked, key=lambda m: m["score"])
    if worst["status"] == GOOD:
        return f"All ranked numbers on track. Strongest: {best['label']} at {best['display']}."
    return f"Needs action: {worst['label']} at {worst['display']}. Strongest: {best['label']} at {best['display']}."


NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?[KkMm%x]?")


def grounded(text: str, ms: list[dict]) -> bool:
    """Every number in model text must appear in the facts it was given."""
    allowed = " ".join(metric_line(m) + " " + " ".join(f"{money(i['amount'])} {i['why']}" for i in m["items"])
                       for m in ms)
    return all(n in allowed for n in NUM.findall(text))


def read_line(ctx, role_title: str, ms: list[dict]) -> tuple[str, str]:
    fb = fallback_read(ms)
    facts = [{"metric": m["label"], "now": metric_line(m), "status": m["status"]} for m in ms]
    text, source = writer.narrate(ctx, f"Write ONE sentence for the {role_title}: the single thing to act on today "
                                  "and why, then the strongest number. Quote numbers exactly as given.",
                                  {"metrics": facts}, fb, max_words=40)
    text = text.strip().lstrip("- ").splitlines()[0] if text.strip() else fb
    if source == "model" and not grounded(text, ms):
        ctx.audit.log("exec_brief.ungrounded", text=text[:300])
        return fb, "template"
    return text, source


# ---------------------------------------------------------------- json-render spec

class Spec:
    """Builds a flat json-render spec: {root, elements: {id: {type, props, children}}}."""

    def __init__(self):
        self.elements: dict[str, dict] = {}
        self.n = 0

    def el(self, type_: str, props: dict | None = None, children: list[str] | None = None) -> str:
        self.n += 1
        eid = f"{type_.lower()}-{self.n}"
        self.elements[eid] = {"type": type_, "props": props or {}, "children": children or []}
        return eid

    def done(self, root: str) -> dict:
        return {"root": root, "elements": self.elements}


def _day(now: datetime) -> str:
    return now.strftime("%a %b %d").replace(" 0", " ")


def exec_spec(role_title: str, ms: list[dict], read: str, now: datetime, link: str = "") -> dict:
    s = Spec()
    kids = [s.el("Text", {"content": read, "style": "bold"})]
    fields = [s.el("Field", {"label": f"{DOT[m['status']]} {m['label']}", "value": metric_line(m)}) for m in ms]
    kids.append(s.el("Fields", {}, fields))
    rows = [[m["label"], i["name"], money(i["amount"]), i["why"]]
            for m in ms if m["status"] in (BAD, WATCH) for i in m["items"]][:5]
    if rows:
        kids.append(s.el("Divider"))
        kids.append(s.el("Table", {"headers": ["Behind", "Deal or account", "Amount", "Why"], "rows": rows,
                                   "align": ["left", "left", "right", "left"],
                                   "caption": "Deals and accounts behind the numbers"}))
    if link:
        kids.append(s.el("Actions", {}, [s.el("LinkButton", {"label": "Open dashboard", "url": link})]))
    root = s.el("Card", {"title": f"{role_title} daily brief", "subtitle": f"{_day(now)} | 5 numbers that matter"}, kids)
    return s.done(root)


def company_spec(rows_: list[dict], headline: str, now: datetime, link: str = "", strip: str = "") -> dict:
    s = Spec()
    cell = lambda m: f"{m['label']}: {m['display']}" if m else "nothing ranked"  # noqa: E731
    table = s.el("Table", {"headers": ["Team", "Best", "Worst"], "caption": "Best and worst number per team",
                           "rows": [[r["name"], cell(r["best"]), cell(r["worst"])] for r in rows_]})
    kids = [s.el("Text", {"content": headline, "style": "bold"}), table]
    if strip:
        kids += [s.el("Divider"), s.el("Text", {"content": "Last 6 weeks, oldest to newest", "style": "muted"}),
                 s.el("Text", {"content": strip})]
    if link:
        kids.append(s.el("Actions", {}, [s.el("LinkButton", {"label": "Open command center", "url": link})]))
    root = s.el("Card", {"title": "Company daily snapshot", "subtitle": f"{_day(now)} | best and worst number per team"},
                kids)
    return s.done(root)


ALLOWED = {"Card", "Section", "Text", "Fields", "Field", "Table", "Chart", "Divider", "Image", "Actions", "Button",
           "LinkButton"}


def validate_spec(spec: dict, max_tables: int = 1) -> list[str]:
    issues, els = [], spec.get("elements") or {}
    if spec.get("root") not in els:
        issues.append("root element missing")
    for eid, e in els.items():
        if e.get("type") not in ALLOWED:
            issues.append(f"{eid}: unknown type {e.get('type')}")
        for c in e.get("children") or []:
            if c not in els:
                issues.append(f"{eid}: child {c} missing")
    if sum(e.get("type") == "Table" for e in els.values()) > max_tables:
        issues.append(f"more than {max_tables} table")
    return issues


# ---------------------------------------------------------------- render and deliver

BRIDGE = Path(__file__).resolve().parent / "delivery" / "render.mjs"


def _bridge_ready() -> bool:
    return bool(shutil.which("node")) and (BRIDGE.parent / "node_modules" / "@json-render" / "chat").exists()


def render(spec: dict, renderer: str | None = None) -> tuple[list[dict], str, str]:
    """(blocks, fallback text, renderer used). chat-sdk uses json-render + Chat SDK's Slack adapter in Node;
    python is the built-in Block Kit renderer and the fallback when Node is unavailable."""
    mode = (renderer or os.environ.get("EXEC_BRIEF_RENDERER") or "auto").lower()
    if mode in ("auto", "chat-sdk") and _bridge_ready():
        try:
            r = subprocess.run(["node", str(BRIDGE)], input=json.dumps({"spec": spec, "limits": {"tables": 1}}),
                               capture_output=True, text=True, timeout=30, check=True)
            out = json.loads(r.stdout)
            return out["blocks"], out["text"], "chat-sdk"
        except Exception as e:  # never lose the brief over the renderer
            if mode == "chat-sdk":
                raise RuntimeError(f"chat-sdk renderer failed: {e}") from e
    blocks, text = python_blocks(spec)
    return blocks, text, "python"


def python_blocks(spec: dict) -> tuple[list[dict], str]:
    els = spec["elements"]
    blocks, text = [], []

    def walk(eid):
        e = els[eid]
        t, p = e["type"], e["props"]
        if t == "Card":
            title = p.get("title") or ""
            blocks.append({"type": "header", "text": {"type": "plain_text", "text": title[:150]}})
            if p.get("subtitle"):
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": p["subtitle"]}]})
            text.append(title)
        elif t == "Text":
            c = f"*{p['content']}*" if p.get("style") == "bold" else p["content"]
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": c[:3000]}})
            text.append(p["content"])
        elif t == "Fields":
            lines = [f"{els[c]['props']['label']}\n{els[c]['props']['value']}" for c in e["children"]]
            for ln in lines:  # one section per metric keeps long values readable on a phone
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ln[:3000]}})
            text.extend(lines)
            return
        elif t == "Divider":
            blocks.append({"type": "divider"})
        elif t == "Table":
            rows = [p["headers"], *p["rows"]]
            body = "\n".join(" | ".join(str(c) for c in r) for r in rows)
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"```{body[:2900]}```"}})
            text.append(body)
        elif t == "Actions":
            btns = []
            for c in e["children"]:
                cp = els[c]["props"]
                b = {"type": "button", "text": {"type": "plain_text", "text": cp["label"]}}
                b.update({"url": cp["url"]} if els[c]["type"] == "LinkButton" else {"action_id": cp["id"]})
                btns.append(b)
            blocks.append({"type": "actions", "elements": btns})
            return
        for c in e.get("children") or []:
            walk(c)

    walk(spec["root"])
    return blocks, "\n".join(text)


def recipient_id(cfg: dict, role: str) -> str | None:
    env = ((cfg.get("recipients") or {}).get(role) or {}).get("slack_id_env")
    return os.environ.get(env) if env else None


def run(ctx, now: datetime | None = None, roles: tuple[str, ...] = ROLES, company: bool = True,
        renderer: str | None = None, dry_run: bool = False) -> dict:
    """Compute once, send five-metric briefs to each executive and the company snapshot to the shared channel."""
    now = _now(now)
    cfg = config(ctx)
    rows = load_rows(ctx, cfg)
    prev = ctx.store.get_state(STATE_KEY) or {}
    computed = compute(rows, cfg, prev, now)
    links = ((cfg.get("settings") or {}).get("links") or {})
    sent = {}
    for role in roles:
        title = ((cfg.get("recipients") or {}).get(role) or {}).get("title") or role.upper()
        ms = brief_metrics(computed, cfg, role)
        read, source = read_line(ctx, title, ms)
        spec = exec_spec(title, ms, read, now, links.get(role) or "")
        issues = validate_spec(spec)
        if issues:
            raise ValueError(f"{role} spec invalid: {issues}")
        blocks, text, used = render(spec, renderer)
        uid = recipient_id(cfg, role)
        if not dry_run:
            ctx.slack.dm(uid, text, blocks=blocks)
        sent[role] = {"to": uid or "team channel", "read": read, "read_source": source, "renderer": used,
                      "metrics": {m["key"]: {"value": m["value"], "status": m["status"]} for m in ms}, "spec": spec}
    from gtm_core.agents import load_module
    cc = load_module(ctx.manifest, "command_center")
    if not dry_run:
        cc.record(ctx.store, computed)
    g = cc.grid(sys.modules[__name__], rows, cfg, ctx.store.get_state(cc.HISTORY_KEY) or {}, now, today=computed)
    ext = department_extremes(computed, cfg)
    page = cc.html_page(sys.modules[__name__], g, computed, ext, now)
    page_path = None if dry_run else str(cc.write(ctx.settings, page))
    if company:
        bk = computed["metrics"]["bookings_qtd"]
        headline = f"Bookings {bk['display']} QTD, {bk['detail']}." if bk["detail"] else f"Bookings {bk['display']} QTD."
        strip_keys = [m["key"] for r in ext for m in (r["best"], r["worst"]) if m]
        link = os.environ.get("EXEC_BRIEF_COMMAND_CENTER_URL") or links.get("company") or ""
        spec = company_spec(ext, headline, now, link, cc.slack_strip(g, strip_keys))
        blocks, text, used = render(spec, renderer)
        ch = os.environ.get((cfg.get("company") or {}).get("channel_env") or "")
        if not dry_run:
            ctx.slack.post(text, blocks=blocks, channel=ch or None)
        sent["company"] = {"to": ch or "team channel", "renderer": used, "spec": spec,
                           "teams": {r["dept"]: {"best": r["best"] and r["best"]["key"],
                                                 "worst": r["worst"] and r["worst"]["key"]} for r in ext}}
    if not dry_run:
        ctx.store.set_state(STATE_KEY, snapshot(rows, computed))
    return {"as_of": computed["as_of"], "sent": sent, "command_center": page_path, "page": page}
