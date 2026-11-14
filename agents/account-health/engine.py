"""Account Health engine: renewal risk and expansion readiness for existing customers.

Product usage (trend, utilization, breadth, support load), conversation history (calls and call insights),
contacts (champion departures) and account signals are read from the store. Every score, band, driver and
action is deterministic Python driven by skill/references/health-rules.yaml. The model only narrates.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from gtm_core import pipeline
from gtm_core.store import now_iso

USAGE_SCHEMA = """CREATE TABLE IF NOT EXISTS product_usage (
  id {AUTOID}, account_id TEXT NOT NULL, metric TEXT NOT NULL, value DOUBLE PRECISION, observed_at TEXT NOT NULL,
  source TEXT, created_at TEXT)"""
USAGE_INDEX = "CREATE INDEX IF NOT EXISTS ix_usage_account ON product_usage(account_id, metric, observed_at)"
STATE_PREFIX = "account_health:last:"
NEGATION = re.compile(r"\b(not|no|never|won't|wont|don't|dont|isn't|aren't|without)\b[\w\s,']{0,20}$")


# ---------- config ----------
@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    return yaml.safe_load(open(path).read()) or {}


def rules(ctx) -> dict:
    return _yaml(str(ctx.manifest.path(ctx.manifest.config.get("rules", "skill/references/health-rules.yaml"))))


def _now(now):
    return now or datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.replace(microsecond=0).isoformat()


# ---------- usage storage ----------
def ensure(store) -> None:
    if not getattr(store, "_usage_schema", False):
        autoid = "INTEGER PRIMARY KEY AUTOINCREMENT" if store.kind == "sqlite" else "BIGSERIAL PRIMARY KEY"
        sql = USAGE_SCHEMA.replace("{AUTOID}", autoid)
        store.execute(sql.replace("DOUBLE PRECISION", "REAL") if store.kind == "sqlite" else sql)
        store.execute(USAGE_INDEX)
        store._usage_schema = True


def canonical_metric(ctx, name: str) -> str | None:
    n = (name or "").strip().lower()
    for canon, aliases in rules(ctx).get("metric_aliases", {}).items():
        if n == canon or n in [a.lower() for a in aliases]:
            return canon
    return None


def resolve_account(ctx, ref: str) -> dict | None:
    if not ref:
        return None
    a = ctx.store.account(ref) or ctx.store.account_by_domain(ref)
    if a:
        return a
    low = ref.strip().lower()
    return next((x for x in ctx.store.accounts() if (x.get("name") or "").lower() == low), None)


def add_usage(ctx, account: str, metric: str, value, observed_at: str, source: str = "manual") -> dict:
    """Store one usage observation. Unknown metric names and unknown accounts are refused, not guessed."""
    ensure(ctx.store)
    canon = canonical_metric(ctx, metric)
    if not canon:
        return {"ok": False, "error": f"unknown metric '{metric}'; add it to metric_aliases in health-rules.yaml"}
    acct = resolve_account(ctx, account)
    if not acct:
        return {"ok": False, "error": f"account '{account}' not found"}
    when = pipeline.parse_dt(observed_at)
    if when is None:
        return {"ok": False, "error": f"unreadable observed_at {observed_at!r}"}
    try:
        v = float(value)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"value {value!r} is not a number"}
    when_iso = _iso(when)
    if ctx.store.one("SELECT id FROM product_usage WHERE account_id=? AND metric=? AND observed_at=?",
                     (acct["id"], canon, when_iso)):
        ctx.store.execute("UPDATE product_usage SET value=?, source=? WHERE account_id=? AND metric=? AND observed_at=?",
                          (v, source, acct["id"], canon, when_iso))
        return {"ok": True, "updated": True, "account_id": acct["id"], "metric": canon}
    ctx.store.insert("INSERT INTO product_usage (account_id, metric, value, observed_at, source, created_at) "
                     "VALUES (?,?,?,?,?,?)", (acct["id"], canon, v, when_iso, source, now_iso()))
    return {"ok": True, "updated": False, "account_id": acct["id"], "metric": canon}


def import_usage(ctx, path: str | Path, source: str = "csv") -> dict:
    """CSV or JSON rows with account (id, domain or name), metric, value, observed_at."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        rows = json.loads(p.read_text())
    else:
        with p.open(newline="") as f:
            rows = list(csv.DictReader(f))
    stored, errors = 0, []
    for i, r in enumerate(rows, 1):
        res = add_usage(ctx, r.get("account") or r.get("account_id") or r.get("domain") or "", r.get("metric", ""),
                        r.get("value"), r.get("observed_at") or r.get("date") or "", r.get("source") or source)
        if res["ok"]:
            stored += 1
        else:
            errors.append(f"row {i}: {res['error']}")
    return {"rows": len(rows), "stored": stored, "errors": errors[:20], "error_count": len(errors)}


def usage_rows(ctx, account_id: str) -> list[dict]:
    ensure(ctx.store)
    return ctx.store.query("SELECT metric, value, observed_at FROM product_usage WHERE account_id=? ORDER BY observed_at",
                           (account_id,))


# ---------- customers and contracts ----------
def won_deals(ctx, account_id: str) -> list[dict]:
    return sorted([d for d in ctx.store.select("deals", "account_id=?", (account_id,)) if pipeline.is_won(d)],
                  key=lambda d: d.get("close_date") or "")


def is_customer(ctx, acct: dict) -> bool:
    flag = acct.get("customer")
    if isinstance(flag, str):
        flag = flag.strip().lower() in ("true", "yes", "1", "customer")
    if flag is False:
        return False
    return bool(flag) or bool(won_deals(ctx, acct["id"]))


def customers(ctx, owner: str = "") -> list[dict]:
    out = [a for a in ctx.store.accounts() if is_customer(ctx, a)]
    if owner:
        out = [a for a in out if (contract(ctx, a)["owner"] or "").lower() == owner.lower()]
    return out


def _add_months(d: datetime, months: int) -> datetime:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return d.replace(year=y, month=m, day=day)
        except ValueError:
            continue
    return d


def contract(ctx, acct: dict) -> dict:
    wins = won_deals(ctx, acct["id"])
    renewal = pipeline.parse_dt(acct.get("renewal_date"))
    source = "account"
    if renewal is None and wins and pipeline.parse_dt(wins[-1].get("close_date")):
        renewal = _add_months(pipeline.parse_dt(wins[-1]["close_date"]), int(rules(ctx).get("contract_months", 12)))
        source = "last won deal + contract_months"
    arr = acct.get("arr")
    if arr in (None, "") and wins:
        arr = wins[-1].get("amount")
    try:
        arr = float(arr) if arr not in (None, "") else None
    except (TypeError, ValueError):
        arr = None
    try:
        seats = int(float(acct["seats"])) if acct.get("seats") not in (None, "") else None
    except (TypeError, ValueError):
        seats = None
    owner = acct.get("owner") or acct.get("csm") or (wins[-1].get("owner") if wins else None)
    return {"arr": arr, "seats": seats, "renewal_date": renewal.date().isoformat() if renewal else None,
            "renewal_source": source if renewal else None, "owner": owner}


# ---------- usage math ----------
def _window_avg(rows: list[dict], metric: str, start: datetime, end: datetime) -> float | None:
    vals = [float(r["value"]) for r in rows if r["metric"] == metric
            and start <= (pipeline.parse_dt(r["observed_at"]) or start - timedelta(days=1)) < end]
    return round(sum(vals) / len(vals), 2) if vals else None


def _window_sum(rows: list[dict], metric: str, start: datetime, end: datetime) -> float | None:
    vals = [float(r["value"]) for r in rows if r["metric"] == metric
            and start <= (pipeline.parse_dt(r["observed_at"]) or start - timedelta(days=1)) < end]
    return sum(vals) if vals else None


def _change(cur, prev) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / prev, 3)


def usage_profile(ctx, account_id: str, seats: int | None, now: datetime) -> dict:
    r = rules(ctx)
    days = int(r["windows"]["usage_days"])
    rows = usage_rows(ctx, account_id)
    cur_s, prev_s = now - timedelta(days=days), now - timedelta(days=2 * days)
    out: dict = {"has_data": bool(rows), "metrics": {}}
    for m in ("active_users", "core_actions", "features_used", "teams"):
        cur, prev = _window_avg(rows, m, cur_s, now), _window_avg(rows, m, prev_s, cur_s)
        if cur is not None or prev is not None:
            out["metrics"][m] = {"current": cur, "previous": prev, "change": _change(cur, prev)}
    for m in ("support_tickets", "escalations"):
        cur, prev = _window_sum(rows, m, cur_s, now), _window_sum(rows, m, prev_s, cur_s)
        if cur is not None or prev is not None:
            out["metrics"][m] = {"current": cur or 0, "previous": prev or 0, "change": _change(cur or 0, prev)}
    last = max((pipeline.parse_dt(x["observed_at"]) for x in rows), default=None)
    out["last_seen"] = last.date().isoformat() if last else None
    out["days_since_data"] = (now - last).days if last else None
    latest_au = next((float(x["value"]) for x in reversed(rows) if x["metric"] == "active_users"), None)
    out["latest_active_users"] = latest_au
    out["utilization"] = round(latest_au / seats, 3) if latest_au is not None and seats else None
    return out


# ---------- conversations ----------
def _phrase_hits(text: str, phrases: list[str]) -> list[tuple[str, str]]:
    """(phrase, sentence) for every whole-word hit not negated just before it."""
    hits, seen = [], set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        low = sentence.lower()
        for p in phrases:
            for m in re.finditer(r"(?<![a-z])" + re.escape(p.lower()) + r"(?![a-z])", low):
                if NEGATION.search(low[:m.start()]):
                    continue
                key = (p.lower(), sentence.strip()[:200])
                if key not in seen:
                    seen.add(key)
                    hits.append((p, sentence.strip()[:240]))
                break
    return hits


def conversations(ctx, account_id: str, now: datetime) -> dict:
    r = rules(ctx)
    since = now - timedelta(days=int(r["windows"]["conversation_days"]))
    meetings = [m for m in ctx.store.select("meetings", "account_id=?", (account_id,))
                if (pipeline.parse_dt(m.get("started_at")) or since - timedelta(days=1)) >= since
                and (pipeline.parse_dt(m.get("started_at")) or now) <= now]
    texts = [(m.get("id"), " ".join(filter(None, [m.get("summary"), m.get("transcript")]))) for m in meetings]
    ins = [i for i in ctx.store.insights(since_iso=_iso(since), account_id=account_id)
           if i["kind"] in ("objection", "competitor_mention", "pricing_mention", "next_step", "call_flag")]
    texts += [(i.get("meeting_id"), i.get("evidence") or "") for i in ins]
    churn, expand = [], []
    for mid, t in texts:
        churn += [{"phrase": p, "quote": q, "meeting_id": mid} for p, q in _phrase_hits(t, r.get("churn_phrases", []))]
        expand += [{"phrase": p, "quote": q, "meeting_id": mid} for p, q in _phrase_hits(t, r.get("expansion_phrases", []))]

    def dedupe(xs):
        seen, out = set(), []
        for x in xs:
            if x["quote"] not in seen:
                seen.add(x["quote"])
                out.append(x)
        return out

    comps = sorted({i["key"] for i in ins if i["kind"] == "competitor_mention"})
    all_meetings = ctx.store.select("meetings", "account_id=?", (account_id,))
    last = max((d for d in (pipeline.parse_dt(m.get("started_at")) for m in all_meetings) if d and d <= now), default=None)
    return {"meetings": len(meetings), "churn": dedupe(churn)[:5], "expansion": dedupe(expand)[:5], "competitors": comps,
            "last_meeting": last.date().isoformat() if last else None,
            "days_since_meeting": (now - last).days if last else None}


# ---------- people and signals ----------
def _departed(c: dict, markers: dict) -> bool:
    if markers.get("left_company") and str(c.get("left_company", "")).lower() in ("true", "1", "yes"):
        return True
    return (str(c.get("status") or "").lower()) in [s.lower() for s in markers.get("status", [])]


def champions_left(ctx, account_id: str) -> list[str]:
    r = rules(ctx)
    roles = {x.lower() for x in r.get("champion_roles", [])}
    return [c.get("name") or c.get("email") or c["id"] for c in ctx.store.select("contacts", "account_id=?", (account_id,))
            if str(c.get("role") or "").lower() in roles and _departed(c, r.get("departed_markers", {}))]


def account_signals(ctx, account_id: str, now: datetime) -> dict:
    r = rules(ctx)
    since = _iso(now - timedelta(days=int(r["windows"]["signal_days"])))
    sigs = [s for s in ctx.store.signals_for(account_id, since) if (pipeline.parse_dt(s["observed_at"]) or now) <= now]
    risk_t, exp_t = set(r["signals"]["risk"]), set(r["signals"]["expansion"])
    fmt = lambda s: f"{s['signal_type']} {s['observed_at'][:10]}" + (f" ({s['url']})" if s.get("url") else "")
    return {"risk": [fmt(s) for s in sigs if s["signal_type"] in risk_t],
            "expansion": [fmt(s) for s in sigs if s["signal_type"] in exp_t]}


# ---------- assessment ----------
def _pct(x: float) -> str:
    return f"{'+' if x > 0 else ''}{round(x * 100)}%"


ACTIONS = {
    "usage_drop": "Run a usage review with the admin: which teams stopped and why",
    "usage_dark": "Confirm the usage feed and check in with the admin; the account has gone quiet",
    "low_utilization": "Build an adoption plan for unused seats before renewal talks",
    "feature_shrink": "Re-onboard the features they stopped using",
    "support_spike": "Review open tickets with support and close the loop with the customer",
    "escalation": "Get the escalation owner and the customer on a call this week",
    "churn_language": "Book an executive sponsor call to address what they said on the call",
    "competitor_mentioned": "Ask what they like about the competitor they named and show the gap",
    "champion_left": "Find and meet the new owner of the relationship",
    "no_meeting": "Book a business review",
    "risk_signal": "Check what the account news means for their budget and team",
    "seat_ceiling": "Propose a seat true-up before they hit the limit",
    "usage_growth": "Share the usage growth with the sponsor and ask where it goes next",
    "breadth_growth": "Map the new teams using it and find their leaders",
    "expansion_language": "Book an expansion discovery on what they said on the call",
    "expansion_signal": "Tie the account news to a wider rollout",
}


def assess(ctx, acct: dict, now: datetime | None = None) -> dict:
    """Assess one customer. Pure read: nothing is written."""
    now = _now(now)
    r = rules(ctx)
    t, rp, ep = r["thresholds"], r["risk_points"], r["expansion_points"]
    con = contract(ctx, acct)
    use = usage_profile(ctx, acct["id"], con["seats"], now)
    conv = conversations(ctx, acct["id"], now)
    sig = account_signals(ctx, acct["id"], now)
    left = champions_left(ctx, acct["id"])
    risk: list[tuple[str, int, str]] = []
    expand: list[tuple[str, int, str]] = []
    m = use["metrics"]

    au, ca = m.get("active_users", {}), m.get("core_actions", {})
    drops = [(k, x) for k, x in (("active users", au), ("core actions", ca))
             if x.get("change") is not None and x["change"] <= t["usage_drop"]]
    if drops:
        k, x = min(drops, key=lambda kx: kx[1]["change"])
        risk.append(("usage_drop", rp["usage_drop"], f"{k} {_pct(x['change'])} ({x['previous']:g} to {x['current']:g})"))
    dark = int(r["windows"]["dark_days"])
    if use["has_data"] and (use["days_since_data"] or 0) >= dark:
        risk.append(("usage_dark", rp["usage_dark"], f"no usage data for {use['days_since_data']} days (last {use['last_seen']})"))
    if use["utilization"] is not None and use["utilization"] < t["low_utilization"]:
        risk.append(("low_utilization", rp["low_utilization"],
                     f"{use['latest_active_users']:g} of {con['seats']} seats active ({round(use['utilization'] * 100)}%)"))
    fu = m.get("features_used", {})
    if fu.get("change") is not None and fu["change"] < 0:
        risk.append(("feature_shrink", rp["feature_shrink"], f"features used {fu['previous']:g} to {fu['current']:g}"))
    st = m.get("support_tickets", {})
    if st and st["current"] >= t["support_spike_min"] and (st["previous"] == 0 or (st["change"] or 0) >= t["support_spike"]):
        risk.append(("support_spike", rp["support_spike"], f"support tickets {st['previous']:g} to {st['current']:g}"))
    esc = m.get("escalations", {})
    if esc and esc["current"] > 0:
        risk.append(("escalation", rp["escalation"], f"{esc['current']:g} escalation(s) in the last {r['windows']['usage_days']} days"))
    if conv["churn"]:
        risk.append(("churn_language", rp["churn_language"], f"said \"{conv['churn'][0]['quote'][:120]}\""))
    if conv["competitors"]:
        risk.append(("competitor_mentioned", rp["competitor_mentioned"], "competitor named on a call: " + ", ".join(conv["competitors"][:3])))
    if left:
        risk.append(("champion_left", rp["champion_left"], "champion or sponsor left: " + ", ".join(left[:3])))
    nmd = int(r["windows"]["no_meeting_days"])
    if conv["days_since_meeting"] is None or conv["days_since_meeting"] > nmd:
        risk.append(("no_meeting", rp["no_meeting"], f"no customer meeting in {conv['days_since_meeting']} days"
                     if conv["days_since_meeting"] is not None else "no customer meeting on record"))
    if sig["risk"]:
        risk.append(("risk_signal", rp["risk_signal"], "account news: " + "; ".join(sig["risk"][:2])))

    if use["utilization"] is not None and use["utilization"] >= t["seat_ceiling"]:
        expand.append(("seat_ceiling", ep["seat_ceiling"],
                       f"{use['latest_active_users']:g} of {con['seats']} seats active ({round(use['utilization'] * 100)}%)"))
    ups = [(k, x) for k, x in (("active users", au), ("core actions", ca))
           if x.get("change") is not None and x["change"] >= t["usage_growth"]]
    if ups:
        k, x = max(ups, key=lambda kx: kx[1]["change"])
        expand.append(("usage_growth", ep["usage_growth"], f"{k} {_pct(x['change'])} ({x['previous']:g} to {x['current']:g})"))
    br = [(k, m[k]) for k in ("teams", "features_used") if m.get(k, {}).get("change") is not None and m[k]["change"] > 0]
    if br:
        k, x = br[0]
        expand.append(("breadth_growth", ep["breadth_growth"], f"{k.replace('_', ' ')} {x['previous']:g} to {x['current']:g}"))
    if conv["expansion"]:
        expand.append(("expansion_language", ep["expansion_language"], f"said \"{conv['expansion'][0]['quote'][:120]}\""))
    if sig["expansion"]:
        expand.append(("expansion_signal", ep["expansion_signal"], "account news: " + "; ".join(sig["expansion"][:2])))

    risk_score = min(100, sum(p for _, p, _ in risk))
    exp_score = min(100, sum(p for _, p, _ in expand))
    bands = r["bands"]
    band = "at_risk" if risk_score >= bands["at_risk"] else "watch" if risk_score >= bands["watch"] else "healthy"
    days_to_renewal = pipeline.days_until(con["renewal_date"], now) if con["renewal_date"] else None
    factor = 1.0
    if days_to_renewal is not None and days_to_renewal >= 0:
        for u in sorted(r.get("urgency", []), key=lambda u: u["within_days"]):
            if days_to_renewal <= u["within_days"]:
                factor = float(u["factor"])
                break
    if band == "at_risk":
        rec, src = "save", risk
    elif exp_score >= int(r["expansion_ready"]):
        rec, src = "expand", expand
    elif band == "watch":
        rec, src = "watch", risk
    else:
        rec, src = "steady", []
    actions = [ACTIONS[k] for k, _, _ in sorted(src, key=lambda x: -x[1])][:3]
    alert_days = int(r["windows"]["renewal_alert_days"])
    return {
        "account_id": acct["id"], "name": acct.get("name"), "owner": con["owner"], "arr": con["arr"],
        "seats": con["seats"], "renewal_date": con["renewal_date"], "renewal_source": con["renewal_source"],
        "days_to_renewal": days_to_renewal,
        "renewal_window": days_to_renewal is not None and 0 <= days_to_renewal <= alert_days,
        "risk": risk_score, "band": band, "expansion": exp_score, "recommendation": rec,
        "priority": round(risk_score * factor, 1),
        "risk_drivers": [d for _, _, d in sorted(risk, key=lambda x: -x[1])],
        "risk_keys": [k for k, _, _ in risk],
        "expansion_drivers": [d for _, _, d in sorted(expand, key=lambda x: -x[1])],
        "expansion_keys": [k for k, _, _ in expand],
        "actions": actions,
        "evidence": {"churn": conv["churn"], "expansion": conv["expansion"], "competitors": conv["competitors"],
                     "champions_left": left, "signals": sig},
        "usage": use, "last_meeting": conv["last_meeting"],
    }


def assess_all(ctx, owner: str = "", now: datetime | None = None, persist: bool = True) -> list[dict]:
    now = _now(now)
    res = [assess(ctx, a, now) for a in customers(ctx, owner)]
    res.sort(key=lambda x: (-x["priority"], -x["expansion"], x["name"] or ""))
    if persist:
        for x in res:
            record(ctx, x)
    return res


def record(ctx, x: dict) -> None:
    ctx.store.add_insight("account-health", "account_health", x["account_id"],
                          {k: x[k] for k in ("risk", "band", "expansion", "recommendation", "priority", "renewal_date",
                                             "risk_drivers", "expansion_drivers")},
                          "; ".join(x["risk_drivers"][:2] or x["expansion_drivers"][:2]), account_id=x["account_id"])


# ---------- write-back (approval only) ----------
def queue_task(ctx, x: dict, now: datetime) -> int | None:
    """One CRM task for the owner when an account becomes `save` or `expand`. Waits for approval."""
    if x["recommendation"] not in ("save", "expand"):
        return None
    acct = ctx.store.account(x["account_id"]) or {}
    label = "Renewal risk" if x["recommendation"] == "save" else "Expansion play"
    drivers = x["risk_drivers"] if x["recommendation"] == "save" else x["expansion_drivers"]
    body = "\n".join([f"{label}: {x['name']} (risk {x['risk']}, expansion {x['expansion']})",
                      *(f"- {d}" for d in drivers[:4]), "Next:", *(f"- {a}" for a in x["actions"])])
    due = (now + timedelta(days=2 if x["recommendation"] == "save" else 5)).date().isoformat()
    return ctx.approvals.request("crm_task", {"subject": f"{label}: {x['name']}", "body": body, "due_at": due,
                                              "account_crm_id": acct.get("crm_id"), "owner": x["owner"],
                                              "account_id": x["account_id"], "motion": "crm"})


def changes(ctx, results: list[dict], now: datetime, queue: bool = True) -> dict:
    """Compare with the last run: new saves and expansions queue a task; renewal-window entries alert."""
    new_save, new_expand, entered_window, task_ids = [], [], [], []
    for x in results:
        key = STATE_PREFIX + x["account_id"]
        prev = ctx.store.get_state(key) or {}
        if x["recommendation"] != prev.get("recommendation"):
            if x["recommendation"] == "save":
                new_save.append(x)
            elif x["recommendation"] == "expand":
                new_expand.append(x)
            if queue and x["recommendation"] in ("save", "expand"):
                rid = queue_task(ctx, x, now)
                if rid:
                    task_ids.append(rid)
        if x["renewal_window"] and not prev.get("renewal_window") and x["band"] != "healthy":
            entered_window.append(x)
        ctx.store.set_state(key, {"recommendation": x["recommendation"], "band": x["band"],
                                  "renewal_window": x["renewal_window"], "at": _iso(now)})
    return {"new_save": new_save, "new_expand": new_expand, "entered_renewal_window": entered_window,
            "tasks_queued": task_ids}


# ---------- formatting ----------
def money(v) -> str:
    return f"${v:,.0f}" if v is not None else "n/a"


def format_one(x: dict) -> str:
    lines = [f"*{x['name']}* | {x['recommendation'].upper()} | risk {x['risk']} ({x['band']}) | expansion {x['expansion']}",
             f"ARR {money(x['arr'])} | renewal {x['renewal_date'] or 'unknown'}"
             + (f" ({x['days_to_renewal']} days)" if x["days_to_renewal"] is not None else "") + f" | owner {x['owner'] or 'none'}"]
    if x["risk_drivers"]:
        lines.append("Risk: " + "; ".join(x["risk_drivers"][:4]))
    if x["expansion_drivers"]:
        lines.append("Expansion: " + "; ".join(x["expansion_drivers"][:4]))
    if x["actions"]:
        lines.append("Next: " + " | ".join(x["actions"]))
    return "\n".join(lines)


def portfolio(results: list[dict]) -> dict:
    def tot(xs):
        return round(sum(x["arr"] or 0 for x in xs), 2)
    at_risk = [x for x in results if x["band"] == "at_risk"]
    watch = [x for x in results if x["band"] == "watch"]
    exp = [x for x in results if x["recommendation"] == "expand"]
    return {"customers": len(results), "arr": tot(results),
            "at_risk": {"count": len(at_risk), "arr": tot(at_risk)}, "watch": {"count": len(watch), "arr": tot(watch)},
            "expand": {"count": len(exp), "arr": tot(exp)},
            "renewing_in_window": {"count": sum(1 for x in results if x["renewal_window"]),
                                   "arr": tot([x for x in results if x["renewal_window"]])}}


def format_report(results: list[dict], size: int = 10) -> str:
    p = portfolio(results)
    lines = [f"*Account Health* | {p['customers']} customers | {money(p['arr'])} ARR",
             f"At risk {p['at_risk']['count']} ({money(p['at_risk']['arr'])}) | watch {p['watch']['count']} "
             f"({money(p['watch']['arr'])}) | expansion plays {p['expand']['count']} ({money(p['expand']['arr'])}) | "
             f"renewing in window {p['renewing_in_window']['count']} ({money(p['renewing_in_window']['arr'])})"]
    saves = [x for x in results if x["recommendation"] == "save"][:size]
    if saves:
        lines.append("Save first:")
        lines += [f"{i}. {x['name']} ({x['owner'] or 'no owner'}) risk {x['risk']}, renews {x['renewal_date'] or 'unknown'}: "
                  + "; ".join(x["risk_drivers"][:2]) for i, x in enumerate(saves, 1)]
    exps = sorted([x for x in results if x["recommendation"] == "expand"], key=lambda x: -x["expansion"])[:size]
    if exps:
        lines.append("Expand:")
        lines += [f"{i}. {x['name']} ({x['owner'] or 'no owner'}) expansion {x['expansion']}: "
                  + "; ".join(x["expansion_drivers"][:2]) for i, x in enumerate(exps, 1)]
    watch = [x for x in results if x["recommendation"] == "watch"][:size]
    if watch:
        lines.append("Watch: " + "; ".join(f"{x['name']} ({x['risk']})" for x in watch))
    return "\n".join(lines)


def find(ctx, ref: str) -> dict | None:
    a = resolve_account(ctx, ref)
    return a if a and is_customer(ctx, a) else None
