"""ICP Outbound scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.guardrails import StepCounter


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def weekly_list_build(ctx, now: datetime | None = None) -> dict:
    """Build the ranked target list and post it to Slack. Writes nothing to the CRM."""
    eng = _eng(ctx)
    res = eng.build_list(ctx, now)
    ctx.store.set_state("icp_outbound_list", [a["account_id"] for a in res["accounts"]])
    ctx.slack.post(eng.format_list(res, int(ctx.manifest.config.get("list_size", 25))))
    return {"targets": res["count"], "excluded": len(res["excluded"]),
            "active_pipeline_conflicts": sum(1 for e in res["excluded"]
                                             if any(r.startswith("active pipeline") for r in e["reasons"]))}


def daily_drafts(ctx, now: datetime | None = None) -> dict:
    """Draft sequences for the top targets not yet drafted, up to daily_cap contacts."""
    eng = _eng(ctx)
    cap = int(ctx.manifest.config.get("daily_cap", 10))
    res = eng.build_list(ctx, now)
    drafted, queued, skipped = 0, 0, 0
    with StepCounter(limit=max(cap * 3, ctx.settings.max_loop_steps)) as steps:
        for a in res["accounts"]:
            if drafted >= cap:
                break
            acct = ctx.store.account(a["account_id"])
            for c in a["contacts"]:
                if drafted >= cap:
                    break
                if eng.already_drafted(ctx, c["contact_id"]):
                    continue
                steps.tick(c["contact_id"])
                out = eng.draft_sequence(ctx, acct, c, now)
                if out.get("skipped"):
                    skipped += 1
                    continue
                drafted += 1
                queued += 1 if out["approval"] else 0
    if drafted:
        ctx.slack.post(f"*ICP Outbound*: drafted {drafted} sequences, {queued} queued for approval. "
                       f"Review: `gtm approvals icp-outbound list`")
    return {"drafted": drafted, "queued": queued, "skipped": skipped}


def weekly_angle_report(ctx, now: datetime | None = None) -> dict:
    """Post open and reply rates by value prop, angle and judged ICP band. Read only."""
    perf = load_module(ctx.manifest, "tools").angle_performance(ctx)
    o = perf["overall"]
    if not o["sends"]:
        return {"sends": 0}
    def fmt(d):
        return "; ".join(f"{k} {v['open_rate']:.0%}/{v['reply_rate']:.0%} ({v['sends']})" for k, v in d.items() if v["sends"])
    ctx.slack.post(f"*ICP Outbound engagement* (open/reply, human opens only): overall {o['open_rate']:.0%}/"
                   f"{o['reply_rate']:.0%} over {o['sends']} sends\nBy value prop: {fmt(perf['by_value_prop'])}\n"
                   f"By angle: {fmt(perf['by_angle'])}\nBy judged ICP: {fmt(perf['by_judged_icp'])}")
    return {"sends": o["sends"], **perf}
