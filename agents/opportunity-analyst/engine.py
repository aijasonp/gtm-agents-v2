"""Opportunity Analyst engine: every number about open, won and lost opportunities, computed in code.

Reads the `deals` table (all history after a Salesforce sync), deal attrs (type, lead source, loss reason,
competitor, account name, any custom fields pulled), `accounts` (industry, size) and stage history
(`deal_stage_history` from the CRM, else the store's own `deal_history` snapshots).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import yaml

from gtm_core import pipeline

MAX_ROWS = 200
ROW_KEYS = ("id", "name", "account", "owner", "stage", "status", "amount", "close_date", "created_at", "type",
            "lead_source", "loss_reason", "competitor", "forecast_category")


# ---------------- basics ----------------
def now(at: datetime | None = None) -> datetime:
    return at or datetime.now(timezone.utc)


def amt(d: dict) -> float:
    try:
        return float(d.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def status(d: dict) -> str:
    if pipeline.is_won(d):
        return "won"
    if pipeline.is_lost(d):
        return "lost"
    return "open" if pipeline.is_open(d) else (d.get("status") or "open").lower()


def day(v) -> datetime | None:
    return pipeline.parse_dt(v)


def window(since: str = "", until: str = "", at: datetime | None = None, default_days: int = 365):
    """Inclusive since, exclusive until. since accepts an ISO date or 'Nd' (last N days)."""
    end = day(until) if until else now(at)
    if since and since.endswith("d") and since[:-1].isdigit():
        start = end - timedelta(days=int(since[:-1]))
    else:
        start = day(since) if since else end - timedelta(days=default_days)
    return start, end


def stages_config(ctx) -> dict:
    path = ctx.manifest.path(ctx.manifest.config.get("stages", "")) if ctx.manifest.config.get("stages") else None
    if path and path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def stage_key(raw: str | None, cfg: dict) -> str | None:
    s = (raw or "").strip().lower()
    if not s or "closed" in s or s in ("won", "lost"):
        return None
    for key, aliases in (cfg.get("stage_aliases") or {}).items():
        for a in [key, *aliases]:
            if s == a.lower() or a.lower() in s:
                return key
    return s


def deals(ctx) -> list[dict]:
    rows = ctx.store.select("deals")
    accts = {a["id"]: a for a in ctx.store.query("SELECT id, name, industry, employees, country FROM accounts")}
    for d in rows:
        a = accts.get(d.get("account_id")) or {}
        d["account"] = d.get("account_name") or a.get("name") or d.get("account_id")
        d["industry"] = d.get("industry") or a.get("industry")
        d["employees"] = d.get("employees") or a.get("employees")
        d["_status"] = status(d)
    return rows


def history(ctx) -> dict[str, list[dict]]:
    """deal_id -> [{stage, at}] oldest first. CRM history wins; store snapshots fill deals with none."""
    out: dict[str, list[dict]] = defaultdict(list)
    for h in ctx.store.query("SELECT deal_id, stage, changed_at FROM deal_stage_history ORDER BY changed_at"):
        out[h["deal_id"]].append({"stage": h["stage"], "at": h["changed_at"]})
    for h in ctx.store.query("SELECT deal_id, stage, snapshot_at FROM deal_history ORDER BY snapshot_at"):
        if h["deal_id"] not in out or out[h["deal_id"]][0].get("_snap"):
            out[h["deal_id"]].append({"stage": h["stage"], "at": h["snapshot_at"], "_snap": True})
    return out


def row(d: dict) -> dict:
    r = {k: d.get(k) for k in ROW_KEYS if d.get(k) not in (None, "")}
    r["status"] = d["_status"]
    return r


def segment(d: dict) -> str:
    n = d.get("employees")
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "unknown"
    return "SMB (<200)" if n < 200 else "Mid-market (200-1999)" if n < 2000 else "Enterprise (2000+)"


def group_value(d: dict, by: str, hist: dict, cfg: dict) -> str:
    cd = (d.get("close_date") or "")[:10]
    if by == "close_month":
        return cd[:7] or "none"
    if by == "close_quarter":
        dt = day(cd)
        return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}" if dt else "none"
    if by == "created_month":
        return (d.get("created_at") or "")[:7] or "none"
    if by == "segment":
        return segment(d)
    if by == "stage_lost":
        return last_open_stage(d, hist, cfg) or "unknown"
    v = d.get(by)
    return str(v) if v not in (None, "") else "none"


def last_open_stage(d: dict, hist: dict, cfg: dict) -> str | None:
    for h in reversed(hist.get(d["id"], [])):
        k = stage_key(h["stage"], cfg)
        if k:
            return k
    return None


def cycle_days(d: dict) -> int | None:
    a, b = day(d.get("created_at")), day(d.get("close_date"))
    return (b - a).days if a and b and b >= a else None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def tally(ds: list[dict]) -> dict:
    won = [d for d in ds if d["_status"] == "won"]
    lost = [d for d in ds if d["_status"] == "lost"]
    wa, la = sum(map(amt, won)), sum(map(amt, lost))
    closed = len(won) + len(lost)
    return {"won": len(won), "won_amount": round(wa, 2), "lost": len(lost), "lost_amount": round(la, 2),
            "win_rate": round(len(won) / closed, 3) if closed else None,
            "win_rate_amount": round(wa / (wa + la), 3) if wa + la else None,
            "avg_won_size": round(wa / len(won), 2) if won else None,
            "avg_cycle_days_won": _avg([cycle_days(d) for d in won]),
            "avg_cycle_days_lost": _avg([cycle_days(d) for d in lost])}


def in_window(d: dict, start, end, field: str = "close_date") -> bool:
    t = day(d.get(field))
    return bool(t and start <= t < end)


# ---------------- tools' logic ----------------
def list_opps(ctx, status="", stage="", owner="", search="", since="", until="", date_field="close_date",
              min_amount=0.0, sort="amount", limit=25, at=None) -> dict:
    rows = deals(ctx)
    if status:
        want = {s.strip().lower() for s in status.split(",")}
        rows = [d for d in rows if d["_status"] in want]
    if stage:
        rows = [d for d in rows if stage.lower() in (d.get("stage") or "").lower()]
    if owner:
        rows = [d for d in rows if owner.lower() in (d.get("owner") or "").lower()]
    if search:
        q = search.lower()
        rows = [d for d in rows if q in (d.get("name") or "").lower() or q in str(d.get("account") or "").lower()]
    if since or until:
        start, end = window(since, until, at)
        rows = [d for d in rows if in_window(d, start, end, date_field)]
    if min_amount:
        rows = [d for d in rows if amt(d) >= float(min_amount)]
    key = {"amount": lambda d: -amt(d), "close_date": lambda d: d.get("close_date") or "",
           "created_at": lambda d: d.get("created_at") or ""}.get(sort, lambda d: -amt(d))
    rows.sort(key=key)
    n = max(1, min(int(limit or 25), MAX_ROWS))
    return {"count": len(rows), "total_amount": round(sum(map(amt, rows)), 2), "shown": min(n, len(rows)),
            "opportunities": [row(d) for d in rows[:n]]}


def win_loss(ctx, since="", until="", group_by="", at=None) -> dict:
    start, end = window(since, until, at)
    closed = [d for d in deals(ctx) if d["_status"] in ("won", "lost") and in_window(d, start, end)]
    out = {"window": [start.date().isoformat(), end.date().isoformat()], "closed": len(closed), **tally(closed)}
    if group_by:
        hist, cfg = history(ctx), stages_config(ctx)
        groups: dict[str, list] = defaultdict(list)
        for d in closed:
            groups[group_value(d, group_by, hist, cfg)].append(d)
        out["by"] = group_by
        out["groups"] = sorted(({"key": k, "closed": len(v), **tally(v)} for k, v in groups.items()),
                               key=lambda g: -(g["won_amount"] + g["lost_amount"]))
    return out


def loss_analysis(ctx, since="", until="", top=10, at=None) -> dict:
    start, end = window(since, until, at)
    hist, cfg = history(ctx), stages_config(ctx)
    lost = [d for d in deals(ctx) if d["_status"] == "lost" and in_window(d, start, end)]

    def breakdown(by):
        g: dict[str, list] = defaultdict(list)
        for d in lost:
            g[group_value(d, by, hist, cfg)].append(d)
        return sorted(({"key": k, "count": len(v), "amount": round(sum(map(amt, v)), 2)} for k, v in g.items()),
                      key=lambda x: (-x["amount"], -x["count"]))

    has_reason = any(d.get("loss_reason") for d in lost)
    out = {"window": [start.date().isoformat(), end.date().isoformat()], "lost": len(lost),
           "lost_amount": round(sum(map(amt, lost)), 2), "avg_cycle_days": _avg([cycle_days(d) for d in lost]),
           "by_reason": breakdown("loss_reason") if has_reason else [],
           "by_competitor": breakdown("competitor") if any(d.get("competitor") for d in lost) else [],
           "by_stage_lost": breakdown("stage_lost"), "by_owner": breakdown("owner"), "by_type": breakdown("type"),
           "largest": [row(d) for d in sorted(lost, key=lambda d: -amt(d))[:max(1, min(int(top), 50))]]}
    if not has_reason:
        out["note"] = ("no loss reason field found on these deals; set SALESFORCE_LOSS_REASON_FIELD "
                       "and run a full sync")
    return out


def open_pipeline(ctx, group_by="stage", owner="", at=None) -> dict:
    t = now(at)
    rows = [d for d in deals(ctx) if d["_status"] == "open"
            and (not owner or owner.lower() in (d.get("owner") or "").lower())]
    hist, cfg = history(ctx), stages_config(ctx)
    g: dict[str, list] = defaultdict(list)
    for d in rows:
        g[group_value(d, group_by or "stage", hist, cfg)].append(d)
    past_due = [d for d in rows if day(d.get("close_date")) and day(d.get("close_date")) < t]
    return {"as_of": t.date().isoformat(), "open": len(rows), "open_amount": round(sum(map(amt, rows)), 2),
            "past_due_close": {"count": len(past_due), "amount": round(sum(map(amt, past_due)), 2)},
            "by": group_by or "stage",
            "groups": sorted(({"key": k, "count": len(v), "amount": round(sum(map(amt, v)), 2)} for k, v in g.items()),
                             key=lambda x: -x["amount"])}


def stage_conversion(ctx, since="", until="", at=None) -> dict:
    """Of deals created in the window: how many reached each stage, moved to the next, and won."""
    start, end = window(since, until, at)
    cfg = stages_config(ctx)
    order = list(cfg.get("order") or [])
    hist = history(ctx)
    cohort = [d for d in deals(ctx) if in_window(d, start, end, "created_at")]
    reached: dict[str, list] = defaultdict(list)
    dwell: dict[str, list] = defaultdict(list)
    for d in cohort:
        keys = [stage_key(h["stage"], cfg) for h in hist.get(d["id"], [])] + [stage_key(d.get("stage"), cfg)]
        keys = [k for k in keys if k]
        idx = [order.index(k) for k in keys if k in order]
        top = max(idx) if idx else -1
        seen = set(order[:top + 1]) | set(keys)  # reaching a later stage implies the earlier ones
        for k in seen:
            reached[k].append(d)
        h = [x for x in hist.get(d["id"], []) if not x.get("_snap")]
        for a, b in zip(h, h[1:]):
            ka, ta, tb = stage_key(a["stage"], cfg), day(a["at"]), day(b["at"])
            if ka and ta and tb and stage_key(b["stage"], cfg) != ka:
                dwell[ka].append((tb - ta).days)
    stages = order + sorted(k for k in reached if k not in order)
    out = []
    for i, k in enumerate(stages):
        ds = reached.get(k, [])
        if not ds and k not in order:
            continue
        nxt = stages[i + 1] if i + 1 < len(order) and k in order else None
        nxt_ids = {x["id"] for x in reached.get(nxt, [])} if nxt else set()
        to_next = len([d for d in ds if d["id"] in nxt_ids]) if nxt else None
        t = tally(ds)
        out.append({"stage": k, "reached": len(ds), "to_next": to_next,
                    "to_next_rate": round(to_next / len(ds), 3) if nxt and ds else None,
                    "won": t["won"], "lost": t["lost"], "win_rate_from_stage": t["win_rate"],
                    "avg_days_in_stage": _avg(dwell.get(k, []))})
    return {"window": [start.date().isoformat(), end.date().isoformat()], "cohort": len(cohort),
            "history_source": "crm" if ctx.store.one("SELECT 1 AS x FROM deal_stage_history") else "snapshots",
            "stages": out}


def trend(ctx, periods=6, by="month", at=None) -> dict:
    t = now(at)
    ds = deals(ctx)

    def key(v):
        dt = day(v)
        if not dt:
            return None
        return f"{dt.year}-{dt.month:02d}" if by == "month" else f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"

    keys, cur = [], datetime(t.year, t.month, 1, tzinfo=timezone.utc)
    step = 1 if by == "month" else 3
    if by != "month":
        cur = datetime(t.year, (t.month - 1) // 3 * 3 + 1, 1, tzinfo=timezone.utc)
    for _ in range(max(1, min(int(periods), 24))):
        keys.append(key(cur))
        m = cur.month - step
        cur = cur.replace(year=cur.year + (m - 1) // 12, month=(m - 1) % 12 + 1)
    keys.reverse()
    out = []
    for k in keys:
        created = [d for d in ds if key(d.get("created_at")) == k]
        closed = [d for d in ds if d["_status"] in ("won", "lost") and key(d.get("close_date")) == k]
        t2 = tally(closed)
        out.append({"period": k, "created": len(created), "created_amount": round(sum(map(amt, created)), 2),
                    "won": t2["won"], "won_amount": t2["won_amount"], "lost": t2["lost"],
                    "lost_amount": t2["lost_amount"], "win_rate": t2["win_rate"]})
    return {"by": by, "periods": out}


def detail(ctx, deal: str) -> dict:
    q = (deal or "").strip().lower()
    ds = deals(ctx)
    hit = [d for d in ds if q in ((d.get("id") or "").lower(), (d.get("crm_id") or "").lower())]
    hit = hit or [d for d in ds if q and q in (d.get("name") or "").lower()]
    if not hit:
        return {"error": f"no opportunity matches '{deal}'"}
    if len(hit) > 1:
        return {"matches": [row(d) for d in hit[:10]], "note": "more than one match; ask again with the id"}
    d = hit[0]
    hist = ctx.store.query("SELECT stage, amount, close_date, forecast_category, changed_at FROM deal_stage_history "
                           "WHERE deal_id=? ORDER BY changed_at", (d["id"],))
    rec = {k: v for k, v in d.items() if not k.startswith("_") and v not in (None, "") and k != "meddpicc"}
    rec["status"] = d["_status"]
    return {"opportunity": rec, "cycle_days": cycle_days(d), "stage_history": hist[-30:]}
