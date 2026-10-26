"""Daily Book evaluator: pools, order, exclusions, per-account cap, backfill, shortfall and approval-gated drafts."""
from __future__ import annotations

from datetime import datetime, timedelta

from gtm_core import engagement
from gtm_core.agents import load_module
from gtm_core.scoring import signal_id


def seed(ctx, spec) -> None:
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for aid, tier in spec["scores"].items():
        ctx.store.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
                         ("seed", "signal-scout", aid, spec["score_values"][aid], tier, spec["now"]))
    for c in spec["contacts"]:
        ctx.store.upsert("contacts", c)
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    for ld in spec["leads"]:
        ctx.store.upsert("leads", ld)
    now = datetime.fromisoformat(spec["now"])
    for email, n in spec["engaged"].items():
        c = ctx.store.contact_by_email(email)
        did = ctx.store.add_draft("icp-outbound", "first_touch", "Hi", status="sent", account_id=c["account_id"],
                                  contact_id=c["id"])
        engagement.record(ctx.store, email, "sent", (now - timedelta(days=6)).isoformat(), did, "first_touch")
        for i in range(n):
            engagement.record(ctx.store, email, "open", (now - timedelta(days=5, hours=-i)).isoformat())
    eng = load_module(ctx.manifest.__class__.load(ctx.manifest.path("../follow-through")), "engine") \
        if ctx.manifest.path("../follow-through/agent.yaml").exists() else None
    if eng:
        eng.ensure_schema(ctx)
        for e in spec["teed_up"]:
            ctx.store.execute("INSERT INTO teeups (id, email, status, created_at) VALUES (?,?,?,?)",
                              (f"t:{e}", e, "open", spec["now"]))
    s = spec["sourced_signal"]
    ctx.store.add_signal({"id": signal_id(s["account_id"], s["signal_type"], s["url"], s["observed_at"]),
                          "account_id": s["account_id"], "signal_type": s["signal_type"], "category": "filings",
                          "source": "sourcing:filing", "url": s["url"], "observed_at": s["observed_at"], "strength": 1.0,
                          "payload": {"title": s["title"], "confidence": "High", "topic": "sales productivity",
                                      "filing": "10-Q"}})


def evaluate(m, spec, make_ctx) -> list[dict]:
    out = []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    ctx = make_ctx(m)
    ctx.manifest.config.update(spec["config"])
    seed(ctx, spec)
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    books = {o: eng.build(ctx, o, now) for o in spec["expect"]}

    sam, ex = books["Sam Rivera"], spec["expect"]["Sam Rivera"]
    warm = [r["email"] for r in sam["rows"] if r["pool"] == "warm"]
    cold = [r["email"] for r in sam["rows"] if r["pool"] == "cold"]
    add("Sam's book fills every slot", sam["filled"] == ex["filled"] and sam["shortfall"] == 0, sam["filled"])
    add("warm pool in priority order", warm == ex["warm"], warm)
    add("cold pool: today's sourced account first, then Signal Scout score", cold == ex["cold"], cold)
    src = {r["email"]: r["source"] for r in sam["rows"]}
    add("each row says where it came from", all(src.get(e) == s for e, s in ex["sources"].items()), src)
    every = [r["email"] for b in books.values() for r in b["rows"]]
    add("never: teed up, opted out, tier X, open-deal account, non-buyer title",
        not set(ex["never"]) & set(every), sorted(set(ex["never"]) & set(every)))
    add("engaged rows never tell the AE to mention opens",
        all("never mention" in r["action"] for r in sam["rows"] if r["source"] == "engaged"), "")
    add("each person appears once across all books", len(every) == len(set(every)), "")

    lee, lx = books["Lee Park"], spec["expect"]["Lee Park"]
    add("a thin warm pool is backfilled from cold", lee["filled"] == lx["filled"] and
        lee["backfill"]["warm_from_cold"] == lx["backfill_warm_from_cold"] and lee["warm"] == lx["warm_count"],
        {k: lee[k] for k in ("filled", "warm", "cold", "backfill")})
    ent1 = [r for r in lee["rows"] if r.get("account_id") == "ent1.example"]
    add("at most max_per_account people from one account", len(ent1) == lx["max_from_ent1"], len(ent1))

    pri, px = books["Priya Shah"], spec["expect"]["Priya Shah"]
    add("a real shortfall is reported, never padded", pri["filled"] == px["filled"] and pri["shortfall"] == px["shortfall"],
        {k: pri[k] for k in ("filled", "shortfall")})
    add("the book is held to 25..50 slots outside tests",
        _clamped(ctx, eng), "")

    d = eng.predraft(ctx, sam, now)
    pend = [a for a in ctx.approvals.list("pending", all_agents=True) if a["action"] == "sequence_enroll"]
    add("cold first touches are drafted and wait for the AE", d["queued"] == len(cold) and
        {a["payload"]["contact"]["email"] for a in pend} >= set(cold), d)
    again = eng.build(ctx, "Sam Rivera", now)
    add("rebuilding the same day keeps one row per person", len(ctx.store.query(
        "SELECT email FROM daily_book WHERE owner='Sam Rivera'")) == again["filled"], again["filled"])
    msg = eng.format_book(pri)
    add("the shortfall is said plainly in the book", "Short by 6" in msg, msg)
    return out


def _clamped(ctx, eng) -> bool:
    saved = dict(ctx.manifest.config)
    try:
        ctx.manifest.config.update({"allow_small_books": False, "slots": 6})
        small = eng.plan(ctx, "Sam Rivera")[0]
        ctx.manifest.config.update({"slots": 80})
        big = eng.plan(ctx, "Sam Rivera")[0]
        return small == 25 and big == 50
    finally:
        ctx.manifest.config.clear()
        ctx.manifest.config.update(saved)
