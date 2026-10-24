"""`gtm` command line: the one interface the customer's ops person needs."""
from __future__ import annotations

import argparse
import json
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
    serve(s, _manifest(s, a.agent), a.transport)


def cmd_approvals(s, a):
    ctx = _ctx(s, a.agent)
    if a.action == "list":
        for r in ctx.approvals.list(None if a.all else "pending"):
            print(f"#{r['id']:<5} {r['status']:<9} {r['action']:<18} {json.dumps(r['payload'])[:110]}")
    elif a.action in ("approve", "reject"):
        for rid in a.ids:
            ctx.approvals.decide(int(rid), a.action == "approve", by=a.by)
        print(f"{a.action}d: {', '.join(a.ids)}")
    elif a.action == "execute":
        from .agents import load_module
        jobs = load_module(ctx.manifest, "jobs")
        if jobs is not None and hasattr(jobs, "register_executors"):
            jobs.register_executors(ctx)
        print(json.dumps(ctx.approvals.execute_approved(dry_run=a.dry_run), indent=2, default=str))


def cmd_import(s, a):
    from .importers import import_accounts, import_signals, import_outcomes
    ctx = _ctx(s, a.agent)
    fn = {"accounts": import_accounts, "signals": import_signals, "outcomes": import_outcomes}[a.kind]
    print(json.dumps(fn(ctx, Path(a.path)), indent=2))


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
    sv.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"]); sv.set_defaults(fn=cmd_serve)
    ap = sub.add_parser("approvals"); ap.add_argument("agent"); ap.add_argument("action", choices=["list", "approve", "reject", "execute"])
    ap.add_argument("ids", nargs="*"); ap.add_argument("--by", default="operator"); ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true"); ap.set_defaults(fn=cmd_approvals)
    im = sub.add_parser("import"); im.add_argument("agent"); im.add_argument("kind", choices=["accounts", "signals", "outcomes"])
    im.add_argument("path"); im.set_defaults(fn=cmd_import)
    u = sub.add_parser("usage"); u.add_argument("agent"); u.set_defaults(fn=cmd_usage)
    rs = sub.add_parser("resume"); rs.add_argument("agent"); rs.set_defaults(fn=cmd_resume)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    e = sub.add_parser("eval"); e.add_argument("agent"); e.set_defaults(fn=cmd_eval)
    li = sub.add_parser("license"); li.add_argument("action", choices=["keygen", "issue", "verify"])
    li.add_argument("--out", default="license.json"); li.add_argument("--key"); li.add_argument("--customer")
    li.add_argument("--agents", default=""); li.add_argument("--expires"); li.add_argument("--path")
    li.set_defaults(fn=cmd_license)
    a = p.parse_args(argv)
    a.fn(get_settings(), a)


if __name__ == "__main__":
    main()
