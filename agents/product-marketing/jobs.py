"""Product Marketing scheduled jobs (persistent edition)."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module
from gtm_core.guardrails import StepCounter


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def weekly_field_report(ctx, now: datetime | None = None) -> dict:
    """Friday: competitor mention trends, new objections and the week's win/loss, posted to Slack."""
    eng = _eng(ctx)
    r = eng.field_report(ctx, now)
    ctx.slack.post(eng.render_field_report(r))
    return {"competitors": len(r["competitors"]), "new_objections": r["new_objections"], "won": r["won"], "lost": r["lost"]}


def battlecard_refresh(ctx, now: datetime | None = None) -> dict:
    """Monthly: rebuild a card for every known competitor and any new one seen often on calls."""
    eng = _eng(ctx)
    names, new = eng.competitors_to_refresh(ctx, now=now)
    built = []
    with StepCounter(limit=max(ctx.settings.max_loop_steps, 50)) as steps:
        for n in names:
            steps.tick(n)
            card = eng.battlecard(ctx, n, now=now)
            built.append({"competitor": card["competitor"], "draft_id": card["draft_id"], "mentions": card["mentions"],
                          "won": card["won"], "lost": card["lost"]})
    lines = [f"*Product Marketing: {len(built)} battlecards refreshed*"]
    lines += [f"- {b['competitor']}: {b['mentions']} mentions, {b['won']}-{b['lost']} (draft #{b['draft_id']})" for b in built]
    if new:
        lines.append("New competitors on calls, not in company.yaml: " + ", ".join(new) + ". Add their positioning.")
    ctx.slack.post("\n".join(lines))
    return {"refreshed": len(built), "new_competitors": new, "cards": built}
