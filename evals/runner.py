"""Release gate: run an agent's golden cases against a throwaway in-memory database.

Every release must pass `python -m evals.runner <agent>` (or `gtm eval <agent>`).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

from gtm_core.agents import Context, Manifest, discover, load_module
from gtm_core.config import Settings
from gtm_core.connectors.base import NullCRM
from gtm_core.connectors.slack import Slack
from gtm_core.scoring import signal_id
from gtm_core.store import Store

TIER_RANK = {"A": 4, "B": 3, "C": 2, "D": 1, "X": 0}


def _ctx(m: Manifest) -> Context:
    s = Settings()
    s.slack_webhook_url = s.slack_bot_token = None
    slack = Slack(s)
    slack.post = lambda text, **kw: slack.sent.append({"text": text}) or {"ok": True}
    return Context.build(s, m, store=Store("sqlite:///:memory:"), crm=NullCRM(), slack=slack)


def eval_signal_scout(m: Manifest, spec: dict) -> list[dict]:
    ctx = _ctx(m)
    eng = load_module(m, "engine")
    tax = eng.taxonomy(ctx)
    now = datetime.fromisoformat(spec["now"])
    for a in spec["accounts"]:
        ctx.store.upsert_account(a)
    dupes = 0
    for s in spec["signals"]:
        sig = {**s, "id": signal_id(s["account_id"], s["signal_type"], s.get("url", ""), s["observed_at"]),
               "category": tax.types[s["signal_type"]].category}
        if not ctx.store.add_signal(sig):
            dupes += 1
    ranked = {r.account_id: r for r in eng.score_all(ctx, now=now, persist=False)}
    order = [r for r in sorted(ranked.values(), key=lambda r: -r.score)]
    pos = {r.account_id: i for i, r in enumerate(order)}
    ex = spec["expect"]
    results = []

    def add(name, ok, detail):
        results.append({"case": name, "passed": bool(ok), "detail": detail})

    for aid, t in ex.get("tiers", {}).items():
        add(f"tier {aid} == {t}", ranked[aid].tier == t, f"got {ranked[aid].tier} ({ranked[aid].score})")
    for aid, t in ex.get("min_tier", {}).items():
        add(f"tier {aid} >= {t}", TIER_RANK[ranked[aid].tier] >= TIER_RANK[t], f"got {ranked[aid].tier} ({ranked[aid].score})")
    for aid, t in ex.get("max_tier", {}).items():
        add(f"tier {aid} <= {t}", TIER_RANK[ranked[aid].tier] <= TIER_RANK[t], f"got {ranked[aid].tier} ({ranked[aid].score})")
    for hi, lo in ex.get("order", []):
        add(f"{hi} above {lo}", pos[hi] < pos[lo], f"{ranked[hi].score} vs {ranked[lo].score}")
    for aid, rule in ex.get("stack_rule", {}).items():
        got = ranked[aid].signals.rule if ranked[aid].signals else None
        add(f"{aid} stack rule {rule}", got == rule, f"got {got}")
    if "duplicates_ignored" in ex:
        add("duplicate signals ignored", dupes == ex["duplicates_ignored"], f"{dupes} ignored")
    return results


def eval_copy_qa_gate(m: Manifest, spec: dict) -> list[dict]:
    ctx = _ctx(m)
    tools = load_module(m, "tools").TOOLS
    results = []
    for case in spec["cases"]:
        res = tools["check_copy"](ctx, case["text"])
        results.append({"case": case["name"], "passed": res["passed"] == case["expect_pass"],
                        "detail": f"score {res['score']}/40, expected pass={case['expect_pass']}"})
    return results


EVALUATORS = {"signal-scout": eval_signal_scout, "copy-qa-gate": eval_copy_qa_gate}


def run_agent_evals(m: Manifest) -> dict:
    if not m.evals or m.id not in EVALUATORS:
        return {"agent": m.id, "passed": False, "error": "no evals defined"}
    spec = yaml.safe_load(m.path(m.evals).read_text())
    cases = EVALUATORS[m.id](m, spec)
    passed = sum(c["passed"] for c in cases)
    return {"agent": m.id, "version": m.version, "passed": passed == len(cases),
            "score": f"{passed}/{len(cases)}", "cases": cases}


if __name__ == "__main__":
    agents_dir = Path(__file__).resolve().parents[1] / "agents"
    ms = discover(agents_dir)
    targets = sys.argv[1:] or list(ms)
    report = [run_agent_evals(ms[t]) for t in targets]
    print(json.dumps(report, indent=2))
    sys.exit(0 if all(r["passed"] for r in report) else 1)
