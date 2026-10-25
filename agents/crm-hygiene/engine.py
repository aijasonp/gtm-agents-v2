"""CRM Hygiene engine: deterministic duplicate, orphan, bounce and stale-stage checks.

Nothing here writes to the CRM. propose_fix() queues approvals; executors run only after a human approves.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from gtm_core import pipeline


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def _now(now):
    return now or datetime.now(timezone.utc)


# ---------- normalization ----------
def norm_domain(v: str | None) -> str:
    v = (v or "").strip().lower()
    v = re.sub(r"^[a-z]+://", "", v).split("/")[0].split("?")[0]
    return v.removeprefix("www.").rstrip(".")


def norm_name(v: str | None, suffixes: list[str] | None = None) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", (v or "").lower().replace("&", " and ")).split()
    suf = set(suffixes or [])
    while words and words[-1] in suf:
        words.pop()
    return " ".join(words)


def _filled(r: dict) -> int:
    return sum(1 for k, v in r.items() if v not in (None, "", [], {}) and k not in ("id", "updated_at"))


def survivor(records: list[dict]) -> dict:
    """Keep the record that has a CRM id, then the most recently updated, then the most fields filled,
    then the smallest id. Same input, same pick."""
    def key(r):
        return (1 if r.get("crm_id") else 0, str(r.get("updated_at") or ""), _filled(r))
    best = max(key(r) for r in records)
    return sorted([r for r in records if key(r) == best], key=lambda r: str(r["id"]))[0]


def _live(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r.get("merged_into")]


def _group(rows: list[dict], keyfn, basis: str) -> list[dict]:
    groups: dict[str, list] = {}
    for r in rows:
        k = keyfn(r)
        if k:
            groups.setdefault(k, []).append(r)
    out = []
    for k, rs in sorted(groups.items()):
        if len(rs) < 2:
            continue
        s = survivor(rs)
        out.append({"basis": basis, "key": k, "survivor": s["id"], "ids": sorted(r["id"] for r in rs),
                    "losers": sorted(r["id"] for r in rs if r["id"] != s["id"]),
                    "names": sorted({r.get("name") or r.get("email") or r["id"] for r in rs})})
    return out


# ---------- checks ----------
def duplicate_accounts(ctx) -> list[dict]:
    rows = _live(ctx.store.accounts())
    by_domain = _group(rows, lambda r: norm_domain(r.get("domain") or (r["id"] if "." in r["id"] else "")), "domain")
    seen = {frozenset(g["ids"]) for g in by_domain}
    suf = cfg(ctx, "name_suffixes", [])
    by_name = [g for g in _group(rows, lambda r: norm_name(r.get("name"), suf), "name") if frozenset(g["ids"]) not in seen]
    return by_domain + by_name


def duplicate_contacts(ctx) -> list[dict]:
    rows = _live(ctx.store.select("contacts"))
    by_email = _group(rows, lambda r: (r.get("email") or "").strip().lower(), "email")
    covered = {i for g in by_email for i in g["ids"]}
    by_name = _group([r for r in rows if r["id"] not in covered],
                     lambda r: f"{r['account_id']}|{norm_name(r.get('name'))}" if r.get("account_id") and r.get("name") else "",
                     "name_at_account")
    return by_email + by_name


def missing_account(ctx) -> list[dict]:
    free = {d.lower() for d in cfg(ctx, "free_mail_domains", [])}
    known = {a["id"] for a in ctx.store.accounts()}
    out = []
    for c in _live(ctx.store.select("contacts", order="id")):
        if c.get("account_id") and c["account_id"] in known:
            continue
        email = (c.get("email") or "").lower()
        dom = email.split("@", 1)[1] if "@" in email else ""
        row = {"contact_id": c["id"], "name": c.get("name"), "email": email or None, "domain": dom or None}
        if not dom:
            row["match"], row["why"] = None, "no email"
        elif dom in free:
            row["match"], row["why"] = None, "personal email domain; needs a work email"
        else:
            a = ctx.store.account_by_domain(dom)
            row["match"] = a["id"] if a else None
            row["why"] = f"email domain matches {a['name']}" if a else f"no account with domain {dom}"
        out.append(row)
    return out


def bounced(ctx) -> list[dict]:
    return [{"contact_id": c["id"], "name": c.get("name"), "email": c.get("email"), "account_id": c.get("account_id"),
             "bounced_at": c.get("email_invalid_at")}
            for c in _live(ctx.store.select("contacts", order="id")) if c.get("email_invalid") in (True, 1, "true", "1")]


def request_reenrichment(ctx, contact_ids: list[str] | None = None) -> dict:
    rows = bounced(ctx)
    if contact_ids:
        rows = [r for r in rows if r["contact_id"] in contact_ids]
    if not getattr(ctx, "handoffs", None):
        return {"queued": 0, "contacts": rows, "note": "handoffs unavailable; listed only"}
    queued = 0
    for r in rows:
        hid = ctx.handoffs.send("enrichment", "enrich_request", r["contact_id"],
                                {"contact_id": r["contact_id"], "name": r["name"], "account_id": r["account_id"],
                                 "fields": ["email"], "reason": "email bounced"})
        queued += 1 if hid else 0
    return {"queued": queued, "contacts": rows}


def stale(ctx, now: datetime | None = None) -> list[dict]:
    now = _now(now)
    limits = {k.lower(): int(v) for k, v in (cfg(ctx, "stage_max_days", {}) or {}).items()}
    default = int(cfg(ctx, "default_stage_max_days", 45))
    push = int(cfg(ctx, "close_date_push_days", 30))
    out = []
    for d in ctx.store.select("deals", order="id"):
        if not pipeline.is_open(d):
            continue
        issues, fields = [], {}
        until = pipeline.days_until(d.get("close_date"), now)
        if until is not None and until < 0:
            issues.append(f"close date {str(d['close_date'])[:10]} is {-until} days past")
            fields["close_date"] = (now + timedelta(days=push)).date().isoformat()
        limit = limits.get((d.get("stage") or "").lower(), default)
        idle = pipeline.days_since(d.get("last_activity_at") or d.get("stage_entered_at"), now)
        if idle is not None and idle > limit:
            issues.append(f"no activity for {idle} days in {d.get('stage')} (limit {limit})")
        if not issues:
            continue
        out.append({"deal_id": d["id"], "name": d.get("name"), "owner": d.get("owner"), "stage": d.get("stage"),
                    "crm_id": d.get("crm_id"), "issues": issues, "proposed_fields": fields,
                    "ask_owner": "confirm the close date and next step, or close it lost"})
    return out


# ---------- fixes ----------
def _contact_account_field(ctx) -> str:
    m = cfg(ctx, "contact_account_field", {}) or {}
    return m.get(getattr(ctx.settings, "crm", "hubspot"), "account_id")


def propose_fix(ctx, kind: str, ids: list[str]) -> dict:
    """Queue one approval per fix. kinds: merge_accounts, merge_contacts, link_contact, revise_deal."""
    ids = [str(i) for i in (ids or [])]
    if not ids:
        return {"error": "ids required"}
    if kind in ("merge_accounts", "merge_contacts"):
        recs = [ctx.store.account(i) if kind == "merge_accounts" else ctx.store.get("contacts", i) for i in ids]
        if any(r is None for r in recs):
            return {"error": f"not found: {[i for i, r in zip(ids, recs) if r is None]}"}
        recs = _live(recs)
        if len(recs) < 2:
            return {"error": "a merge needs at least two live records"}
        s = survivor(recs)
        obj = "account" if kind == "merge_accounts" else "contact"
        payload = {"object": obj, "survivor": {"id": s["id"], "crm_id": s.get("crm_id"), "name": s.get("name") or s.get("email")},
                   "losers": [{"id": r["id"], "crm_id": r.get("crm_id"), "name": r.get("name") or r.get("email")}
                              for r in recs if r["id"] != s["id"]],
                   "reason": "survivor has a CRM id, then the latest update, then the most fields filled"}
        rid = ctx.request_approval("crm_merge", payload,
                                   summary=f"merge {len(payload['losers'])} {obj}(s) into {payload['survivor']['name']}")
        return {"queued_for_approval": rid, **payload}
    if kind == "link_contact":
        found = {r["contact_id"]: r for r in missing_account(ctx)}
        queued, skipped = [], []
        for i in ids:
            r = found.get(i)
            if not r or not r.get("match"):
                skipped.append({"contact_id": i, "why": (r or {}).get("why", "not missing an account")})
                continue
            c, a = ctx.store.get("contacts", i), ctx.store.account(r["match"])
            if c.get("crm_id"):
                rid = ctx.request_approval("contact_update", {"crm_id": c["crm_id"], "fields": {
                    _contact_account_field(ctx): a.get("crm_id") or a["id"]}}, summary=f"link {c.get('name')} to {a['name']}")
            else:
                rid = ctx.request_approval("crm_contact", {"fields": {k: c.get(k) for k in ("name", "email", "title") if c.get(k)},
                                                           "account_crm_id": a.get("crm_id")},
                                           summary=f"create {c.get('name')} under {a['name']}")
            queued.append({"contact_id": i, "account": a["id"], "approval": rid})
        return {"queued": queued, "skipped": skipped}
    if kind == "revise_deal":
        found = {r["deal_id"]: r for r in stale(ctx)}
        queued, skipped = [], []
        for i in ids:
            r = found.get(i)
            if not r:
                skipped.append({"deal_id": i, "why": "not stale"})
                continue
            if not r.get("crm_id") or not r["proposed_fields"]:
                skipped.append({"deal_id": i, "why": "no CRM id" if not r.get("crm_id") else
                                "nothing to change automatically; ask the owner", "issues": r["issues"]})
                continue
            rid = ctx.request_approval("deal_update", {"crm_id": r["crm_id"], "fields": r["proposed_fields"]},
                                       summary=f"{r['name']}: " + "; ".join(r["issues"]))
            queued.append({"deal_id": i, "approval": rid, "fields": r["proposed_fields"]})
        return {"queued": queued, "skipped": skipped}
    return {"error": "kind must be merge_accounts, merge_contacts, link_contact or revise_deal"}


def mark_merged(ctx, payload: dict) -> list[str]:
    """After an approved merge: losers are marked merged_into locally so checks stop flagging them."""
    sid = payload["survivor"]["id"]
    done = []
    for l in payload.get("losers", []):
        if payload["object"] == "account":
            a = ctx.store.account(l["id"])
            if a:
                ctx.store.upsert_account({**{k: v for k, v in a.items() if k != "updated_at"}, "merged_into": sid})
                done.append(l["id"])
        else:
            if ctx.store.get("contacts", l["id"]):
                ctx.store.upsert("contacts", {"id": l["id"], "merged_into": sid})
                done.append(l["id"])
    return done


def summary(ctx, now: datetime | None = None) -> dict:
    return {"duplicate_accounts": duplicate_accounts(ctx), "duplicate_contacts": duplicate_contacts(ctx),
            "missing_account": missing_account(ctx), "bounced": bounced(ctx), "stale_deals": stale(ctx, now)}


def format_report(s: dict, n: int = 5) -> str:
    matchable = [r for r in s["missing_account"] if r.get("match")]
    lines = ["*CRM Hygiene weekly report*",
             f"- Duplicate accounts: {len(s['duplicate_accounts'])} groups",
             f"- Duplicate contacts: {len(s['duplicate_contacts'])} groups",
             f"- Contacts with no account: {len(s['missing_account'])} ({len(matchable)} match by email domain)",
             f"- Bounced contacts needing a new email: {len(s['bounced'])}",
             f"- Stale open deals: {len(s['stale_deals'])}"]
    for d in s["stale_deals"][:n]:
        lines.append(f"  - {d['name']} ({d['owner'] or 'no owner'}): {'; '.join(d['issues'])}")
    lines.append("Nothing was changed. Ask for a fix to queue it for approval.")
    return "\n".join(lines)


def as_json(v) -> str:
    return json.dumps(v, default=str)
