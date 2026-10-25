"""Meeting Intelligence evaluator."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.handoffs import Handoffs


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    for a in spec.get("accounts", []):
        ctx.store.upsert_account(a)
    for d in spec.get("deals", []):
        ctx.store.upsert("deals", d)
    for mt in spec.get("meetings", []):
        ctx.store.upsert("meetings", mt)
    jobs, eng = load_module(m, "jobs"), load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    run = jobs.process_meetings(ctx, now=now)
    again = jobs.process_meetings(ctx, now=now)
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": detail})

    def summ(mid):
        return ctx.store.get("meetings", mid).get("summary") or {}

    add("processes meetings with transcripts only", run["processed"] == ex["processed"], str(run))
    add("second run is a no-op", again["processed"] == ex["idempotent_second_run"], str(again))
    for mid, comp in ex.get("competitor_insight", {}).items():
        keys = [i["key"] for i in ctx.store.insights("competitor_mention", meeting_id=mid)]
        add(f"{mid} competitor {comp}", comp in keys, str(keys))
    for mid, cats in ex.get("objection_insight", {}).items():
        keys = {i["key"] for i in ctx.store.insights("objection", meeting_id=mid)}
        add(f"{mid} objections {cats}", set(cats) <= keys, str(sorted(keys)))
    for mid, els in ex.get("meddpicc_found", {}).items():
        got = set(summ(mid).get("meddpicc_found", []))
        add(f"{mid} MEDDPICC evidence {els}", set(els) <= got, str(sorted(got)))
    for mid in ex.get("no_next_step_flag", []):
        add(f"{mid} flagged no next step", any("No clear next step" in f for f in summ(mid).get("flags", [])),
            str(summ(mid).get("flags")))
    for mid in ex.get("has_next_step", []):
        add(f"{mid} next step captured", any("pilot plan" in n for n in summ(mid).get("next_steps", [])),
            str(summ(mid).get("next_steps")))
    for mid in ex.get("talk_ratio_flag", []):
        add(f"{mid} talk ratio flagged", any("talked" in f for f in summ(mid).get("flags", [])), str(summ(mid).get("flags")))
    recaps = {h["ref"]: h for h in Handoffs(ctx.store, "seller-follow-up").pending("meeting_recap")}
    for mid in ex.get("handoff_recap", []):
        h = recaps.get(mid)
        add(f"{mid} recap handed to seller-follow-up", h and h["payload"].get("deal_id") and "summary" in h["payload"], str(h))
    evid = {h["payload"]["deal_id"]: h for h in Handoffs(ctx.store, "deal-inspection").pending("meddpicc_evidence")}
    for did in ex.get("handoff_evidence_deals", []):
        add(f"{did} evidence handed to deal-inspection", did in evid and evid[did]["payload"]["evidence"], str(list(evid)))
    notes = [a for a in ctx.approvals.list() if a["action"] == "deal_note"]
    add("deal notes queued for approval", len(notes) == ex["deal_note_approvals"] and "Next steps" in notes[0]["payload"]["body"],
        f"{len(notes)} notes")
    for did in ex.get("never_confirms", []):
        h = evid.get(did)
        scores = [v["score"] for v in (h["payload"].get("proposed") or {}).values()] if h else []
        stored = ctx.store.get("deals", did).get("meddpicc")
        add(f"{did} evidence only proposes partial, deal untouched", scores and max(scores) == 1 and stored is None,
            f"proposed {scores}, stored {stored}")
    for mid, areas in ex.get("coaching_missed", {}).items():
        c = eng.coaching(ctx, ctx.store.get("meetings", mid))
        add(f"{mid} coaching names missed areas {areas}", set(areas) <= set(c["missed_meddpicc_areas"]) and c["tips"],
            str(c["missed_meddpicc_areas"]))
    return out
