"""Rep Brief evaluator: ownership, ranking, why-now safety, pipeline math, do-next order, push-button guards."""
from __future__ import annotations

import json
from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.scoring import signal_id


def seed(ctx, spec, eng):
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for c in spec["contacts"]:
        ctx.store.upsert("contacts", c)
    tax = eng.taxonomy(ctx)
    for s in spec["signals"]:
        ctx.store.add_signal({**s, "id": signal_id(s["account_id"], s["signal_type"], s["url"], s["observed_at"]),
                              "category": tax.types[s["signal_type"]].category})
    for s in spec["scores"]:
        ctx.store.insert("INSERT INTO scores (run_id, agent, account_id, score, tier, created_at) VALUES (?,?,?,?,?,?)",
                         ("eval", "signal-scout", s["account_id"], s["score"], s["tier"], spec["now"]))
    for d in spec["deals"]:
        ctx.store.upsert("deals", d)
    for i in spec.get("inspections", []):
        ctx.store.add_insight("deal-inspection", "deal_inspection", i["deal_id"], i, observed_at=spec["now"])
    for l in spec.get("leads", []):
        ctx.store.upsert("leads", l)
    for r in spec.get("replies", []):
        ctx.store.add_insight("reply-desk", "reply", r["key"], r["value"], observed_at=r["observed_at"],
                              account_id=r["account_id"])


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    seed(ctx, spec, eng)
    now = datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:300]})

    for aid, who in ex["owner"].items():
        got = eng.assigned_owner(ctx, ctx.store.account(aid))
        add(f"{aid} owned by {who}", got[0] == who, got)
    b = eng.brief(ctx, "Sam Rivera", now)
    ids = [a["account_id"] for a in b["top_accounts"]]
    add("Sam's top accounts ranked by score", ids[:3] == ex["top_order_sam"], ids)
    add("out-of-ICP accounts never listed", not set(ids) & set(ex["never_listed"]), ids)
    fc = next(a for a in b["top_accounts"] if a["account_id"] == ex["why_now_not_timing"])
    add("why-now never uses a timing-only signal", fc["why_now"] and "pricing" not in fc["why_now"]["signal"].lower()
        and "Visited pricing page" in fc["timing_only"], fc["why_now"])
    nw = next(a for a in b["top_accounts"] if a["account_id"] == ex["open_deal_no_contacts"])
    add("open-deal account shows the deal, not contacts", nw["open_deal"] and not nw["contacts"], nw)
    p = b["pipeline"]
    add("pipeline math", all(abs(float(p[k]) - float(v)) < 0.01 for k, v in ex["pipeline_sam"].items()),
        {k: p[k] for k in ex["pipeline_sam"]})
    add("missing next step and quiet deal found", any("Northwind" in x for x in p["missing_next_step"]) and
        any("Northwind" in x for x in p["idle"]) and any("Contoso" in x for x in p["missing_next_step"]), p)
    add("flagged deal from Deal Inspection", p["flagged"] and p["flagged"][0]["deal"] == "Contoso Agents", p["flagged"])
    add("hot lead and positive reply in brief", b["hot_leads"] and b["replies"], (b["hot_leads"], b["replies"]))
    add("do next 1 is the positive reply", b["do_next"] and ex["do_next_first"] in b["do_next"][0], b["do_next"])
    add("do next 2 is the hot lead", len(b["do_next"]) > 1 and ex["do_next_second"] in b["do_next"][1], b["do_next"])
    pw = next(a for a in b["top_accounts"] if a["account_id"] == "proseware.example")
    add("account with inbound lead in progress is on hold, never suggested for push-button",
        pw["hold"] and "inbound lead" in pw["hold"] and not any("Push-button Proseware" in x for x in b["do_next"]), (pw["hold"], b["do_next"]))
    text = eng.format_brief(b)
    add("brief text has no timing-only signal quoted as why-now", "why now: Visited pricing page" not in text, text[:200])

    r = eng.push_button(ctx, "fourthcoffee.example", "rosa@fourthcoffee.example", now=now)
    acts = [a["action"] for a in ctx.approvals.list() if a["id"] in r.get("approvals", [])]
    add("push-button Rosa queues email, task and dialer", sorted(acts) == sorted(ex["push_rosa"]["approvals"]), r.get("reasons") or acts)
    add("push-button draft passes gate", r.get("draft", {}).get("gate_passed"), r.get("draft"))
    add("Rosa's opener uses her new-role signal", ex["push_rosa"]["opener_contains"] in (r.get("draft", {}).get("body") or "").lower(),
        r.get("draft", {}).get("body"))
    k = eng.push_button(ctx, "fourthcoffee.example", "kai@fourthcoffee.example", now=now)
    acts = [a["action"] for a in ctx.approvals.list() if a["id"] in k.get("approvals", [])]
    add("Kai (no phone) gets email and task only", sorted(acts) == sorted(ex["push_kai"]["approvals"]), k.get("reasons") or acts)
    add("Kai is not congratulated on Rosa's role", ex["push_kai"]["opener_not_contains"] not in (k.get("draft", {}).get("body") or "").lower(),
        k.get("draft", {}).get("body"))
    again = eng.push_button(ctx, "fourthcoffee.example", "rosa@fourthcoffee.example", now=now)
    add("pushing the same contact twice is refused", again.get("refused") and any("touched" in x or "draft" in x for x in again["reasons"]),
        again.get("reasons"))
    for aid, reason in ex["refuse"].items():
        rr = eng.push_button(ctx, aid, owner="Priya Shah" if aid == "northwind.example" else None, now=now)
        add(f"push-button {aid} refused: {reason}", rr.get("refused") and any(reason in x for x in rr["reasons"]) and
            not rr.get("approvals"), rr.get("reasons"))
    jobs = load_module(m, "jobs")
    first = jobs.daily_briefs(ctx, now)
    add("daily briefs go to reps with news, skip empty ones", first["sent"] >= 1 and "Lee Park" not in first["reps"], first)
    second = jobs.daily_briefs(ctx, now)
    add("nothing new since last brief: no second message", second["sent"] == 0, second)
    return out
