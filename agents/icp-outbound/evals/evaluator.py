"""ICP Outbound evaluator: list order, exclusions, contact picks, angle safety, approvals."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.scoring import signal_id


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    tax = eng.taxonomy(ctx)
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for s in spec.get("scores", []):
        ctx.store.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
                         ("golden", "signal-scout", s["account_id"], s["score"], s["tier"], spec["now"]))
    for d in spec.get("deals", []):
        ctx.store.upsert("deals", d)
    for c in spec.get("contacts", []):
        ctx.store.upsert("contacts", c)
    for s in spec.get("signals", []):
        ctx.store.add_signal({**s, "id": signal_id(s["account_id"], s["signal_type"], s.get("title", ""), s["observed_at"]),
                              "category": tax.types[s["signal_type"]].category, "payload": {"title": s.get("title", "")}})
    dnc = {k: set(v) for k, v in spec.get("do_not_contact", {"domains": [], "emails": []}).items()}
    orig = eng.dnc
    eng.dnc = lambda ctx: dnc
    try:
        now = datetime.fromisoformat(spec["now"])
        lst = eng.build_list(ctx, now)
        ranked = {a["account_id"]: (i, a) for i, a in enumerate(lst["accounts"])}
        excluded = {e["account_id"]: e for e in lst["excluded"]}
        drafts = {}
        for aid, (_, a) in ranked.items():
            acct = ctx.store.account(aid)
            drafts[aid] = [eng.draft_sequence(ctx, acct, c, now) for c in a["contacts"]]
        skipped = {aid: eng.draft_sequence(ctx, ctx.store.account(aid), {"email": "x@y.example", "name": "X"}, now)
                   for aid in spec["expect"].get("skip_draft_for", [])}
    finally:
        eng.dnc = orig
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": detail})

    for hi, lo in ex.get("order", []):
        add(f"{hi} above {lo}", hi in ranked and lo in ranked and ranked[hi][0] < ranked[lo][0],
            f"ranked: {list(ranked)}")
    for aid, why in ex.get("excluded_reason", {}).items():
        reasons = excluded.get(aid, {}).get("reasons", [])
        add(f"{aid} excluded: {why}", any(why in r for r in reasons), str(reasons))
    for aid, name in ex.get("first_contact", {}).items():
        cs = ranked.get(aid, (0, {"contacts": []}))[1]["contacts"]
        add(f"{aid} first contact {name}", cs and cs[0]["name"] == name, str([c["name"] for c in cs]))
    all_contacts = {c["email"] for _, a in ranked.values() for c in a["contacts"]}
    for e in ex.get("never_contacted", []):
        add(f"{e} not picked (not a buyer)", e not in all_contacts, str(sorted(all_contacts)))
    for aid in ex.get("no_buyer_flag", []):
        a = ranked.get(aid, (0, {}))[1]
        add(f"{aid} flagged no buyer contact", "no buyer contact found" in a.get("flags", []), str(a.get("flags")))
    for aid, words in ex.get("copy_excludes", {}).items():
        text = " ".join(s["body"].lower() for d in drafts.get(aid, []) for s in d.get("steps", []))
        add(f"{aid} copy never says {words}", text and not any(w in text for w in words), text[:160])
    for aid, words in ex.get("copy_includes", {}).items():
        text = " ".join(s["body"].lower() for d in drafts.get(aid, []) for s in d.get("steps", []))
        add(f"{aid} copy uses the reason now {words}", all(w in text for w in words), text[:160])
    seq = [d for ds in drafts.values() for d in ds]
    enroll = [a for a in ctx.approvals.list() if a["action"] == "sequence_enroll"]
    add("one send approval per drafted contact, 3 passing steps each",
        seq and len(enroll) == len(seq) and all(len(a["payload"]["steps"]) == 3 for a in enroll),
        f"{len(seq)} contacts, {len(enroll)} approvals")
    add("every step passes the Copy QA Gate", all(s["gate_passed"] for d in seq for s in d["steps"]),
        str([(s["step"], s["gate_score"]) for d in seq for s in d["steps"] if not s["gate_passed"]]))
    for aid, r in skipped.items():
        add(f"{aid} draft refused (conflict)", r.get("skipped") and any("active pipeline" in x for x in r["reasons"]),
            str(r))
    return out
