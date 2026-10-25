"""Product Marketing MCP tools. Aggregation is deterministic; nothing here writes to the CRM."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def competitor_intel(ctx, competitor: str, since_days: int = 90) -> dict:
    """Mentions and trend, accounts and deals, record and win rate, co-occurring objections and quotes for one competitor."""
    return _eng(ctx).competitor_intel(ctx, competitor, since_days)


def battlecard(ctx, competitor: str, since_days: int = 90) -> dict:
    """Build (and save as a draft) an evidence-backed battlecard for a competitor. Unproven claims go under 'To verify'."""
    card = _eng(ctx).battlecard(ctx, competitor, since_days)
    return {"competitor": card["competitor"], "draft_id": card.get("draft_id"), "text": card["text"],
            "to_verify": card["to_verify"], "objection_gaps": card["objection_gaps"]}


def win_loss_report(ctx, since_days: int = 90) -> dict:
    """Won vs lost: counts, amounts, reasons, cuts by competitor, industry and size, average cycle length."""
    return _eng(ctx).win_loss(ctx, since_days)


def objection_library(ctx, since_days: int = 90) -> dict:
    """Objection categories ranked by frequency with deals affected, quotes, the prepared response and gaps."""
    return _eng(ctx).objection_library(ctx, since_days)


def messaging_brief(ctx, persona_function: str, segment: str = "") -> dict:
    """Message for a buyer function (sales, revops, executive...) and optional segment (mid_market, enterprise)."""
    return _eng(ctx).messaging_brief(ctx, persona_function, segment)


def launch_brief(ctx, feature: str, audience: str = "") -> dict:
    """Launch brief skeleton with only known facts filled in; every gap is a TODO with an owner."""
    return _eng(ctx).launch_brief(ctx, feature, audience)


TOOLS = {f.__name__: f for f in [competitor_intel, battlecard, win_loss_report, objection_library, messaging_brief,
                                 launch_brief]}
