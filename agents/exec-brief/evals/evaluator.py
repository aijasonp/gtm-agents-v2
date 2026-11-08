"""Exec Brief evaluator: exact metric values, status, ranking, card structure and delivery."""
from __future__ import annotations

import os
from datetime import datetime

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    cc = load_module(m, "command_center")
    cfg, rows, now = spec["config"], spec["rows"], datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    c = eng.compute(rows, cfg, spec["previous"], now)
    ms = c["metrics"]
    for k, v in ex["values"].items():
        add(f"value {k}", ms[k]["value"] == v, ms[k]["value"])
    for k, v in ex["status"].items():
        add(f"status {k}", ms[k]["status"] == v, (ms[k]["status"], ms[k]["score"]))
    for k, v in ex["deltas"].items():
        add(f"change {k}", ms[k]["delta"] == v, ms[k]["delta"])
    add("slipped deals, largest first", [i["name"] for i in ms["slipped_out_1d"]["items"]] == ex["slipped_order"],
        ms["slipped_out_1d"]["items"])
    add("renewals excluded from sales numbers", all(i["name"] != "Wingtip Renewal" for i in ms["commit_qtr"]["items"]),
        ms["commit_qtr"]["items"])

    for role in eng.ROLES:
        five = eng.brief_metrics(c, cfg, role)
        add(f"{role} brief has exactly 5 metrics in config order",
            [x["key"] for x in five] == cfg["briefs"][role], [x["key"] for x in five])
    try:
        eng.brief_metrics(c, {"briefs": {"ceo": ["bookings_qtd"]}}, "ceo")
        add("a brief with other than 5 metrics is refused", False)
    except ValueError:
        add("a brief with other than 5 metrics is refused", True)

    ext = {r["dept"]: r for r in eng.department_extremes(c, cfg)}
    for d, (best, worst) in ex["extremes"].items():
        got = [ext[d]["best"] and ext[d]["best"]["key"], ext[d]["worst"] and ext[d]["worst"]["key"]]
        add(f"{d} best and worst", got == [best, worst], got)

    five = eng.brief_metrics(c, cfg, "cso")
    fb = eng.fallback_read(five)
    add("template sentence names the worst and best", "Slipped out of quarter" in fb and "Win rate" in fb, fb)
    add("template sentence is grounded", eng.grounded(fb, five), fb)
    add("invented number is caught", not eng.grounded("Commit is down to $95K, act now.", five), "")
    spec_ = eng.exec_spec("Chief Sales Officer", five, fb, now)
    add("card spec is valid json-render", eng.validate_spec(spec_) == [], eng.validate_spec(spec_))
    fields = [e for e in spec_["elements"].values() if e["type"] == "Field"]
    add("card shows 5 fields", len(fields) == 5, len(fields))
    tables = [e for e in spec_["elements"].values() if e["type"] == "Table"]
    add("deals behind red numbers listed", tables and any("Woodgrove Orchestration" in r for r in tables[0]["props"]["rows"]),
        tables)
    blocks, text, used = eng.render(spec_, "python")
    add("python renderer makes Block Kit", blocks[0]["type"] == "header" and used == "python" and "$55K" in text, text[:200])

    # full run: four DMs, one channel post, snapshot and history stored, command center written
    env = {"EVAL_CEO": "U1", "EVAL_CSO": "U2", "EVAL_CMO": "U3", "EVAL_CHANNEL": "U4", "EVAL_COMPANY": "C9"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    sent = []
    ctx.slack.dm = lambda uid, text, blocks=None, **kw: sent.append(("dm", uid, text)) or {"ok": True}
    ctx.slack.post = lambda text, blocks=None, channel=None, **kw: sent.append(("post", channel, text)) or {"ok": True}
    orig = eng.config, eng.load_rows
    eng.config = lambda _ctx: cfg
    eng.load_rows = lambda _ctx, _cfg=None: rows
    ctx.store.set_state(eng.STATE_KEY, spec["previous"])
    import tempfile
    ctx.settings.data_dir = tempfile.mkdtemp()
    try:
        r = eng.run(ctx, now=now, renderer="python")
    finally:
        eng.config, eng.load_rows = orig
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    add("each executive gets a DM", [s[1] for s in sent if s[0] == "dm"] == ["U1", "U2", "U3", "U4"], sent)
    add("company snapshot goes to the shared channel", [s[1] for s in sent if s[0] == "post"] == ["C9"], sent)
    company = next((s[2] for s in sent if s[0] == "post"), "")
    add("company snapshot has every team", all(t in company for t in ("Sales", "Marketing", "Partners", "Customer Success")),
        company[:300])
    add("snapshot stored for tomorrow", ctx.store.get_state(eng.STATE_KEY)["metrics"]["bookings_qtd"] == 160000, "")
    add("daily history recorded", "2026-11-16" in (ctx.store.get_state(cc.HISTORY_KEY) or {}), "")
    add("command center page written", r["command_center"] and os.path.exists(r["command_center"]), r["command_center"])

    g = cc.grid(eng, rows, cfg, ctx.store.get_state(cc.HISTORY_KEY) or {}, now, today=c)
    add("command center has 8 weekly columns", len(g["weeks"]) == 8 and g["weeks"][-1] == "2026-11-16", g["weeks"])
    bk = g["metrics"]["bookings_qtd"]["cells"]
    add("no week-over-week change across the quarter start", bk[1]["wow"] is None and g["weeks"][1] == "2026-10-05",
        (g["weeks"][1], bk[1]))
    pc = g["metrics"]["pipeline_created_qtd"]["cells"]
    add("week-over-week change inside the quarter (O6 created Nov 10)", pc[-1]["wow"] == 50000 and pc[-1]["wow_good"],
        pc[-1])
    mq = g["metrics"]["mqls_mtd"]["cells"]
    add("no week-over-week change across the month start", mq[5]["wow"] is None and g["weeks"][5] == "2026-11-02",
        (g["weeks"][5], mq[5]))
    add("live-state metrics blank before history exists", g["metrics"]["commit_qtr"]["cells"][0]["value"] is None,
        g["metrics"]["commit_qtr"]["cells"][0])
    add("heat strip renders squares", ":large_red_square:" in cc.slack_strip(g, ["bookings_qtd"]), "")
    return out
