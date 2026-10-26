"""`gtm` command line: the one interface the customer's ops person needs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .agents import Context, discover
from .config import get_settings


def _manifest(s, agent_id):
    ms = discover(s.agents_dir)
    if agent_id not in ms:
        sys.exit(f"unknown agent '{agent_id}'. Available: {', '.join(ms) or 'none'}")
    return ms[agent_id]


def _ctx(s, agent_id):
    return Context.build(s, _manifest(s, agent_id))


def cmd_init(s, a):
    from .store import Store
    Store(s.database_url).init()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    print(f"database ready: {s.database_url}")


def cmd_agents(s, a):
    for m in discover(s.agents_dir).values():
        print(f"{m.id:<22} v{m.version:<8} tier {m.tier}  editions={','.join(m.editions)}  jobs={[j['name'] for j in m.jobs]}")


def cmd_run(s, a):
    from .scheduler import run_job
    res = run_job(s, _manifest(s, a.agent), a.job)
    print(json.dumps({k: v for k, v in res.items() if k != "ranked"}, indent=2, default=str))


def cmd_schedule(s, a):  # pragma: no cover
    from .scheduler import loop
    loop(s, discover(s.agents_dir), a.tick)


def cmd_tools(s, a):
    from .mcp_server import describe
    print(describe(s, _manifest(s, a.agent)))


def cmd_call(s, a):
    from .mcp_server import bind_tools
    tools = bind_tools(_ctx(s, a.agent))
    if a.tool not in tools:
        sys.exit(f"unknown tool '{a.tool}'. Available: {', '.join(tools)}")
    print(json.dumps(tools[a.tool](**json.loads(a.args or "{}")), indent=2, default=str))


def cmd_serve(s, a):  # pragma: no cover
    from .mcp_server import serve
    serve(s, _manifest(s, a.agent), a.transport, a.host, a.port)


def cmd_serve_api(s, a):  # pragma: no cover
    from .api import serve
    serve(s, a.host, a.port)


def cmd_approvals(s, a):
    ctx = _ctx(s, a.agent)
    if a.action == "list":
        for r in ctx.approvals.list(None if a.all else "pending", all_agents=a.all_agents):
            print(f"#{r['id']:<5} {r['status']:<9} {r['action']:<18} {json.dumps(r['payload'])[:110]}")
    elif a.action in ("approve", "reject"):
        from .approval_policy import ApprovalRefused
        edits = {k: v for k, v in (("subject", a.subject), ("body", a.body)) if v is not None} or None
        if edits and len(a.ids) != 1:
            raise SystemExit("--subject and --body edit one approval at a time")
        for rid in a.ids:
            try:
                ctx.approvals.decide(int(rid), a.action == "approve", by=a.by, edits=edits)
            except ApprovalRefused as e:
                raise SystemExit(f"#{rid} not approved: {e}")
        print(f"{a.action}d: {', '.join(a.ids)}")
    elif a.action == "execute":
        from .agents import load_module
        from .executors import register_core_executors
        register_core_executors(ctx)
        jobs = load_module(ctx.manifest, "jobs")
        if jobs is not None and hasattr(jobs, "register_executors"):
            jobs.register_executors(ctx)
        print(json.dumps(ctx.approvals.execute_approved(dry_run=a.dry_run), indent=2, default=str))


def cmd_import(s, a):
    from .importers import RECORD_IMPORTERS
    ctx = _ctx(s, a.agent)
    print(json.dumps(RECORD_IMPORTERS[a.kind](ctx, Path(a.path)), indent=2))


def cmd_ask(s, a):
    from .assistant import Assistant
    ans = Assistant(s, agents=a.agents.split(",") if a.agents else None).ask(" ".join(a.question))
    print(ans.text)
    if a.trace:
        print(json.dumps(ans.trace, indent=2, default=str))


def cmd_assistant(s, a):  # pragma: no cover - interactive
    from .assistant import Assistant
    bot = Assistant(s, agents=a.agents.split(",") if a.agents else None)
    print(f"GTM assistant: {len(bot.tools)} tools from {len(bot.manifests)} agents. Ctrl-D to quit.")
    history = []
    while True:
        try:
            q = input("> ").strip()
        except EOFError:
            break
        if not q:
            continue
        ans = bot.ask(q, history)
        print(ans.text + "\n")
        if ans.text.strip():
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": ans.text}]
        history = history[-12:]


def cmd_slack_bot(s, a):  # pragma: no cover
    from .assistant import run_slack_bot
    run_slack_bot(s)


def cmd_models(s, a):
    from .budgets import Budgets
    from .gateway import check_models
    from .store import Store
    st = Store(s.database_url); st.init()
    res = check_models(s, Budgets(st, agent="core"))
    print(json.dumps(res, indent=2))
    sys.exit(0 if any(v["ok"] for v in res.values()) else 1)


def cmd_sync(s, a):
    from .sync import sync_all
    print(json.dumps(sync_all(_ctx(s, a.agent)), indent=2))


def cmd_handoffs(s, a):
    from .handoffs import Handoffs
    from .store import Store
    st = Store(s.database_url); st.init()
    for h in Handoffs(st, "core").all(None if a.all else "pending"):
        print(f"#{h['id']:<5} {h['status']:<9} {h['from_agent']} -> {h['to_agent']:<20} {h['kind']:<18} {h['ref']}")


def cmd_drafts(s, a):
    from .store import Store
    st = Store(s.database_url); st.init()
    for d in st.drafts(a.agent, a.status, a.limit):
        print(f"#{d['id']:<5} {d['agent']:<20} {d['kind']:<16} {d['status']:<8} gate {d['gate_score']}/40 "
              f"[{d['source']}] {d['subject'] or ''}")
        if a.full:
            print("    " + (d["body"] or "").replace("\n", "\n    ") + "\n")


def cmd_usage(s, a):
    ctx = _ctx(s, a.agent)
    print(json.dumps({**ctx.budgets.usage(), "paused": ctx.budgets.paused(),
                      "daily_token_budget": ctx.budgets.daily_tokens, "monthly_usd_budget": ctx.budgets.monthly_usd},
                     indent=2))


def cmd_resume(s, a):
    _ctx(s, a.agent).budgets.resume()
    print("resumed")


def cmd_selftest(s, a):
    from .selftest import run
    report = run(s)
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if report["ok"] else 1)


def cmd_eval(s, a):
    sys.path.insert(0, str(Path.cwd()))
    from evals.runner import run_agent_evals
    res = run_agent_evals(_manifest(s, a.agent))
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["passed"] else 1)


def cmd_license(s, a):
    from . import license as lic
    if a.action == "keygen":
        priv, pub = lic.keygen(a.out)
        print(f"private key (keep offline, never commit): {priv}\npublic key (ship in core/gtm_core/license_pub.pem): {pub}")
    elif a.action == "issue":
        doc = lic.issue(Path(a.key).read_bytes(), a.customer, a.agents.split(","), a.expires)
        Path(a.out).write_text(json.dumps(doc, indent=2))
        print(f"wrote {a.out}")
    elif a.action == "verify":
        print(json.dumps(lic.load_and_verify(a.path or s.license_path), indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="gtm", description=f"GTM agents runtime v{__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("agents").set_defaults(fn=cmd_agents)
    r = sub.add_parser("run"); r.add_argument("agent"); r.add_argument("job"); r.set_defaults(fn=cmd_run)
    sc = sub.add_parser("schedule"); sc.add_argument("--tick", type=int, default=30); sc.set_defaults(fn=cmd_schedule)
    t = sub.add_parser("tools"); t.add_argument("agent"); t.set_defaults(fn=cmd_tools)
    c = sub.add_parser("call"); c.add_argument("agent"); c.add_argument("tool"); c.add_argument("--args", default="{}")
    c.set_defaults(fn=cmd_call)
    sv = sub.add_parser("serve-mcp"); sv.add_argument("agent")
    sv.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve)
    sa = sub.add_parser("serve-api"); sa.add_argument("--host", default="127.0.0.1"); sa.add_argument("--port", type=int, default=8787)
    sa.set_defaults(fn=cmd_serve_api)
    ap = sub.add_parser("approvals"); ap.add_argument("agent"); ap.add_argument("action", choices=["list", "approve", "reject", "execute"])
    ap.add_argument("ids", nargs="*"); ap.add_argument("--by", default=os.environ.get("GTM_APPROVER", "operator"))
    ap.add_argument("--subject", default=None); ap.add_argument("--body", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--all-agents", action="store_true")
    ap.set_defaults(fn=cmd_approvals)
    im = sub.add_parser("import"); im.add_argument("agent"); im.add_argument("kind", choices=["accounts", "signals", "outcomes", "contacts", "leads", "deals", "tasks", "meetings"])
    im.add_argument("path"); im.set_defaults(fn=cmd_import)
    u = sub.add_parser("usage"); u.add_argument("agent"); u.set_defaults(fn=cmd_usage)
    rs = sub.add_parser("resume"); rs.add_argument("agent"); rs.set_defaults(fn=cmd_resume)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    sub.add_parser("models").set_defaults(fn=cmd_models)
    ak = sub.add_parser("ask"); ak.add_argument("question", nargs="+"); ak.add_argument("--agents", default="")
    ak.add_argument("--trace", action="store_true"); ak.set_defaults(fn=cmd_ask)
    asst = sub.add_parser("assistant"); asst.add_argument("--agents", default=""); asst.set_defaults(fn=cmd_assistant)
    sub.add_parser("slack-bot").set_defaults(fn=cmd_slack_bot)
    sy = sub.add_parser("sync"); sy.add_argument("agent"); sy.set_defaults(fn=cmd_sync)
    ho = sub.add_parser("handoffs"); ho.add_argument("--all", action="store_true"); ho.set_defaults(fn=cmd_handoffs)
    dr = sub.add_parser("drafts"); dr.add_argument("--agent"); dr.add_argument("--status")
    dr.add_argument("--limit", type=int, default=20); dr.add_argument("--full", action="store_true")
    dr.set_defaults(fn=cmd_drafts)
    e = sub.add_parser("eval"); e.add_argument("agent"); e.set_defaults(fn=cmd_eval)
    li = sub.add_parser("license"); li.add_argument("action", choices=["keygen", "issue", "verify"])
    li.add_argument("--out", default="license.json"); li.add_argument("--key"); li.add_argument("--customer")
    li.add_argument("--agents", default=""); li.add_argument("--expires"); li.add_argument("--path")
    li.set_defaults(fn=cmd_license)
    a = p.parse_args(argv)
    a.fn(get_settings(), a)


if __name__ == "__main__":
    main()
