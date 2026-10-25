"""Enrichment evaluator: waterfall order, normalization, cache, TTL, caps, overwrite rules, approvals, reports."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    saved = m.config.get("providers_inline")
    m.config["providers_inline"] = spec["providers"]
    try:
        return _run(m, spec, make_ctx)
    finally:
        if saved is None:
            m.config.pop("providers_inline", None)
        else:
            m.config["providers_inline"] = saved


def _run(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for s in spec["scores"]:
        ctx.store.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
                         ("r1", "signal-scout", s["account_id"], 80, s["tier"], spec["now"]))
    for c in spec["contacts"]:
        ctx.store.upsert("contacts", c)
    from gtm_core.handoffs import Handoffs
    for h in spec.get("handoffs", []):
        Handoffs(ctx.store, "reply-desk").send("enrichment", h["kind"], h["ref"], h["payload"])
    eng = load_module(m, "engine")
    jobs = load_module(m, "jobs")
    now = datetime.fromisoformat(spec["now"])
    stats = jobs.enrich_queue(ctx, now=now)
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:300]})

    def calls(person=None, provider=None):
        sql, p = "SELECT * FROM enrichment_calls WHERE 1=1", []
        if person:
            sql += " AND person=?"; p.append(person)
        if provider:
            sql += " AND provider=?"; p.append(provider)
        return ctx.store.query(sql, p)

    for cid, want in ex["phone"].items():
        c = ctx.store.get("contacts", cid) or {}
        prov = (c.get("enrichment") or {}).get("phone", {})
        add(f"{cid} phone {want['value']} from {want['provider']}", c.get("phone") == want["value"] and prov.get("provider") == want["provider"],
            f"{c.get('phone')} via {prov.get('provider')}")
    for cid, pname in ex.get("not_called", {}).items():
        add(f"{cid}: {pname} never called after a hit", not calls(cid, pname), [r["provider"] for r in calls(cid)])
    for cid, kept in ex.get("crm_value_kept", {}).items():
        c = ctx.store.get("contacts", cid) or {}
        add(f"{cid} CRM values kept {kept}", all(c.get(k) == v for k, v in kept.items()), {k: c.get(k) for k in kept})
    cid = ex.get("invalid_phone_is_miss")
    if cid:
        c = ctx.store.get("contacts", cid) or {}
        bad_calls = calls(cid, "p1")
        add(f"{cid}: invalid phone rejected", not c.get("phone") and bad_calls and "'phone'" not in bad_calls[0]["note"].split("valid")[-1],
            (c.get("phone"), [r["note"] for r in bad_calls]))
    cid = ex.get("invalid_email_rejected")
    if cid:
        c = ctx.store.get("contacts", cid) or {}
        add(f"{cid}: invalid email rejected", not c.get("email") and c.get("title") == "Analyst", (c.get("email"), c.get("title")))
    for cid, fields in ex.get("contact_update_fields", {}).items():
        c = ctx.store.get("contacts", cid)
        ups = [a for a in ctx.approvals.list(None) if a["action"] == "contact_update" and a["payload"]["crm_id"] == c["crm_id"]]
        add(f"{cid}: contact_update with only {fields}", len(ups) == 1 and sorted(ups[0]["payload"]["fields"]) == sorted(fields),
            [u["payload"]["fields"] for u in ups])
    cid = ex.get("new_contact_gets_crm_contact")
    if cid:
        cc = [a for a in ctx.approvals.list(None) if a["action"] == "crm_contact" and a["payload"]["fields"].get("email") == cid]
        add(f"{cid}: new contact queued as crm_contact", len(cc) == 1 and cc[0]["payload"]["fields"].get("phone") == "+14155550199", cc)
    cid = ex.get("skipped_do_not_contact")
    if cid:
        add(f"{cid}: do not contact skipped", not calls(cid) and not (ctx.store.get("contacts", cid) or {}).get("phone"), calls(cid))
    rc = ex.get("request_contact")
    if rc:
        c = ctx.store.get("contacts", rc["id"]) or {}
        consumed = not ctx.handoffs.pending("enrich_request")
        add("enrich_request handoff: contact created and filled", consumed and c.get("email") == rc["email"] and c.get("phone") == rc["phone"],
            {k: c.get(k) for k in ("email", "phone")} | {"consumed": consumed})
    cid = ex.get("cache_second_run_no_calls")
    if cid:
        before = len(calls())
        r = eng.waterfall(ctx, eng.person_from_contact(ctx, ctx.store.get("contacts", cid)), ["phone", "linkedin"], eng.new_run(), now=now)
        add(f"{cid}: second lookup served from cache", len(calls()) == before and r["phone"]["source"] == "cache", r)
        days = ex.get("ttl_expired_requeries_after_days")
        if days:
            r2 = eng.waterfall(ctx, eng.person_from_contact(ctx, ctx.store.get("contacts", cid)), ["phone"], eng.new_run(),
                               now=now + timedelta(days=days))
            add(f"{cid}: re-queried after {days} days", len(calls()) > before and r2["phone"].get("source") == "provider", r2)
    cap = ex.get("per_run_cap")
    if cap:
        cfg = json.loads(json.dumps(spec["providers"]))
        cfg["caps"]["per_run_usd"] = cap["cap"]
        sent = len(ctx.slack.sent)
        run = eng.new_run()
        r = eng.waterfall(ctx, {"email": "nobody@nw.example", "domain": "nw.example"}, ["phone"], run, cfg, now)
        add("per-run cap stops the waterfall and alerts", run["capped"] and "stopped" in r["phone"].get("status", "")
            and len(ctx.slack.sent) == sent + 1 and run["spent"] <= cap["cap"], (r, run))
    for aid, want in ex.get("account", {}).items():
        res = eng.enrich_account(ctx, ctx.store.account(aid), now=now)
        a = ctx.store.account(aid)
        upd = [x for x in ctx.approvals.list(None) if x["action"] == "crm_update"]
        add(f"{aid} firmographics filled and queued", all(a.get(k) == v for k, v in want.items()) and len(upd) == 1,
            ({k: a.get(k) for k in want}, res.get("changed")))
    rep = eng.waterfall_report(ctx, 30, now + timedelta(days=1))
    for field, pname in ex.get("report_keep", {}).items():
        add(f"report recommends keeping {pname} for {field}", any(r.startswith(f"{field}: keep {pname}") for r in rep["recommendations"]),
            rep["recommendations"])
    cov = ex.get("coverage_phone")
    if cov:
        cr = eng.coverage_report(ctx)
        add(f"coverage: {cov['valid']} of {cov['of']} target contacts have a valid phone",
            cr["valid_phone"] == cov["valid"] and cr["target_contacts"] == cov["of"], cr)
    add("job summary posted", stats["contacts"] >= 6 and any("Enrichment" in m_["text"] for m_ in ctx.slack.sent), stats)
    return out
