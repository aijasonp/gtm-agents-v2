"""`gtm selftest`: the report a customer shares when something breaks. Contains no secrets."""
from __future__ import annotations

import platform
import sys

from . import __version__
from .agents import Context, discover
from .config import Settings
from .license import load_and_verify
from .store import Store


def run(s: Settings) -> dict:
    checks: dict[str, dict] = {}

    def ok(name, passed, detail=""):
        checks[name] = {"ok": bool(passed), "detail": detail}

    try:
        st = Store(s.database_url)
        st.init()
        ok("database", True, st.kind)
    except Exception as e:
        ok("database", False, str(e))
        st = None

    try:
        ms = discover(s.agents_dir)
        ok("manifests", bool(ms), ", ".join(f"{m.id}@{m.version}" for m in ms.values()))
    except Exception as e:
        ms = {}
        ok("manifests", False, str(e))

    for m in ms.values():
        try:
            from .mcp_server import bind_tools
            ctx = Context.build(s, m, store=st)
            tools = bind_tools(ctx)
            ok(f"tools:{m.id}", True, ", ".join(tools))
            u = ctx.budgets.usage()
            ok(f"budget:{m.id}", not ctx.budgets.paused(), f"{u['tokens_today']:,} tokens today, ${u['usd_month']:.2f} this month")
        except Exception as e:
            ok(f"tools:{m.id}", False, str(e))

    ok("model_key", bool(s.anthropic_api_key or s.openai_api_key), "set" if (s.anthropic_api_key or s.openai_api_key) else "missing")
    ok("crm", True, s.crm if (s.hubspot_token or s.salesforce_token) else "not configured (CSV import mode)")
    ok("slack", True, "configured" if (s.slack_webhook_url or s.slack_bot_token) else "not configured (stdout)")
    lic = load_and_verify(s.license_path)
    ok("license", lic["valid"] and not lic["expired"], lic["reason"])

    critical = ["database", "manifests"]
    return {"version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
            "ok": all(checks[c]["ok"] for c in critical if c in checks), "checks": checks}
