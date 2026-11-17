"""Account Health evaluator: scores, bands, the save-before-expand gate, negation, contract fallbacks,
approval-only write-back with dedupe, renewal-window alerts and usage import validation."""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from gtm_core.agents import load_module
from gtm_core.scoring import signal_id


def load(ctx, spec, eng) -> None:
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    for d in spec.get("deals", []):
        ctx.store.upsert("deals", d)
    for c in spec.get("contacts", []):
        ctx.store.upsert("contacts", c)
    for m in spec.get("meetings", []):
        ctx.store.upsert("meetings", m)
    for acct, metric, value, at in spec.get("usage", []):
        r = eng.add_usage(ctx, acct, metric, value, at, "golden")
        assert r["ok"], r
    for kind, key, acct, mid, ev, at in spec.get("insights", []):
        ctx.store.add_insight("meeting-intelligence", kind, key, None, ev, at, account_id=acct, meeting_id=mid)
    for acct, st, cat, at in spec.get("signals", []):
        ctx.store.add_signal({"id": signal_id(acct, st, "", at), "account_id": acct, "signal_type": st, "category": cat,
                              "observed_at": at, "source": "golden"})


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    load(ctx, spec, eng)
    now = datetime.fromisoformat(spec["now"])
    res_list = eng.assess_all(ctx, now=now, persist=False)
    res = {x["account_id"]: x for x in res_list}
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)})

    for aid, rec in ex["recommendation"].items():
        x = res.get(aid)
        add(f"{aid} -> {rec}", x and x["recommendation"] == rec,
            x and f"got {x['recommendation']} risk {x['risk']} exp {x['expansion']} {x['risk_drivers']} {x['expansion_drivers']}")
    for aid, band in ex["band"].items():
        add(f"{aid} band {band}", res[aid]["band"] == band, res[aid]["band"])
    for aid, v in ex.get("risk", {}).items():
        add(f"{aid} risk == {v}", res[aid]["risk"] == v, f"{res[aid]['risk']}: {res[aid]['risk_keys']}")
    for aid, v in ex.get("expansion", {}).items():
        add(f"{aid} expansion == {v}", res[aid]["expansion"] == v, f"{res[aid]['expansion']}: {res[aid]['expansion_keys']}")
    order = [x["account_id"] for x in res_list]
    want = ex["order"]
    add("priority order (risk x renewal urgency)", [a for a in order if a in want] == want, order)
    for aid, keys in ex.get("risk_keys_include", {}).items():
        miss = [k for k in keys if k not in res[aid]["risk_keys"]]
        add(f"{aid} risk drivers {keys}", not miss, f"missing {miss}; got {res[aid]['risk_keys']}")
    for aid, keys in ex.get("risk_keys_exclude", {}).items():
        bad = [k for k in keys if k in res[aid]["risk_keys"]]
        add(f"{aid} has no {keys}", not bad, f"got {res[aid]['risk_keys']}")
    for aid, keys in ex.get("expansion_keys_include", {}).items():
        miss = [k for k in keys if k not in res[aid]["expansion_keys"]]
        add(f"{aid} expansion drivers {keys}", not miss, f"missing {miss}; got {res[aid]['expansion_keys']}")
    for aid, parts in ex.get("drivers_include", {}).items():
        text = " | ".join(res[aid]["risk_drivers"] + res[aid]["expansion_drivers"])
        miss = [p for p in parts if p not in text]
        add(f"{aid} drivers quote the evidence", not miss, f"missing {miss} in: {text}")
    for aid, (date, src) in ex.get("renewal", {}).items():
        add(f"{aid} renewal {date} from {src}", res[aid]["renewal_date"] == date and res[aid]["renewal_source"] == src,
            f"{res[aid]['renewal_date']} ({res[aid]['renewal_source']})")
    for aid, v in ex.get("arr", {}).items():
        add(f"{aid} ARR {v}", res[aid]["arr"] == v, res[aid]["arr"])
    for aid in ex.get("not_assessed", []):
        add(f"{aid} is not a customer", aid not in res, "assessed" if aid in res else "skipped")
    for aid, x in res.items():
        if x["recommendation"] != "steady":
            add(f"{aid} has 1-3 actions", 1 <= len(x["actions"]) <= 3, x["actions"])
    p = eng.portfolio(res_list)
    pe = ex["portfolio"]
    add("portfolio rollup", p["customers"] == pe["customers"] and p["arr"] == pe["arr"] and p["at_risk"] == pe["at_risk"]
        and p["expand"] == pe["expand"], p)

    jobs = load_module(m, "jobs")
    r1 = jobs.daily_health(ctx, now=now)
    acts = ctx.approvals.list()
    add("first run queues one CRM task per save or expand", r1["tasks_queued"] == ex["tasks_first_run"]
        and all(a["action"] == "crm_task" and a["status"] == "pending" for a in acts), f"{r1['tasks_queued']} {acts}")
    add("renewal-window alerts for non-healthy customers", sorted(
        res[n]["account_id"] for n in res if res[n]["name"] in r1["entered_renewal_window"]) == sorted(ex["entered_window"]),
        r1["entered_renewal_window"])
    add("changes posted to Slack", any("Account Health changes" in s["text"] for s in ctx.slack.sent), "")
    add("one health insight per customer", len(ctx.store.insights("account_health")) == len(res),
        len(ctx.store.insights("account_health")))
    r2 = jobs.daily_health(ctx, now=now)
    add("second run queues nothing new", r2["tasks_queued"] == ex["tasks_second_run"] and not r2["new_save"], r2)

    jobs.weekly_portfolio(ctx, now=now)
    text = ctx.slack.sent[-1]["text"]
    add("weekly report renders save and expand lists", "Save first:" in text and "Expand:" in text
        and "$460,000" in text, text[:300])

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "usage.csv"
        f.write_text("account,metric,value,observed_at\n"
                     "Adatum Corp,mau,47,2026-11-12\n"
                     "adatum.example,happiness,9,2026-11-12\n"
                     "nobody.example,active_users,5,2026-11-12\n"
                     "adatum.example,active_users,lots,2026-11-12\n")
        r = eng.import_usage(ctx, f)
        add("import maps aliases and refuses unknown metrics, accounts and values",
            r["stored"] == 1 and r["error_count"] == 3, r)

    tools = load_module(m, "tools")
    e = tools.explain_health(ctx, "Northwind Logistics")
    add("explain works with no model (template)", e["summary_source"] == "template" and "SAVE" in e["summary"], e)
    add("unknown customer is refused", "error" in tools.account_health(ctx, "wingtip.example"), "")
    return out
