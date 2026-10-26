"""Signal Sourcing evaluator: tiers, gates, quotes, dedupe, dispatch and discovery on recorded responses."""
from __future__ import annotations

import json
from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.sources.fixtures import fixture_client


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    ctx.sources_client = fixture_client(m.path(spec["fixtures"]))
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    for a in json.loads(m.path(spec["accounts"]).read_text()):
        ctx.store.upsert_account(a)
    res = {a["id"]: eng.scan_account(ctx, a, now) for a in ctx.store.accounts()}
    for aid, word in ex["rejected"].items():
        why = res[aid].get("rejected") or ""
        add(f"{aid} rejected ({word})", word in why or (word == "lead-gen" and "lead-gen" in why), why)
    for aid, srcs in ex["sources"].items():
        got = sorted({f["source"] for f in res[aid]["findings"]})
        add(f"{aid} tiers {srcs}", got == srcs, got)
    for aid, e in ex["filing"].items():
        f = next((f for f in res[aid]["findings"] if f["source"] == "filing"), None)
        add(f"{aid} filing {e['form']} {e['date']} {e['confidence']}",
            f and f["confidence"] == e["confidence"] and f["observed_at"] == e["date"] and f["meta"]["filing"] == e["form"]
            and e["contains"] in f["detail"], f)
    quotes = [f["detail"].lower() for r in res.values() for f in r["findings"]] + \
             [q.lower() for r in res.values() for f in r["findings"] for q in f["meta"].get("other_quotes", [])]
    add("boilerplate never quoted", not any(ex["boilerplate_never_quoted"] in q for q in quotes), "")
    aid = ex["exec_change_once"]
    n = sum(1 for f in res[aid]["findings"] if f["source"] == "exec_change")
    add("8-K and newsroom report the same appointment once", n == 1, n)
    for aid, roles in ex["hiring_roles"].items():
        f = next((f for f in res[aid]["findings"] if f["source"] == "hiring"), {})
        add(f"{aid} hiring counts buyer roles in window only", f.get("meta", {}).get("roles") == roles, f.get("meta"))
    for aid, amt in ex["initiative_amount"].items():
        f = next((f for f in res[aid]["findings"] if f["source"] == "initiative"), {})
        add(f"{aid} initiative amount {amt}", f.get("amount") == amt and f.get("confidence") == "High", f)
    for aid, txt in ex["notes"].items():
        add(f"{aid} says why nothing was found", txt in json.dumps(res[aid]["tiers"]), res[aid]["tiers"])
    d = eng.dispatch(ctx, now)
    add("dispatch holds only accounts with a valid signal", [b["account_id"] for b in d["batch"]] == ex["dispatch"],
        [b["account_id"] for b in d["batch"]])
    exc = {e["account_id"]: e["reason"] for e in d["excluded"]}
    for aid, word in ex["dispatch_excluded"].items():
        add(f"{aid} held out ({word})", word in exc.get(aid, ""), exc.get(aid))
    add("every dispatch row is complete", all(all(b[k] for k in ("domain", "company", "industry", "signal_source",
        "signal_detail", "signal_url", "signal_date", "signal_score", "target_personas")) for b in d["batch"]), d["batch"])
    again = eng.scan_account(ctx, ctx.store.account("northwind.example"), now)
    add("re-scan stores no duplicates", len(again["stored"]) == ex["rescan_stores"], again["stored"])
    disc = eng.discover(ctx, now)
    add("discovery finds new companies only, investors excluded", [c["name"] for c in disc["candidates"]] == ex["discovery"],
        [c["name"] for c in disc["candidates"]])
    # downstream: the sourced filing becomes a safe opener in ICP Outbound
    from gtm_core.agents import Manifest
    ob = Manifest.load(m.path("../icp-outbound"))
    octx = make_ctx(ob)
    octx.store = ctx.store
    for aid, line in ex["say_it"].items():
        allsay = _all_openers(octx, ob, ctx.store.account(aid), now)
        add(f"{aid} filing opener fills from the sourced payload", line in allsay, allsay)
    off = make_ctx(m)
    off.store = ctx.store
    add("offline runtime fetches nothing", eng.scan_account(off, ctx.store.account("northwind.example"), now).get("skipped"), "")
    if spec.get("job_search"):
        out += _job_search_cases(m, spec, make_ctx, eng, now)
    if spec.get("page_changes"):
        out += _page_change_cases(m, spec, make_ctx, eng, now)
    return out


def _page_change_cases(m, spec, make_ctx, eng, now) -> list[dict]:
    pc, out = spec["page_changes"], []

    def add(name, ok, detail=""):
        out.append({"case": "page changes: " + name, "passed": bool(ok), "detail": str(detail)[:400]})

    ctx = make_ctx(m)
    ctx.store.upsert_account(pc["account"])
    aid = pc["account"]["id"]
    p = eng.page_change(ctx, {**pc["pricing_only"], "changed_at": now.date().isoformat()}, now)
    add("a pricing page change is stored as a timing-only signal", [f["signal_type"] for f in p["findings"]] ==
        ["pricing_change"] and p["stored"], p)
    d = eng.dispatch(ctx, now)
    add("a timing-only page change never qualifies an account for the send list",
        aid not in [b["account_id"] for b in d["batch"]], [b["account_id"] for b in d["batch"]])
    c = eng.page_change(ctx, {**pc["careers"], "changed_at": now.date().isoformat()}, now)
    f = (c["findings"] or [{}])[0]
    add("careers page buyer roles become a hiring signal", f.get("signal_type") == "hiring_buyer_team" and
        f.get("meta", {}).get("roles") == pc["expect_careers_roles"], f)
    d = eng.dispatch(ctx, now)
    row = next((b for b in d["batch"] if b["account_id"] == aid), None)
    add("a mentionable page change can carry an account onto the send list", row and row["signal_source"] == "page change",
        row)
    again = eng.page_change(ctx, {**pc["careers"], "changed_at": now.date().isoformat()}, now)
    add("the same notification twice stores nothing new", again["stored"] == [], again["stored"])
    return out


class _FakeSearch:
    name = "jobspy"

    def __init__(self, rows):
        self.rows = rows

    def search(self, acct, max_age_days):
        from gtm_core.sources.jobsearch import same_company
        return [r for r in self.rows if same_company(acct, r.get("company"), r.get("company_url"))]


def _job_search_cases(m, spec, make_ctx, eng, now) -> list[dict]:
    js, out = spec["job_search"], []

    def add(name, ok, detail=""):
        out.append({"case": "job search: " + name, "passed": bool(ok), "detail": str(detail)[:400]})

    ctx = make_ctx(m)
    ctx.sources_client = fixture_client(m.path(spec["fixtures"]))
    ctx.job_search = _FakeSearch(js["postings"])
    ctx.store.upsert_account(js["account"])
    r = eng.scan_account(ctx, ctx.store.account(js["account"]["id"]), now)
    f = next((x for x in r["findings"] if x["source"] == "hiring"), None)
    add("an enterprise with no ATS board gets its hiring signal from job sites",
        f and f["meta"]["provider"] == "jobspy" and f["meta"]["roles"] == js["expect_roles"], f and f["meta"])
    add("job site hiring is stored as a sourced signal", ctx.store.one("SELECT source FROM signals WHERE account_id=? AND signal_type='hiring_buyer_team'",
                          (js["account"]["id"],)) == {"source": "sourcing:hiring"}, r["stored"])
    add("a job search provider never becomes the account's ATS board", not ctx.store.account(js["account"]["id"]).get("ats"),
        ctx.store.account(js["account"]["id"]).get("ats"))
    return out


def _all_openers(ctx, ob, acct, now) -> list[str]:
    eng = load_module(ob, "engine")
    tax = eng.taxonomy(ctx)
    out = []
    for s in ctx.store.signals_for(acct["id"]):
        st = tax.types.get(s["signal_type"])
        if st and st.say_it:
            line = eng._fill(st.say_it, acct, "", s.get("payload"))
            if line:
                out.append(line)
    return out
