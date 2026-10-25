"""Product Marketing engine: deterministic aggregation of field evidence into enablement.

Inputs (all in the customer's store):
  insights   competitor_mention (key=competitor), objection (key=category), written by Meeting Intelligence
  deals      won/lost outcomes, meddpicc.competition evidence, optional loss_reason / win_reason attrs
  accounts   industry and headcount for segment cuts
  contacts   function, to tie objections to a persona
  company.yaml  competitors, value props, proof points, personas

Nothing here invents a competitor capability. Facts come from evidence or company.yaml; the rest is
listed under "to verify". The model (writer.narrate) only polishes one summary sentence per card.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from gtm_core import meddpicc, pipeline, profile, writer

OBJECTION_QUESTIONS = {
    "price": "What are you comparing the cost to: another tool, a hire, or doing nothing?",
    "timing": "What has to happen before this becomes a priority, and when is that?",
    "authority": "Who else weighs in on this, and what does each of them care about?",
    "competition": "What do you like about what you use today, and what made you take this call anyway?",
    "need": "How do you handle this today, and what does that cost you each month?",
    "security": "What is on your security review checklist, and who owns it?",
    "integration": "Which systems must this connect to, and who owns them?",
}
PERSONA_VALUE_PROP = {"sales": "prioritization", "revops": "deal_hygiene", "executive": "deal_hygiene"}


# ---------------------------------------------------------------- helpers
def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _days(ctx, since_days: int | None) -> int:
    return int(since_days or ctx.manifest.config.get("default_since_days", 90))


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _in(v, start: datetime, end: datetime) -> bool:
    return pipeline.in_period(v, start, end)


def company_competitors(ctx) -> list[dict]:
    out = []
    for c in profile.company(ctx).get("competitors", []):
        out.append(c if isinstance(c, dict) else {"name": str(c)})
    return out


def _known(ctx, competitor: str) -> dict | None:
    return next((c for c in company_competitors(ctx) if _norm(c.get("name")) == _norm(competitor)), None)


def _insights(ctx, kind: str, start: datetime | None = None, end: datetime | None = None) -> list[dict]:
    rows = ctx.store.insights(kind)
    if start is None:
        return rows
    return [r for r in rows if _in(r.get("observed_at"), start, end)]


def _account(ctx, account_id: str | None) -> dict:
    return (ctx.store.account(account_id) if account_id else None) or {}


def size_band(employees) -> str:
    try:
        n = int(employees)
    except (TypeError, ValueError):
        return "unknown"
    if n >= 1000:
        return "enterprise"
    if n >= 200:
        return "mid_market"
    return "small"


def _deal_text(deal: dict) -> str:
    """Every free-text field on a closed deal that may name a competitor or a reason."""
    m = meddpicc.normalize(deal.get("meddpicc"))
    parts = [m["competition"]["evidence"], deal.get("loss_reason"), deal.get("win_reason"), deal.get("competitor"),
             deal.get("reason")]
    return " | ".join(str(p) for p in parts if p)


def _mentions_name(text: str, name: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(_norm(name)) + r"(?![a-z0-9])", _norm(text)))


def deal_competitors(ctx, deal: dict, mention_deals: dict[str, set] | None = None) -> set[str]:
    """Competitors tied to a deal: named in its competition evidence / reasons, or mentioned on its calls."""
    names = {c["name"] for c in company_competitors(ctx)}
    if mention_deals:
        names |= set(mention_deals)
    text = _deal_text(deal)
    found = {n for n in names if text and _mentions_name(text, n)}
    for n, ids in (mention_deals or {}).items():
        if deal["id"] in ids:
            found.add(n)
    return found


def _mention_index(ctx) -> dict[str, set]:
    """competitor display name -> deal ids where it was mentioned on a call (all time)."""
    idx: dict[str, set] = {}
    canon = {_norm(c["name"]): c["name"] for c in company_competitors(ctx)}
    for r in _insights(ctx, "competitor_mention"):
        name = canon.get(_norm(r["key"]), r["key"])
        idx.setdefault(name, set())
        if r.get("deal_id"):
            idx[name].add(r["deal_id"])
    return idx


def closed_deals(ctx, start: datetime, end: datetime) -> list[dict]:
    out = []
    for d in ctx.store.select("deals"):
        if not (pipeline.is_won(d) or pipeline.is_lost(d)):
            continue
        if _in(d.get("close_date") or d.get("updated_at"), start, end):
            out.append(d)
    return out


def cycle_days(deal: dict) -> int | None:
    a, b = pipeline.parse_dt(deal.get("created_at")), pipeline.parse_dt(deal.get("close_date"))
    return (b - a).days if a and b and b >= a else None


def _objections_on(ctx, deal_ids: set) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in _insights(ctx, "objection"):
        if r.get("deal_id") in deal_ids:
            out.setdefault(r["key"], []).append(r)
    return out


def _is_bare_name(ctx, text: str) -> bool:
    """True when competition evidence is only a competitor name (says who, not why)."""
    t = _norm(re.sub(r"^confirmed:\s*", "", text or "", flags=re.I))
    names = {_norm(c["name"]) for c in company_competitors(ctx)} | {_norm(k) for k in _mention_index(ctx)}
    return t in names


def deal_reason(ctx, deal: dict) -> str:
    """Why a closed deal went the way it did: CRM reason first, then competition evidence that says why,
    then (won deals) the value the buyer confirmed, then the top objection on its calls."""
    for k in ("loss_reason", "win_reason", "reason"):
        if deal.get(k):
            return str(deal[k])
    m = meddpicc.normalize(deal.get("meddpicc"))
    ev = m["competition"]["evidence"]
    if ev and not _is_bare_name(ctx, ev):
        return ev
    if pipeline.is_won(deal) and m["metrics"]["evidence"]:
        return f"value proven: {m['metrics']['evidence']}"
    objs = _objections_on(ctx, {deal["id"]})
    if objs:
        top = max(objs, key=lambda k: len(objs[k]))
        return f"objection: {top}"
    return "no reason recorded"


@lru_cache(maxsize=8)
def _responses(path: str) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    out, cur, buf = {}, None, []
    for line in p.read_text().splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur:
                out[cur] = " ".join(buf).strip()
            cur, buf = _norm(m.group(1)), []
        elif cur is not None and line.strip():
            buf.append(line.strip())
    if cur:
        out[cur] = " ".join(buf).strip()
    return out


def responses(ctx) -> dict[str, str]:
    return _responses(str(ctx.manifest.path(ctx.manifest.config.get(
        "objection_responses", "skill/references/objection-responses.md"))))


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text or "")
    return m.group(1) if m else (text or "")


def _trend(cur: int, prev: int) -> str:
    if prev == 0:
        return "new" if cur else "none"
    if cur > prev:
        return "up"
    if cur < prev:
        return "down"
    return "flat"


# ---------------------------------------------------------------- competitor intel
def competitor_intel(ctx, competitor: str, since_days: int | None = None, now: datetime | None = None) -> dict:
    days = _days(ctx, since_days)
    end = _now(now)
    start, prev_start = end - timedelta(days=days), end - timedelta(days=2 * days)
    known = _known(ctx, competitor)
    name = known["name"] if known else competitor

    def is_comp(r):
        return _norm(r["key"]) == _norm(name)

    cur = [r for r in _insights(ctx, "competitor_mention", start, end) if is_comp(r)]
    prev = [r for r in _insights(ctx, "competitor_mention", prev_start, start) if is_comp(r)]
    idx = _mention_index(ctx)
    closed = [d for d in closed_deals(ctx, start, end) if name in deal_competitors(ctx, d, idx)]
    won = [d for d in closed if pipeline.is_won(d)]
    lost = [d for d in closed if pipeline.is_lost(d)]
    deal_ids = {r["deal_id"] for r in cur if r.get("deal_id")} | {d["id"] for d in closed}
    accounts = sorted({r["account_id"] for r in cur if r.get("account_id")} | {d["account_id"] for d in closed if d.get("account_id")})
    objs = _objections_on(ctx, deal_ids)
    top_objs = sorted(((k, len(v)) for k, v in objs.items()), key=lambda kv: (-kv[1], kv[0]))

    quotes = []
    for r in sorted(cur, key=lambda r: r.get("observed_at") or "", reverse=True):
        if r.get("evidence"):
            quotes.append({"date": (r.get("observed_at") or "")[:10], "account_id": r.get("account_id"),
                           "deal_id": r.get("deal_id"), "quote": r["evidence"]})
    for d in lost + won:
        ev = meddpicc.normalize(d.get("meddpicc"))["competition"]["evidence"]
        if ev and not _is_bare_name(ctx, ev) and ev not in [q["quote"] for q in quotes]:
            quotes.append({"date": str(d.get("close_date") or "")[:10], "account_id": d.get("account_id"),
                           "deal_id": d["id"], "quote": ev, "outcome": "won" if pipeline.is_won(d) else "lost"})
    quotes = quotes[:5]

    to_verify = ["Their pricing, packaging and feature claims (no evidence on file)"]
    if not known:
        to_verify.insert(0, f"{name} is not in company.yaml competitors: add positioning")
    if not closed:
        to_verify.append("Win rate: no closed deals against them in this period")
    win_rate = round(len(won) / len(closed), 2) if closed else None
    return {
        "competitor": name, "known": bool(known), "since_days": days,
        "positioning": (known or {}).get("positioning") or "to verify",
        "mentions": len(cur), "mentions_prev": len(prev), "trend": _trend(len(cur), len(prev)),
        "accounts": accounts, "deals": sorted(deal_ids),
        "won": [{"id": d["id"], "name": d.get("name"), "amount": d.get("amount"), "reason": deal_reason(ctx, d)} for d in won],
        "lost": [{"id": d["id"], "name": d.get("name"), "amount": d.get("amount"), "reason": deal_reason(ctx, d)} for d in lost],
        "win_rate": win_rate, "top_objections": [{"category": k, "count": n} for k, n in top_objs[:5]],
        "quotes": quotes, "to_verify": to_verify,
    }


# ---------------------------------------------------------------- win / loss
def win_loss(ctx, since_days: int | None = None, now: datetime | None = None) -> dict:
    days = _days(ctx, since_days)
    end = _now(now)
    start = end - timedelta(days=days)
    deals = closed_deals(ctx, start, end)
    idx = _mention_index(ctx)
    won = [d for d in deals if pipeline.is_won(d)]
    lost = [d for d in deals if pipeline.is_lost(d)]

    def tally(groups: dict, key: str, d: dict):
        g = groups.setdefault(key, {"won": 0, "lost": 0, "won_amount": 0.0, "lost_amount": 0.0})
        side = "won" if pipeline.is_won(d) else "lost"
        g[side] += 1
        g[f"{side}_amount"] += float(d.get("amount") or 0)

    by_comp, by_ind, by_size = {}, {}, {}
    rows = []
    for d in deals:
        comps = deal_competitors(ctx, d, idx) or {"none named"}
        for c in comps:
            tally(by_comp, c, d)
        acct = _account(ctx, d.get("account_id"))
        tally(by_ind, acct.get("industry") or "unknown", d)
        tally(by_size, size_band(acct.get("employees")), d)
        rows.append({"id": d["id"], "name": d.get("name"), "outcome": "won" if pipeline.is_won(d) else "lost",
                     "amount": d.get("amount"), "competitors": sorted(comps), "reason": deal_reason(ctx, d),
                     "cycle_days": cycle_days(d)})
    for g in list(by_comp.values()) + list(by_ind.values()) + list(by_size.values()):
        n = g["won"] + g["lost"]
        g["win_rate"] = round(g["won"] / n, 2) if n else None

    def avg(ds):
        vals = [c for c in (cycle_days(d) for d in ds) if c is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    loss_objs = _objections_on(ctx, {d["id"] for d in lost})
    return {
        "since_days": days, "won": len(won), "lost": len(lost),
        "won_amount": round(sum(float(d.get("amount") or 0) for d in won), 2),
        "lost_amount": round(sum(float(d.get("amount") or 0) for d in lost), 2),
        "win_rate": round(len(won) / len(deals), 2) if deals else None,
        "avg_cycle_days_won": avg(won), "avg_cycle_days_lost": avg(lost),
        "by_competitor": by_comp, "by_industry": by_ind, "by_size": by_size,
        "loss_reasons": [r["reason"] for r in rows if r["outcome"] == "lost"],
        "win_reasons": [r["reason"] for r in rows if r["outcome"] == "won"],
        "objections_on_losses": {k: len(v) for k, v in sorted(loss_objs.items(), key=lambda kv: -len(kv[1]))},
        "deals": rows,
    }


# ---------------------------------------------------------------- objection library
def objection_library(ctx, since_days: int | None = None, now: datetime | None = None) -> dict:
    days = _days(ctx, since_days)
    end = _now(now)
    start = end - timedelta(days=days)
    resp = responses(ctx)
    groups: dict[str, list[dict]] = {}
    for r in _insights(ctx, "objection", start, end):
        groups.setdefault(_norm(r["key"]), []).append(r)
    min_freq = int(ctx.manifest.config.get("frequent_objection_min", 2))
    rows = []
    for cat, items in groups.items():
        quotes = []
        for r in items:
            if r.get("evidence") and r["evidence"] not in quotes:
                quotes.append(r["evidence"])
        have = resp.get(cat, "")
        rows.append({"category": cat, "count": len(items), "deals": sorted({r["deal_id"] for r in items if r.get("deal_id")}),
                     "accounts": sorted({r["account_id"] for r in items if r.get("account_id")}),
                     "quotes": quotes[:3], "response": have,
                     "question": OBJECTION_QUESTIONS.get(cat, ""), "gap": len(items) >= min_freq and not have})
    rows.sort(key=lambda r: (-r["count"], r["category"]))
    return {"since_days": days, "total": sum(r["count"] for r in rows), "categories": rows,
            "gaps": [r["category"] for r in rows if r["gap"]]}


# ---------------------------------------------------------------- battlecard
def _reason_counts(reasons: list[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for r in reasons:
        if r and r != "no reason recorded":
            counts[r] = counts.get(r, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def build_battlecard(ctx, competitor: str, since_days: int | None = None, now: datetime | None = None) -> dict:
    intel = competitor_intel(ctx, competitor, since_days, now)
    lib = {r["category"]: r for r in objection_library(ctx, since_days, now)["categories"]}
    resp = responses(ctx)
    lost_ids = {d["id"] for d in intel["lost"]}
    lost_objs = _objections_on(ctx, lost_ids)

    they_win = [f"{r} ({n})" for r, n in _reason_counts([d["reason"] for d in intel["lost"]])]
    they_win += [f"objection on lost deals: {k} ({len(v)})" for k, v in sorted(lost_objs.items(), key=lambda kv: -len(kv[1]))]
    we_win = [f"{r} ({n})" for r, n in _reason_counts([d["reason"] for d in intel["won"]])]
    cats = [o["category"] for o in intel["top_objections"]] or ["competition"]
    landmines = [OBJECTION_QUESTIONS[c] for c in cats if c in OBJECTION_QUESTIONS][:4]
    handling = []
    for o in intel["top_objections"]:
        text = resp.get(o["category"])
        handling.append({"category": o["category"], "count": o["count"],
                         "response": _first_sentence(text) if text else "No prepared response: add one to objection-responses.md"})
    proof = list(profile.company(ctx).get("proof_points", []))
    to_verify = list(intel["to_verify"])
    if not they_win:
        to_verify.append("Where they win: no lost deals or loss reasons on file")
    if not we_win:
        to_verify.append("Where we win: no won deals against them on file")
    if not proof:
        to_verify.append("Proof: no approved proof points in company.yaml")

    wr = f"{int(intel['win_rate'] * 100)}%" if intel["win_rate"] is not None else "no closed deals yet"
    summary_fallback = (f"{intel['competitor']}: {intel['mentions']} mentions in {intel['since_days']} days "
                        f"({intel['trend']}), record {len(intel['won'])}-{len(intel['lost'])}, win rate {wr}.")
    facts = {"competitor": intel["competitor"], "positioning": intel["positioning"], "mentions": intel["mentions"],
             "trend": intel["trend"], "won": len(intel["won"]), "lost": len(intel["lost"]), "win_rate": wr,
             "where_they_win": they_win, "where_we_win": we_win, "top_objections": intel["top_objections"]}
    summary, source = writer.narrate(ctx, "Write a two sentence snapshot for a sales battlecard from these facts only.",
                                     facts, summary_fallback, max_words=60)
    return {"competitor": intel["competitor"], "built_at": _now(now).replace(microsecond=0).isoformat(),
            "since_days": intel["since_days"], "summary": summary, "summary_source": source,
            "positioning": intel["positioning"], "accounts": intel["accounts"], "mentions": intel["mentions"],
            "mentions_prev": intel["mentions_prev"], "trend": intel["trend"], "won": len(intel["won"]),
            "lost": len(intel["lost"]), "win_rate": intel["win_rate"], "where_they_win": they_win,
            "where_we_win": we_win, "landmines": landmines, "objection_handling": handling, "proof": proof,
            "evidence": intel["quotes"], "to_verify": to_verify,
            "objection_gaps": [c for c in cats if lib.get(c, {}).get("gap")]}


def render_battlecard(card: dict) -> str:
    wr = f"{int(card['win_rate'] * 100)}%" if card["win_rate"] is not None else "no closed deals yet"
    L = [f"Battlecard: {card['competitor']}   (built {card['built_at'][:10]} from {card['mentions']} mentions, "
         f"{card['won']} wins, {card['lost']} losses in {card['since_days']} days)", "",
         card["summary"], "", "Snapshot",
         f"  Their positioning (from company.yaml): {card['positioning']}",
         f"  Seen on: {', '.join(card['accounts']) or 'none'}  | Mentions: {card['mentions']} "
         f"(prev {card['mentions_prev']}, {card['trend']})",
         f"  Record vs them: {card['won']}-{card['lost']} (win rate {wr})", ""]

    def section(title, items, empty):
        L.append(title)
        L.extend(f"  - {i}" for i in items) if items else L.append(f"  - {empty}")
        L.append("")

    section("Where they win", card["where_they_win"], "no evidence yet")
    section("Where we win", card["where_we_win"], "no evidence yet")
    section("Landmines and questions to ask", card["landmines"], "no objections on file yet")
    section("Objection handling", [f"{h['category']} ({h['count']}): {h['response']}" for h in card["objection_handling"]],
            "no objections on file yet")
    section("Proof", card["proof"], "No approved proof: add one")
    section("Evidence log", [f"{q['date']} {q.get('account_id') or ''}: \"{q['quote']}\"" for q in card["evidence"]],
            "no quotes yet")
    section("To verify", card["to_verify"], "nothing open")
    return "\n".join(L).rstrip() + "\n"


def battlecard(ctx, competitor: str, since_days: int | None = None, now: datetime | None = None,
               persist: bool = True) -> dict:
    card = build_battlecard(ctx, competitor, since_days, now)
    text = render_battlecard(card)
    out = {**card, "text": text}
    if persist:
        ctx.store.add_insight(ctx.manifest.id, "battlecard", card["competitor"], value=card, evidence=card["summary"],
                              observed_at=card["built_at"])
        out["draft_id"] = ctx.store.add_draft(ctx.manifest.id, "battlecard", text, subject=f"Battlecard: {card['competitor']}",
                                              source=card["summary_source"], meta={"competitor": card["competitor"]})
    return out


# ---------------------------------------------------------------- messaging and launch
def _value_prop(ctx, function: str) -> dict:
    vps = profile.company(ctx).get("value_props", [])
    pref = PERSONA_VALUE_PROP.get(function)
    return next((v for v in vps if v.get("id") == pref), vps[0] if vps else {})


def messaging_brief(ctx, persona_function: str, segment: str = "", since_days: int | None = None,
                    now: datetime | None = None) -> dict:
    comp = profile.company(ctx)
    fn = _norm(persona_function)
    vp = _value_prop(ctx, fn)
    others = [v for v in comp.get("value_props", []) if v is not vp]
    accounts = {c["account_id"] for c in ctx.store.select("contacts", "function=?", (fn,)) if c.get("account_id")}
    if segment:
        accounts = {a for a in accounts if size_band(_account(ctx, a).get("employees")) == _norm(segment)}
    deal_ids = {d["id"] for d in ctx.store.select("deals") if d.get("account_id") in accounts}
    lib = objection_library(ctx, since_days, now)["categories"]
    persona_objs = []
    for r in lib:
        n = len(set(r["deals"]) & deal_ids)
        if n:
            persona_objs.append({"category": r["category"], "deals": n, "response": _first_sentence(r["response"]),
                                 "quote": r["quotes"][0] if r["quotes"] else ""})
    persona_objs.sort(key=lambda r: -r["deals"])
    flags = []
    if not comp.get("proof_points"):
        flags.append("missing proof: no approved proof points in company.yaml")
    if not persona_objs:
        flags.append(f"no call evidence yet for {fn} buyers{' in ' + segment if segment else ''}; objections below are general")
        persona_objs = [{"category": r["category"], "deals": len(r["deals"]), "response": _first_sentence(r["response"]),
                         "quote": r["quotes"][0] if r["quotes"] else ""} for r in lib[:3]]
    if not vp:
        flags.append("no value props in company.yaml")
    buyer_fns = comp.get("personas", {}).get("buyer_functions", [])
    if buyer_fns and fn not in buyer_fns:
        flags.append(f"{fn} is not a buyer function in company.yaml")
    return {"persona": fn, "segment": segment or "all", "lead_message": {"pain": vp.get("pain"), "outcome": vp.get("outcome")},
            "supporting": [{"pain": v.get("pain"), "outcome": v.get("outcome")} for v in others],
            "proof": comp.get("proof_points", []), "objections": persona_objs[:4], "accounts_with_evidence": len(accounts),
            "flags": flags}


def launch_brief(ctx, feature: str, audience: str = "") -> dict:
    comp = profile.company(ctx)
    vps = comp.get("value_props", [])
    match = [v for v in vps if any(w in _norm(v.get("pain", "") + " " + v.get("outcome", "")) for w in
                                   [w for w in re.findall(r"[a-z]{4,}", _norm(feature))])]
    proof = comp.get("proof_points", [])
    comps = company_competitors(ctx)
    lib = objection_library(ctx)["categories"][:3]
    todo = []

    def field(value, owner):
        if value:
            return value
        todo.append(owner)
        return f"TODO: {owner}"

    sections = [
        ("What it is (one sentence)", field("", "product owner: one-sentence description")),
        ("Who it is for and the pain it solves", field("; ".join(v["pain"] for v in match), "product marketing: target pain")),
        ("What changes for the customer", field("; ".join(v["outcome"] for v in match), "product marketing: customer outcome")),
        ("Proof", field("; ".join(proof), "marketing: approved proof point")),
        ("Positioning vs competitors", field("; ".join(f"{c['name']}: {c.get('positioning', 'to verify')}" for c in comps),
                                             "product marketing: competitor positioning")),
        ("Objections we expect", field("; ".join(f"{r['category']} ({r['count']})" for r in lib),
                                       "sales: objections from early calls")),
        ("Launch date, channels, owners", field("", "marketing: date, channels, owners")),
        ("Enablement: talk track, demo, FAQ", field("", "enablement: talk track, demo, FAQ")),
        ("Success metric and how we measure it", field("", "product owner: success metric")),
    ]
    text = f"Launch brief: {feature}\nAudience: {audience or 'TODO: product marketing'}\n\n" + "\n".join(
        f"{i}. {t}\n   {v}" for i, (t, v) in enumerate(sections, 1)) + "\n"
    return {"feature": feature, "audience": audience or None, "sections": [{"title": t, "value": v} for t, v in sections],
            "todo": todo, "text": text, "company": comp.get("company")}


# ---------------------------------------------------------------- reports
def field_report(ctx, now: datetime | None = None, days: int = 7) -> dict:
    end = _now(now)
    start, prev_start = end - timedelta(days=days), end - timedelta(days=2 * days)
    hist_start = end - timedelta(days=90 + days)
    canon = {_norm(c["name"]): c["name"] for c in company_competitors(ctx)}

    def count(kind, a, b):
        out: dict[str, int] = {}
        for r in _insights(ctx, kind, a, b):
            k = canon.get(_norm(r["key"]), r["key"]) if kind == "competitor_mention" else _norm(r["key"])
            out[k] = out.get(k, 0) + 1
        return out

    cur, prev = count("competitor_mention", start, end), count("competitor_mention", prev_start, start)
    comp_rows = sorted(({"competitor": k, "mentions": cur.get(k, 0), "prev": prev.get(k, 0),
                         "trend": _trend(cur.get(k, 0), prev.get(k, 0))} for k in set(cur) | set(prev)),
                       key=lambda r: (-r["mentions"], r["competitor"]))
    obj_now, obj_hist = count("objection", start, end), count("objection", hist_start, start)
    new_objs = sorted(k for k in obj_now if k not in obj_hist)
    wl = win_loss(ctx, days, end)
    return {"days": days, "competitors": comp_rows, "objections": obj_now, "new_objections": new_objs,
            "won": wl["won"], "lost": wl["lost"], "won_amount": wl["won_amount"], "lost_amount": wl["lost_amount"],
            "loss_reasons": wl["loss_reasons"]}


def render_field_report(r: dict) -> str:
    L = [f"*Product Marketing: field report, last {r['days']} days*"]
    if r["competitors"]:
        L.append("Competitor mentions: " + "; ".join(f"{c['competitor']} {c['mentions']} (prev {c['prev']}, {c['trend']})"
                                                       for c in r["competitors"]))
    else:
        L.append("Competitor mentions: none")
    if r["objections"]:
        L.append("Objections: " + "; ".join(f"{k} {v}" for k, v in sorted(r["objections"].items(), key=lambda kv: -kv[1])))
    if r["new_objections"]:
        L.append("New this week: " + ", ".join(r["new_objections"]))
    L.append(f"Closed: {r['won']} won (${r['won_amount']:,.0f}), {r['lost']} lost (${r['lost_amount']:,.0f})")
    if r["loss_reasons"]:
        L.append("Loss reasons: " + "; ".join(r["loss_reasons"][:5]))
    return "\n".join(L)


def competitors_to_refresh(ctx, since_days: int | None = None, now: datetime | None = None) -> tuple[list[str], list[str]]:
    """Every company.yaml competitor, plus any name mentioned at least `new_competitor_min_mentions` times."""
    known = [c["name"] for c in company_competitors(ctx)]
    end = _now(now)
    start = end - timedelta(days=_days(ctx, since_days))
    counts: dict[str, int] = {}
    known_norm = {_norm(k) for k in known}
    for r in _insights(ctx, "competitor_mention", start, end):
        if _norm(r["key"]) not in known_norm:
            counts[r["key"]] = counts.get(r["key"], 0) + 1
    min_n = int(ctx.manifest.config.get("new_competitor_min_mentions", 3))
    new = sorted(k for k, n in counts.items() if n >= min_n)
    return known + new, new
