"""Signal Scout scheduled jobs (persistent edition)."""
from __future__ import annotations

from pathlib import Path

from gtm_core.agents import load_module
from gtm_core.approvals import executor
from gtm_core.guardrails import StepCounter
from gtm_core.importers import import_signals
from gtm_core.scoring import reweight


def _engine(ctx):
    return load_module(ctx.manifest, "engine")


def sync_accounts(ctx) -> dict:
    """Pull accounts from the CRM into the local store (read-only)."""
    accts = ctx.crm.list_accounts(limit=int(ctx.manifest.config.get("max_accounts", 5000)))
    for a in accts:
        ctx.store.upsert_account(a)
    return {"synced": len(accts), "crm": ctx.crm.name}


def ingest_inbox(ctx) -> dict:
    """Load any signal files dropped in the inbox folder (CSV or JSON), then archive them."""
    inbox = Path(ctx.manifest.config.get("signal_inbox", "data/signals/inbox"))
    if not inbox.exists():
        return {"files": 0, "added": 0, "duplicates": 0}
    done = inbox.parent / "processed"
    done.mkdir(parents=True, exist_ok=True)
    totals = {"files": 0, "added": 0, "duplicates": 0, "unknown_types": 0}
    with StepCounter(limit=ctx.settings.max_loop_steps) as steps:
        for f in sorted(list(inbox.glob("*.csv")) + list(inbox.glob("*.json"))):
            steps.tick(f.name)
            res = import_signals(ctx, f)
            totals["files"] += 1
            for k in ("added", "duplicates", "unknown_types"):
                totals[k] += res.get(k, 0)
            f.rename(done / f.name)
    return totals


def format_brief(ranked, prev: dict, size: int) -> str:
    top = [r for r in ranked if r.tier in ("A", "B")][:size]
    if not top:
        return "*Signal Scout*: no Tier A or B accounts today."
    lines = [f"*Signal Scout: {len(top)} accounts to work today*"]
    for i, r in enumerate(top, 1):
        delta = ""
        if r.account_id in prev:
            d = r.score - prev[r.account_id]
            delta = f" ({'+' if d >= 0 else ''}{d:.0f})" if abs(d) >= 1 else ""
        else:
            delta = " (new)"
        sig = ", ".join(c.name for c in (r.signals.top[:2] if r.signals else []))
        say = next((c.say_it for c in (r.signals.top if r.signals else []) if c.say_it), "").replace("{", "[").replace("}", "]")
        lines.append(f"{i}. *{r.name}* | {r.tier} {r.score:.0f}{delta} | {sig}" + (f"\n   _Opener angle:_ {say}" if say else ""))
    return "\n".join(lines)


def daily_sweep(ctx) -> dict:
    """Ingest new signals, score every account, post the brief, queue CRM updates for approval."""
    eng = _engine(ctx)
    inbox = ingest_inbox(ctx)
    prev = eng.previous_ranks(ctx)
    ranked = eng.score_all(ctx)
    size = int(ctx.manifest.config.get("brief_size", 20))
    ctx.slack.post(format_brief(ranked, prev, size))

    fields = ctx.manifest.config.get("crm_fields", {})
    queued = 0
    for r in ranked:
        acct = ctx.store.account(r.account_id)
        if not acct or not acct.get("crm_id") or r.tier == "X":
            continue
        if prev.get(r.account_id) is not None and abs(prev[r.account_id] - r.score) < 5:
            continue  # only queue meaningful changes
        ctx.approvals.request("crm_update", {
            "crm_id": acct["crm_id"], "account": r.name,
            "fields": {fields.get("score", "gtm_signal_score"): r.score, fields.get("tier", "gtm_signal_tier"): r.tier,
                       fields.get("reasons", "gtm_signal_reasons"): " | ".join(r.reasons)[:1000]}})
        queued += 1
    tiers = {t: sum(1 for r in ranked if r.tier == t) for t in "ABCDX"}
    return {"accounts": len(ranked), "tiers": tiers, "inbox": inbox, "crm_updates_queued": queued,
            "ranked": [r.as_dict() for r in ranked[:size]]}


def weekly_reweight(ctx, now=None) -> dict:
    """Learn signal weights from outcomes, and judged ICP question weights from email opens and replies."""
    from gtm_core import decision, profile
    changes = reweight(ctx.store, _engine(ctx).taxonomy(ctx))
    lines = []
    if changes:
        lines += ["*Signal Scout weekly learning*"] + [
            f"- {k}: {v['from']} -> {v['to']} (lift {v['lift']}, {v['positive']}/{v['accounts']} positive)"
            for k, v in sorted(changes.items(), key=lambda kv: -abs(kv[1]['to'] - kv[1]['from']))[:10]]
    judged = {}
    cfg = _engine(ctx).judgment(ctx)
    model = decision.get_model(cfg, "icp_fit", profile.company(ctx).get("value_props", [])) if decision.enabled(cfg) else None
    if model:
        lc = cfg.get("learning") or {}
        judged = decision.learn(ctx.store, model, int(lc.get("window_days", 120)), int(lc.get("min_per_side", 20)),
                                weights=lc.get("weights"), now=now)
        moved = {k: v for k, v in judged["questions"].items() if "to" in v}
        if judged["threads"]:
            bands = ", ".join(f"{b}: {r['open_rate']:.0%} open / {r['reply_rate']:.0%} reply ({r['sends']})"
                              for b, r in judged["by_icp_band"].items() if r["sends"])
            lines.append(f"*Judged ICP vs engagement* ({judged['threads']} threads) {bands}")
        lines += [f"- question {k}: x{v['from']} -> x{v['to']} (lift {v['lift']})" for k, v in moved.items()]
    if lines:
        ctx.slack.post("\n".join(lines))
    return {"reweighted": len(changes), "changes": changes, "judged": judged}


# ---- executors for approved actions ----
_CTX = {}


def register_executors(ctx):
    _CTX["ctx"] = ctx

    @executor("crm_update")
    def _crm_update(payload: dict) -> dict:
        return _CTX["ctx"].crm.update_account(payload["crm_id"], payload["fields"])

    @executor("crm_note")
    def _crm_note(payload: dict) -> dict:
        return _CTX["ctx"].crm.add_note(payload["crm_id"], payload["body"])
