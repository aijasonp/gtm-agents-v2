"""Account Health scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from gtm_core.agents import load_module
from gtm_core.sync import sync_all


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def sync_customers(ctx) -> dict:
    """Read accounts, contacts and deals from the CRM into the local store (read-only)."""
    return sync_all(ctx)


def import_usage_inbox(ctx) -> dict:
    """Load every usage export dropped in the inbox folder (CSV or JSON), then move it to processed/."""
    inbox = Path(ctx.manifest.config.get("usage_inbox", "data/usage/inbox"))
    if not inbox.exists():
        return {"files": 0, "stored": 0}
    eng, files, stored, errors = _eng(ctx), 0, 0, []
    done = inbox.parent / "processed"
    for f in sorted(p for p in inbox.iterdir() if p.suffix.lower() in (".csv", ".json")):
        r = eng.import_usage(ctx, f, source=f.name)
        files, stored, errors = files + 1, stored + r["stored"], errors + r["errors"]
        done.mkdir(exist_ok=True)
        f.rename(done / f.name)
    return {"files": files, "stored": stored, "errors": errors[:20]}


def daily_health(ctx, now: datetime | None = None) -> dict:
    """Assess every customer, store results, queue a CRM task for each new save or expansion play (approval
    required), and alert the owner channel on changes and renewal-window entries."""
    eng = _eng(ctx)
    now = eng._now(now)
    res = eng.assess_all(ctx, now=now)
    ch = eng.changes(ctx, res, now)
    lines = []
    for x in ch["new_save"]:
        lines.append(f"New renewal risk: {x['name']} ({x['owner'] or 'no owner'}) risk {x['risk']}: " + "; ".join(x["risk_drivers"][:2]))
    for x in ch["new_expand"]:
        lines.append(f"New expansion play: {x['name']} ({x['owner'] or 'no owner'}) expansion {x['expansion']}: "
                     + "; ".join(x["expansion_drivers"][:2]))
    for x in ch["entered_renewal_window"]:
        lines.append(f"Renewal in {x['days_to_renewal']} days and {x['band'].replace('_', ' ')}: {x['name']} ({eng.money(x['arr'])})")
    if lines:
        ctx.slack.post("*Account Health changes*\n" + "\n".join(lines))
    return {"customers": len(res), "new_save": [x["name"] for x in ch["new_save"]],
            "new_expand": [x["name"] for x in ch["new_expand"]],
            "entered_renewal_window": [x["name"] for x in ch["entered_renewal_window"]],
            "tasks_queued": len(ch["tasks_queued"])}


def weekly_portfolio(ctx, now: datetime | None = None) -> dict:
    """Post the portfolio report: ARR at risk, watch list, expansion plays, renewals in the window."""
    eng = _eng(ctx)
    res = eng.assess_all(ctx, now=now, persist=False)
    ctx.slack.post(eng.format_report(res, int(ctx.manifest.config.get("report_size", 10))))
    return eng.portfolio(res)
