"""Exec Brief evaluator: exact metric values, week-over-week judgments, snapshot picks and the heat map."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    eng = load_module(m, "engine")
    ctx.store.set_state(eng.SNAP_KEY, spec["snapshots"])
    at = datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)})

    got = {x["name"]: x for x in eng.compute(ctx, list(ex["values"]) + [ex["not_configured"]], at)}
    for n, (v, p, sig) in ex["values"].items():
        g = got[n]
        add(f"{n} value", g["value"] == v, g["value"])
        add(f"{n} last week", g["prior"] == p, g["prior"])
        add(f"{n} signal", g["signal"] == sig, g["signal"])
    nc = got[ex["not_configured"]]
    add("unconfigured warehouse metric is reported, not guessed", nc["value"] is None and "not configured" in nc.get("note", ""), nc)

    b = eng.role_brief(ctx, "cso", at)
    add("cso brief signals", [x["signal"] for x in b["metrics"]] == ex["cso_signals"], [x["signal"] for x in b["metrics"]])
    add("cso brief has five metrics", len(b["metrics"]) == 5, len(b["metrics"]))
    add("brief text has no em dash", "\u2014" not in eng.format_role(b))

    snap = eng.company_snapshot(ctx, at)
    for dept, want in ex["snapshot"].items():
        g = snap[dept]
        pick = {k: (g[k] or {}).get("name") for k in ("good", "bad")}
        add(f"snapshot {dept}", pick == want, pick)

    eng.save_snapshot(ctx, at)
    h = {r["name"]: r for r in eng.heat_map(ctx, weeks=5, at=at)["rows"]}["open_pipeline"]
    e = ex["heat_open_pipeline"]
    add("heat map values", h["values"] == e["values"], h["values"])
    add("heat map cells", h["cells"] == e["cells"], h["cells"])
    return out
