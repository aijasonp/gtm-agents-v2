"""Social Signals evaluator: resolution, dedupe, signal typing, timing-only rules, proposals, alerts, reports."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    ctx.manifest.config = {**ctx.manifest.config, "tracked_creators": spec["tracked_creators"]}
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for c in spec["contacts"]:
        ctx.store.upsert("contacts", c)
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    for s in spec.get("scores", []):
        ctx.store.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
                         ("eval", "signal-scout", s["account_id"], s["score"], s["tier"], spec["now"]))
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    out = eng.ingest(ctx, spec["engagements"], now)
    st, res = out["stats"], out["results"]
    by_name = {}
    for r in res:
        by_name.setdefault(r["name"], []).append(r)
    ex, cases = spec["expect"], []

    def add(name, ok, detail):
        cases.append({"case": name, "passed": bool(ok), "detail": str(detail)[:300]})

    for name, want in ex["resolved"].items():
        r = by_name.get(name, [{}])[0]
        add(f"{name} resolved by {want['method']}", all(r.get(k) == v for k, v in want.items()),
            {k: r.get(k) for k in ("method", "contact_id", "account_id", "confidence")})
    add("unresolved engager counted, not dropped", st["unresolved"] == ex["unresolved_count"], st)
    add("untracked creator skipped", st["skipped"] == ex["skipped"], st)
    add("duplicate engagement counted once", st["duplicates"] == ex["duplicates"], st)
    tax = eng.taxonomy(ctx)
    for acct, types in ex["signals_for"].items():
        got = sorted(s["signal_type"] for s in ctx.store.signals_for(acct))
        add(f"{acct} signals {types}", got == sorted(types), got)
    add("timing-only types have no say_it", all(tax.types[t].say_it == "" for t in ex["timing_only_types"]),
        {t: tax.types[t].say_it for t in ex["timing_only_types"]})
    add("comments and shares are mentionable", all(tax.types[t].say_it for t in ex["mentionable_types"]), "")
    add("competitor in a comment becomes an insight",
        any(i["key"] == ex["competitor_insight"] for i in ctx.store.insights("competitor_mention")), "")
    props = [a for a in ctx.approvals.list() if a["action"] == "crm_contact"]
    names = [a["payload"]["fields"]["name"] for a in props]
    add(f"crm_contact proposed for {ex['proposals_for']}", sorted(names) == sorted(ex["proposals_for"]), names)
    add(f"no proposal for {ex['no_proposal_for']}", not set(names) & set(ex["no_proposal_for"]), names)
    alerts = eng.alert_lines(ctx, res)
    for owner, person in ex["alert_owner"].items():
        add(f"{owner} alerted about {person}", any(person in line for line in alerts.get(owner, [])), alerts.get(owner))
    add("account without CRM or deal owner routes to its territory owner",
        eng.owner_for(ctx, "fourthcoffee.example") == "Sam Rivera", eng.owner_for(ctx, "fourthcoffee.example"))
    rep = eng.creator_report(ctx, 7, now)
    add("creator report covers tracked creators", {c["creator"] for c in rep["creators"]} >= set(ex["creator_report_has"]),
        [c["creator"] for c in rep["creators"]])
    rs = by_name.get(ex["repeat_raises_strength"], [])
    add("repeat engagement raises strength", len(rs) >= 2 and rs[-1]["strength"] > rs[0]["strength"] and
        rs[-1]["repeat"] > rs[0]["repeat"], [(r["type"], r["repeat"], r["strength"]) for r in rs])
    add("idempotent: re-ingest adds nothing", eng.ingest(ctx, spec["engagements"], now)["stats"]["duplicates"] ==
        len(spec["engagements"]) - st["skipped"], "")
    return cases
