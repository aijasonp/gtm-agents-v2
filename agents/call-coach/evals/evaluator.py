"""Call Coach evaluator: rubric totals, top fixes, scenario cards and drill plans from real calls."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    out = []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    def text(f):
        return m.path(f).read_text()

    for c in spec["scores"]:
        r = eng.score(ctx, text(c["file"]), c["scenario"])
        tag = f"{c['file'].split('/')[-1]} as {c['scenario']}"
        if "min_total" in c:
            add(f"{tag} total >= {c['min_total']}", r["total"] >= c["min_total"], r["total"])
        if "max_total" in c:
            add(f"{tag} total <= {c['max_total']}", r["total"] <= c["max_total"], r["total"])
        if "rep" in c:
            add(f"{tag} finds the rep", r["rep_speakers"] == c["rep"], r["rep_speakers"])
        if "fixes_include" in c:
            got = [f["skill"] for f in r["top_fixes"]]
            add(f"{tag} top fixes", sorted(got) == sorted(c["fixes_include"]), got)
        for k in c.get("skill_full", []):
            add(f"{tag} full marks on {k}", r["points"][k] == r["max"][k], r["points"][k])
        for k, v in c.get("max_skill", {}).items():
            add(f"{tag} {k} <= {v}", r["points"][k] <= v, r["points"][k])
    sc = eng.scenarios(ctx)
    for sid in spec["scenarios"]["must_include"]:
        add(f"scenario {sid} available", sid in sc)
    st = eng.start(ctx, "discovery_first_call")
    hidden = sc["discovery_first_call"][spec["scenarios"]["buyer_prompt_hides_from_brief"]]
    add("hidden pain in buyer prompt, not in rep brief", hidden in st["buyer_prompt"] and hidden not in str(st["brief"]))
    add("unknown scenario is an error", "error" in eng.start(ctx, "nope"))
    d = spec["drill"]
    for mt in d["meetings"]:
        ctx.store.upsert("meetings", {k: v for k, v in mt.items() if k != "transcript_file"} | {"transcript": text(mt["transcript_file"])})
    p = eng.drill_plan(ctx, d["rep"], 30, now)
    add("drill plan uses only the rep's calls in the window", p["calls_scored"] == d["expect_calls"], p["calls_scored"])
    got = sorted(x["skill"] for x in p["drills"])
    add("drill plan picks the weakest skills", got == sorted(d["expect_weakest"]), got)
    add("every drill has a scenario", all(x["scenario"] for x in p["drills"]), p["drills"])
    return out
