"""Quality Monitor evaluator: sampling, claim sourcing, regression alerts, exclusions."""
from __future__ import annotations

from datetime import datetime, timedelta

from gtm_core.agents import load_module


def seed(ctx, spec):
    now = datetime.fromisoformat(spec["now"])
    for d in spec["drafts"]:
        for n in d["days_ago"]:
            ctx.store.insert(
                "INSERT INTO drafts (agent, kind, subject, body, gate_score, gate_passed, source, status, meta, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (d["agent"], d.get("kind", "first_touch"), "s", spec[d["body"]], 36, 1, "model", "sent", "{}",
                 (now - timedelta(days=n)).replace(microsecond=0).isoformat()))
    return now


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    now = seed(ctx, spec)
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    reg = {r["agent"]: r for r in eng.regression(ctx, now)}
    for a in ex["regressed"]:
        add(f"{a} regression alerted", reg[a]["alerts"], reg[a])
    for a in ex["not_regressed"]:
        add(f"{a} steady, no alert", not reg[a]["alerts"], reg[a])
    for a in ex["no_baseline"]:
        add(f"{a} not compared without baseline", not reg[a]["alerts"] and reg[a].get("note"), reg[a])
    s = eng.sample(ctx, None, None, now)
    add("sample sizes", {a: len(v) for a, v in s.items()} == ex["sample_size"], {a: len(v) for a, v in s.items()})
    add("internal docs excluded", ex["excluded_agent"] not in s and ex["excluded_agent"] not in reg, list(s))
    add("sample is repeatable", [d["id"] for v in s.values() for d in v] ==
        [d["id"] for v in eng.sample(ctx, None, None, now).values() for d in v], "")
    bad = eng.claims(ctx, spec["bad"])
    un = [c["claim"] for c in bad if not c["sourced"]]
    add("unsourced claims found", all(any(x in u for u in un) for x in ex["unsourced_in_bad"]), un)
    ok = eng.claims(ctx, spec["sourced"])
    add("proof point claim counts as sourced", any(c["claim"] == ex["sourced_ok"] and c["sourced"] for c in ok), ok)
    jobs = load_module(m, "jobs")
    r = jobs.daily_quality(ctx, now)
    ins = ctx.store.insights("quality")
    add("daily job alerts and stores insights", r["regressed"] == ex["regressed"] and len(ins) == len(ex["sample_size"])
        and "reply-desk" in ctx.slack.sent[-1]["text"], r)
    return out
