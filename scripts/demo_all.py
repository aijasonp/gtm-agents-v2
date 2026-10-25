"""End-to-end demo: every agent runs once on the fictional sample data, in pipeline order.

    make demo            # or: PYTHONPATH=core:. python3 scripts/demo_all.py

Uses a throwaway SQLite file (demo.db), no CRM, no Slack (messages print), no model key
(template drafts). Set ANTHROPIC_API_KEY or OPENAI_API_KEY to see model-written drafts.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "core"), str(ROOT)]
os.chdir(ROOT)
os.environ.setdefault("DATABASE_URL", "sqlite:///demo.db")
for k in ("SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN", "HUBSPOT_TOKEN", "SALESFORCE_ACCESS_TOKEN"):
    os.environ.pop(k, None)

from gtm_core.agents import Context, discover  # noqa: E402
from gtm_core.config import get_settings  # noqa: E402
from gtm_core.importers import RECORD_IMPORTERS  # noqa: E402
from gtm_core.scheduler import run_job  # noqa: E402
from gtm_core.store import Store  # noqa: E402

PIPELINE = [
    ("signal-scout", "daily_sweep", "Score every account on ICP fit plus buying signals"),
    ("lead-triage", "triage_inbox", "Qualify, route and draft for new inbound and event leads"),
    ("meeting-intelligence", "process_meetings", "Analyze call transcripts, hand off recaps and MEDDPICC evidence"),
    ("deal-inspection", "apply_evidence", "Apply call evidence to deals (proposed, needs approval)"),
    ("deal-inspection", "weekly_inspection", "Inspect every open deal: risk, gaps, recommendation"),
    ("seller-follow-up", "process_recaps", "Draft recap emails, notes and tasks from calls"),
    ("seller-follow-up", "daily_digest", "What each rep needs to follow up on today"),
    ("sales-execution", "precall_briefs", "Pre-call briefs for upcoming meetings"),
    ("icp-outbound", "weekly_list_build", "Target accounts and contacts, conflicts removed"),
    ("icp-outbound", "daily_drafts", "Signal-led sequences drafted and gated"),
    ("social-signals", "ingest_engagement", "LinkedIn and YouTube engagement turned into rep signals"),
    ("reply-desk", "process_replies", "Replies sorted: stops, opt-outs, out of office, hot replies"),
    ("enrichment", "enrich_queue", "Email and phone waterfall for target contacts"),
    ("rep-brief", "daily_briefs", "One brief per AE: top accounts, people, signals, gaps, next actions"),
    ("product-marketing", "weekly_field_report", "Competitor, objection and win/loss trends from the field"),
    ("revenue-pulse", "weekly_pulse", "Leadership pipeline summary"),
    ("forecast-prep", "forecast_prep", "Forecast call prep for AEs, managers and execs"),
    ("stack-audit", "monthly_utilization", "Tool spend, utilization, overlap and savings"),
    ("ops-monitor", "health_check", "Runtime health: missed jobs, stuck approvals, spend"),
]


def main() -> int:
    db = Path("demo.db")
    for f in (db, Path("demo.db-wal"), Path("demo.db-shm")):
        f.unlink(missing_ok=True)
    s = get_settings()
    s.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY") or None
    s.openai_api_key = os.environ.get("OPENAI_API_KEY") or None
    ms = discover(s.agents_dir)
    store = Store(s.database_url)
    store.init()
    ctx = Context.build(s, ms["signal-scout"], store=store)
    sample = Path("data/sample")
    for kind, path in [("accounts", "accounts.csv"), ("contacts", "contacts.csv"), ("signals", "signals.csv"),
                       ("outcomes", "outcomes.csv"), ("deals", "deals.csv"), ("tasks", "tasks.csv"),
                       ("leads", "leads.csv"), ("meetings", "meetings"), ("meetings", "meetings.csv")]:
        print(f"import {kind:<9} {RECORD_IMPORTERS[kind](ctx, sample / path)}")
    import shutil
    for src, inbox in [("replies.json", "data/replies/inbox"), ("engagement.csv", "data/engagement/inbox")]:
        Path(inbox).mkdir(parents=True, exist_ok=True)
        for old in Path(inbox).parent.glob("processed/*"):
            old.unlink()
        shutil.copy(sample / src, Path(inbox) / src)

    for agent, job, what in PIPELINE:
        print(f"\n{'=' * 78}\n{ms[agent].name} :: {job}\n{what}\n{'-' * 78}")
        res = run_job(s, ms[agent], job, store=store)
        summary = {k: v for k, v in res.items() if not isinstance(v, (list, dict)) or k in ("tiers", "inbox")}
        print(f"result: {summary}")

    pending = store.query("SELECT agent, action, COUNT(*) n FROM approvals WHERE status='pending' GROUP BY agent, action ORDER BY agent")
    hand = store.query("SELECT from_agent, to_agent, kind, status, COUNT(*) n FROM handoffs GROUP BY 1,2,3,4")
    drafts = store.query("SELECT agent, kind, source, COUNT(*) n, MIN(gate_score) lo FROM drafts GROUP BY 1,2,3")
    print(f"\n{'=' * 78}\nWaiting for human approval (nothing was written or sent):")
    for r in pending:
        print(f"  {r['agent']:<22} {r['action']:<16} {r['n']}")
    print("Handoffs between agents:")
    for r in hand:
        print(f"  {r['from_agent']} -> {r['to_agent']:<20} {r['kind']:<18} {r['status']:<9} {r['n']}")
    print("Drafts:")
    for r in drafts:
        print(f"  {r['agent']:<22} {r['kind']:<16} {r['source']:<9} {r['n']} (lowest gate score {r['lo']}/40)")
    print("\nNext: `gtm drafts --full`, `gtm approvals <agent> list`, `gtm handoffs --all` with DATABASE_URL=sqlite:///demo.db")
    return 0


if __name__ == "__main__":
    sys.exit(main())
