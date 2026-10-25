"""Proposal Builder engine: quote math, discount guardrails and proposal rendering.

All money is Decimal, rounded half up to cents at every line and every discount. No model calls.
Order of math, per line then per quote:
  unit price  = the volume tier with the highest min_qty at or below qty (else list price)
  line total  = unit price x qty
  recurring   = sum of recurring line totals
  term disc   = recurring x term discount %          (recurring lines only)
  extra disc  = (recurring - term disc) x discount %  (recurring lines only; services are never discounted)
  annual      = recurring - term disc - extra disc
  year one    = annual + one-time lines
  TCV         = annual x term years + one-time lines
Guardrails, in order: below floor (annual < floor % of recurring list) is blocked; an extra discount above
the highest approval level is blocked; above the requester's role limit needs the lowest level that covers it.
"""
from __future__ import annotations

import html
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

import yaml

from gtm_core import meddpicc, profile
from gtm_core.store import now_iso

CENT = Decimal("0.01")
ROLE_ORDER = ["ae", "manager", "vp"]

SCHEMA = ["""CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, deal_id TEXT, account_id TEXT, payload TEXT,
             status TEXT, approval_id INTEGER, created_at TEXT, expires_at TEXT)"""]


def ensure_schema(ctx) -> None:
    if not getattr(ctx.store, "_quotes_schema", False):
        for s in SCHEMA:
            ctx.store.execute(s)
        ctx.store._quotes_schema = True


def money(v) -> Decimal:
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


def pct(v) -> Decimal:
    return Decimal(str(v or 0))


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    p = Path(path)
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def pricebook(ctx) -> dict:
    if isinstance(ctx.manifest.config.get("pricebook_inline"), dict):  # tests and evals
        return ctx.manifest.config["pricebook_inline"]
    return _yaml(str(ctx.manifest.path(ctx.manifest.config.get("pricebook", "../../config/pricebook.yaml"))))


def _now(now):
    return now or datetime.now(timezone.utc)


# ---------------------------------------------------------------- products and pricing
def products(pb: dict) -> dict[str, dict]:
    return {p["sku"]: p for p in pb.get("products", [])}


def unit_price(prod: dict, qty: int) -> tuple[Decimal, str]:
    best, label = money(prod["list_price"]), "list"
    for t in sorted(prod.get("tiers") or [], key=lambda t: t["min_qty"]):
        if qty >= int(t["min_qty"]):
            best, label = money(t["price"]), f"tier {t['min_qty']}+"
    return best, label


def term_discount(pb: dict, years: int) -> Decimal | None:
    for t in pb.get("terms", [{"years": 1, "discount_pct": 0}]):
        if int(t["years"]) == int(years):
            return pct(t["discount_pct"])
    return None


def guardrail(pb: dict, discount_pct, role: str, annual: Decimal, recurring_list: Decimal) -> dict:
    g = {k.lower(): pct(v) for k, v in (pb.get("discount_guardrails") or {}).items()}
    d = pct(discount_pct)
    floor = money(recurring_list * pct(pb.get("floor_pct_of_list", 0)) / 100)
    if recurring_list > 0 and annual < floor:
        return {"status": "blocked", "reason": f"annual recurring {annual} is below the floor {floor} "
                                               f"({pb.get('floor_pct_of_list')}% of list)", "floor": str(floor)}
    if d < 0:
        return {"status": "blocked", "reason": "discount cannot be negative"}
    levels = [r for r in ROLE_ORDER if r in g] + [r for r in g if r not in ROLE_ORDER]
    top = max(g.values()) if g else Decimal(0)
    if d > top:
        return {"status": "blocked", "reason": f"{d}% is above the highest approval level ({top}%)"}
    mine = g.get((role or "ae").lower(), Decimal(0))
    if d <= mine:
        return {"status": "ok", "role_limit": str(mine)}
    need = next(r for r in levels if g[r] >= d)
    return {"status": "needs_approval", "level": need, "role_limit": str(mine),
            "reason": f"{d}% is above the {role} limit of {mine}%; needs {need} approval"}


def compute(pb: dict, lines: list[dict], term_years: int = 1, discount_pct=0, role: str = "ae") -> dict:
    """Pure quote math. Raises ValueError on unknown SKUs, bad quantities or an unsupported term."""
    cat = products(pb)
    if not lines:
        raise ValueError("a quote needs at least one line")
    tdisc = term_discount(pb, term_years)
    if tdisc is None:
        raise ValueError(f"no {term_years}-year term in the price book; options: "
                         f"{[t['years'] for t in pb.get('terms', [])]}")
    out_lines, recurring, recurring_list, one_time = [], Decimal(0), Decimal(0), Decimal(0)
    for ln in lines:
        sku = ln.get("sku")
        if sku not in cat:
            raise ValueError(f"unknown sku {sku!r}; valid: {sorted(cat)}")
        try:
            qty = int(ln.get("qty", 1))
        except (TypeError, ValueError):
            raise ValueError(f"{sku}: qty must be a whole number") from None
        if qty < 1 or qty != float(ln.get("qty", 1)):
            raise ValueError(f"{sku}: qty must be a whole number of 1 or more")
        p = cat[sku]
        up, tier = unit_price(p, qty)
        total = money(up * qty)
        lst = money(money(p["list_price"]) * qty)
        once = bool(p.get("one_time"))
        out_lines.append({"sku": sku, "name": p["name"], "unit": p.get("unit", "unit"), "qty": qty,
                          "list_price": str(money(p["list_price"])), "unit_price": str(up), "tier": tier,
                          "list_total": str(lst), "total": str(total), "one_time": once})
        if once:
            one_time += total
        else:
            recurring += total
            recurring_list += lst
    term_amt = money(recurring * tdisc / 100)
    extra_amt = money((recurring - term_amt) * pct(discount_pct) / 100)
    annual = recurring - term_amt - extra_amt
    tcv = annual * int(term_years) + one_time
    eff = (Decimal(1) - annual / recurring_list) * 100 if recurring_list else Decimal(0)
    return {"currency": pb.get("currency", "USD"), "lines": out_lines, "term_years": int(term_years),
            "recurring_list": str(recurring_list), "recurring_subtotal": str(recurring),
            "term_discount_pct": str(tdisc), "term_discount": str(term_amt),
            "extra_discount_pct": str(pct(discount_pct)), "extra_discount": str(extra_amt),
            "annual_recurring": str(money(annual)), "one_time": str(one_time),
            "year_one_total": str(money(annual + one_time)), "total_contract_value": str(money(tcv)),
            "effective_discount_pct": str(eff.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "guardrail": guardrail(pb, discount_pct, role, money(annual), recurring_list), "role": role}


# ---------------------------------------------------------------- quotes
def _subject(ctx, deal_or_account: str) -> tuple[dict | None, dict | None]:
    deal = ctx.store.get("deals", deal_or_account) if deal_or_account else None
    if deal is None and deal_or_account:
        rows = ctx.store.select("deals", "crm_id=?", (deal_or_account,))
        deal = rows[0] if rows else None
    acct = ctx.store.account(deal["account_id"]) if deal and deal.get("account_id") else \
        (ctx.store.account(deal_or_account) if deal_or_account else None)
    return deal, acct


def build_quote(ctx, deal_or_account: str, lines: list[dict], term_years: int = 1, discount_pct=0,
                role: str = "ae", now: datetime | None = None) -> dict:
    ensure_schema(ctx)
    deal, acct = _subject(ctx, deal_or_account)
    if not deal and not acct:
        return {"error": f"no deal or account '{deal_or_account}'"}
    pb = pricebook(ctx)
    try:
        q = compute(pb, lines, term_years, discount_pct, role)
    except ValueError as e:
        return {"error": str(e)}
    qid = "q_" + uuid.uuid4().hex[:10]
    g = q["guardrail"]
    status = {"ok": "ready", "needs_approval": "pending_approval", "blocked": "blocked"}[g["status"]]
    expires = (_now(now) + timedelta(days=int(pb.get("quote_valid_days", 30)))).date().isoformat()
    q.update({"quote_id": qid, "deal_id": deal["id"] if deal else None, "account_id": acct["id"] if acct else None,
              "account": (acct or {}).get("name") or (deal or {}).get("name"), "expires": expires})
    rid = None
    if status == "pending_approval":
        rid = ctx.request_approval("discount_approval", {
            "quote_id": qid, "level": g["level"], "discount_pct": q["extra_discount_pct"],
            "annual_recurring": q["annual_recurring"], "tcv": q["total_contract_value"], "account": q["account"]},
            summary=f"{q['extra_discount_pct']}% discount for {q['account']} needs {g['level']} approval "
                    f"(annual {q['currency']} {q['annual_recurring']})")
    ctx.store.execute("INSERT INTO quotes (id, deal_id, account_id, payload, status, approval_id, created_at, expires_at) "
                      "VALUES (?,?,?,?,?,?,?,?)", (qid, q["deal_id"], q["account_id"], json.dumps(q), status, rid,
                                                   _now(now).replace(microsecond=0).isoformat(), expires))
    q.update({"status": status, "approval_id": rid})
    return q


def get_quote(ctx, qid: str) -> dict | None:
    ensure_schema(ctx)
    r = ctx.store.one("SELECT * FROM quotes WHERE id=?", (qid,))
    if not r:
        return None
    q = json.loads(r["payload"])
    status = r["status"]
    if status == "pending_approval" and r.get("approval_id"):
        a = ctx.store.one("SELECT status FROM approvals WHERE id=?", (r["approval_id"],))
        if a and a["status"] in ("approved", "executed"):
            status = "ready"
            ctx.store.execute("UPDATE quotes SET status=? WHERE id=?", (status, qid))
        elif a and a["status"] == "rejected":
            status = "discount_rejected"
            ctx.store.execute("UPDATE quotes SET status=? WHERE id=?", (status, qid))
    q.update({"status": status, "approval_id": r.get("approval_id"), "expires": r["expires_at"]})
    return q


def expiring(ctx, days: int = 7, now: datetime | None = None) -> list[dict]:
    ensure_schema(ctx)
    today = _now(now).date()
    end = (today + timedelta(days=days)).isoformat()
    rows = ctx.store.query("SELECT id FROM quotes WHERE status IN ('ready','pending_approval','sent') "
                           "AND expires_at>=? AND expires_at<=? ORDER BY expires_at", (today.isoformat(), end))
    return [get_quote(ctx, r["id"]) for r in rows]


# ---------------------------------------------------------------- rendering
def _fmt(cur: str, v: str) -> str:
    d = Decimal(v)
    sym = {"USD": "$", "EUR": "EUR ", "GBP": "GBP ", "CAD": "CA$"}.get(cur, cur + " ")
    return f"{sym}{d:,.2f}"


def _evidence(m: dict, key: str) -> str:
    e = m.get(key) or {}
    return (e.get("evidence") or "").strip()


def proposal_facts(ctx, q: dict) -> dict:
    """Everything the proposal may say: deal MEDDPICC evidence, company.yaml claims and the quote. Nothing else."""
    comp = profile.company(ctx)
    deal = ctx.store.get("deals", q["deal_id"]) if q.get("deal_id") else None
    m = meddpicc.normalize((deal or {}).get("meddpicc"))
    pain, metrics, criteria = _evidence(m, "identify_pain"), _evidence(m, "metrics"), _evidence(m, "decision_criteria")
    vps = comp.get("value_props", [])
    words = set(re.findall(r"[a-z]{4,}", f"{pain} {metrics}".lower()))
    ranked = sorted(vps, key=lambda v: -len(words & set(re.findall(r"[a-z]{4,}", f"{v.get('pain', '')} {v.get('outcome', '')}".lower()))))
    return {"company": comp.get("company", ""), "product": comp.get("product", ""), "one_liner": comp.get("one_liner", ""),
            "sender": comp.get("sender", {}), "account": q.get("account"), "deal": (deal or {}).get("name"),
            "pain": pain, "metrics": metrics, "decision_criteria": criteria,
            "value_props": ranked[:3], "proof_points": comp.get("proof_points", [])}


def render(ctx, q: dict) -> tuple[str, str]:
    """Return (html, markdown). Self-contained HTML: inline CSS, no scripts, no external assets except an optional logo."""
    f = proposal_facts(ctx, q)
    brand = pricebook(ctx).get("brand", {})
    cur = q["currency"]
    rows = [(ln["name"], f"{ln['qty']} {ln['unit']}", _fmt(cur, ln["unit_price"]) + ("" if ln["one_time"] else " / yr"),
             ln["tier"], _fmt(cur, ln["total"])) for ln in q["lines"]]
    summary = [("Recurring subtotal", q["recurring_subtotal"])]
    if Decimal(q["term_discount"]):
        summary.append((f"{q['term_years']}-year term discount ({q['term_discount_pct']}%)", "-" + q["term_discount"]))
    if Decimal(q["extra_discount"]):
        summary.append((f"Additional discount ({q['extra_discount_pct']}%)", "-" + q["extra_discount"]))
    summary += [("Annual recurring", q["annual_recurring"])]
    if Decimal(q["one_time"]):
        summary.append(("One-time services", q["one_time"]))
    summary += [("Year one total", q["year_one_total"]), (f"Total contract value ({q['term_years']} yr)", q["total_contract_value"])]
    draft = q.get("status") != "ready" and q.get("status") != "sent"
    terms = pricebook(ctx).get("payment_terms", "")

    # markdown
    md = [f"# Proposal for {f['account']}", f"Prepared by {f['sender'].get('name', '')}, {f['company']}. Valid until {q['expires']}.", ""]
    if draft:
        md += [f"> Draft: {q.get('status', '').replace('_', ' ')}. Not for the customer yet.", ""]
    if f["pain"] or f["metrics"]:
        md += ["## What we heard"]
        md += [f"- Pain: {f['pain']}"] if f["pain"] else []
        md += [f"- What success looks like: {f['metrics']}"] if f["metrics"] else []
        md += [f"- How you will decide: {f['decision_criteria']}"] if f["decision_criteria"] else []
        md.append("")
    md += ["## How we help"] + [f"- {v.get('outcome', '')}" for v in f["value_props"]] + [""]
    if f["proof_points"]:
        md += ["## Proof"] + [f"- {p}" for p in f["proof_points"]] + [""]
    md += ["## Pricing", "", "| Item | Quantity | Unit price | Tier | Total |", "| --- | --- | --- | --- | --- |"]
    md += [f"| {' | '.join(r)} |" for r in rows] + [""]
    md += [f"- {k}: {_fmt(cur, v.lstrip('-'))}" if not v.startswith("-") else f"- {k}: -{_fmt(cur, v[1:])}" for k, v in summary]
    md += ["", "## Terms", f"- {terms}", f"- Quote {q['quote_id']} valid until {q['expires']}."]
    markdown = "\n".join(md) + "\n"

    # html
    e = html.escape
    p, a, mu = brand.get("primary", "#1F2933"), brand.get("accent", "#3E7CB1"), brand.get("muted", "#F5F7FA")
    logo = f'<img src="{e(brand["logo_url"])}" alt="{e(f["company"])}" style="height:32px">' if brand.get("logo_url") else \
        f'<strong>{e(f["company"])}</strong>'
    heard = "".join(f"<li><b>{e(k)}:</b> {e(v)}</li>" for k, v in
                    [("Pain", f["pain"]), ("What success looks like", f["metrics"]), ("How you will decide", f["decision_criteria"])] if v)
    trs = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    sums = "".join(f"<tr><td>{e(k)}</td><td class=n>{'-' if v.startswith('-') else ''}{e(_fmt(cur, v.lstrip('-')))}</td></tr>"
                   for k, v in summary)
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proposal for {e(f['account'] or '')}</title><style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:{p};background:#fff;margin:0;line-height:1.5}}
main{{max-width:820px;margin:0 auto;padding:32px 20px}} header{{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid {a};padding-bottom:12px}}
h1{{font-size:28px;margin:24px 0 4px}} h2{{font-size:18px;margin-top:28px;color:{a}}} .muted{{color:#52606D}}
table{{width:100%;border-collapse:collapse;margin-top:8px}} th,td{{text-align:left;padding:8px;border-bottom:1px solid #E4E7EB}}
th{{background:{mu}}} td.n{{text-align:right}} .draft{{background:#FFF4E5;border:1px solid #F0B429;padding:8px 12px;margin-top:16px}}
.sum td:first-child{{color:#52606D}} .sum tr:last-child td{{font-weight:700}}
</style></head><body><main>
<header>{logo}<span class=muted>Quote {e(q['quote_id'])} | valid until {e(q['expires'])}</span></header>
<h1>Proposal for {e(f['account'] or '')}</h1><p class=muted>Prepared by {e(f['sender'].get('name', ''))}, {e(f['company'])}</p>
{f'<div class=draft>Draft: {e(q.get("status", "").replace("_", " "))}. Not for the customer yet.</div>' if draft else ''}
{f'<h2>What we heard</h2><ul>{heard}</ul>' if heard else ''}
<h2>How we help</h2><ul>{''.join(f"<li>{e(v.get('outcome', ''))}</li>" for v in f['value_props'])}</ul>
{('<h2>Proof</h2><ul>' + ''.join(f'<li>{e(x)}</li>' for x in f['proof_points']) + '</ul>') if f['proof_points'] else ''}
<h2>Pricing</h2><table><thead><tr><th>Item</th><th>Quantity</th><th>Unit price</th><th>Tier</th><th>Total</th></tr></thead><tbody>{trs}</tbody></table>
<table class=sum>{sums}</table>
<h2>Terms</h2><ul><li>{e(terms)}</li><li>Prices in {e(cur)}.</li></ul>
</main></body></html>"""
    return body, markdown


def render_proposal(ctx, qid: str) -> dict:
    q = get_quote(ctx, qid)
    if not q:
        return {"error": f"quote {qid} not found"}
    if q["status"] in ("blocked", "discount_rejected"):
        return {"error": f"quote {qid} is {q['status']}: {q['guardrail'].get('reason', 'rebuild it')}"}
    page, md = render(ctx, q)
    out = ctx.manifest.path(ctx.manifest.config.get("output_dir", "../../data/proposals"))
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (q.get("account") or "proposal").lower()).strip("-")
    hp, mp = out / f"{slug}-{qid}.html", out / f"{slug}-{qid}.md"
    hp.write_text(page)
    mp.write_text(md)
    did = ctx.store.add_draft(ctx.manifest.id, "proposal", md, subject=f"Proposal for {q.get('account')}", source="template",
                              status="draft", account_id=q.get("account_id"), deal_id=q.get("deal_id"),
                              meta={"quote_id": qid, "html_path": str(hp), "md_path": str(mp)})
    return {"quote_id": qid, "status": q["status"], "html_path": str(hp), "md_path": str(mp), "draft_id": did,
            "ready_to_send": q["status"] == "ready"}


def queue_send(ctx, qid: str, to_email: str, note: str = "") -> dict:
    q = get_quote(ctx, qid)
    if not q:
        return {"error": f"quote {qid} not found"}
    if q["status"] != "ready":
        return {"error": f"quote {qid} is {q['status']}; only a ready quote (discount approved if needed) can be sent"}
    if "@" not in (to_email or ""):
        return {"error": "to_email required"}
    d = ctx.store.one("SELECT id, meta FROM drafts WHERE agent=? AND kind='proposal' AND meta LIKE ? ORDER BY id DESC LIMIT 1",
                      (ctx.manifest.id, f'%"{qid}"%'))
    if not d:
        return {"error": f"render the proposal for {qid} first"}
    meta = json.loads(d["meta"] or "{}")
    rid = ctx.request_approval("proposal_send", {"quote_id": qid, "to": to_email.lower(), "note": note,
                                                 "draft_id": d["id"], "html_path": meta.get("html_path"),
                                                 "deal_id": q.get("deal_id"), "tcv": q["total_contract_value"]},
                               summary=f"send proposal {qid} to {to_email} ({q['account']}, TCV {q['currency']} "
                                       f"{q['total_contract_value']})")
    ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", rid, d["id"]))
    return {"queued_for_approval": rid, "quote_id": qid}


def mark_sent(ctx, payload: dict) -> dict:
    """Executor body for an approved proposal_send: record it, and log a CRM note when the deal has a CRM id."""
    ensure_schema(ctx)
    ctx.store.execute("UPDATE quotes SET status=? WHERE id=?", ("sent", payload["quote_id"]))
    ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("sent", payload.get("draft_id")))
    deal = ctx.store.get("deals", payload["deal_id"]) if payload.get("deal_id") else None
    res = {"ok": True, "quote_id": payload["quote_id"], "to": payload["to"], "at": now_iso()}
    if deal and deal.get("crm_id"):
        res["crm_note"] = ctx.crm.add_note(deal["crm_id"], f"Proposal {payload['quote_id']} sent to {payload['to']} "
                                                           f"(TCV {payload.get('tcv')})")
    return res
