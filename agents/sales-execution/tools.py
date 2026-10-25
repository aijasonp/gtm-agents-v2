"""Sales Execution MCP tools. Read-only: they assemble facts, nothing is written to the CRM."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def precall_brief(ctx, meeting: str) -> dict:
    """Pre-call brief for a meeting (id or title) or an account (id or domain): people, deal, gaps, history, plan."""
    eng = _eng(ctx)
    m = eng.find_meeting(ctx, meeting)
    if m:
        return eng.brief_with_plan(ctx, meeting=m)
    acct = ctx.store.account(meeting)
    if acct:
        return eng.brief_with_plan(ctx, account_id=acct["id"])
    return {"error": f"no meeting or account matching '{meeting}'"}


def meddpicc_questions(ctx, deal: str) -> dict:
    """Questions to close each MEDDPICC gap the deal's current stage requires."""
    d = _eng(ctx).find_deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found"}
    return _eng(ctx).questions_for(ctx, d)


def objection_help(ctx, objection: str) -> dict:
    """How to handle an objection: pass the buyer's words or a category (price, timing, authority,
    competition, need, security, integration). Adds competitor positioning when a competitor is named."""
    return _eng(ctx).objection(ctx, objection)


def proposal_outline(ctx, deal: str) -> dict:
    """Proposal outline filled from the deal and its MEDDPICC evidence. Missing inputs are flagged, never invented."""
    d = _eng(ctx).find_deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found"}
    return _eng(ctx).proposal(ctx, d)


def next_steps_summary(ctx, deal: str) -> dict:
    """Every open next step for a deal (deal record, tasks, last call), with overdue items marked."""
    d = _eng(ctx).find_deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found"}
    return _eng(ctx).next_steps(ctx, d)


TOOLS = {f.__name__: f for f in [precall_brief, meddpicc_questions, objection_help, proposal_outline, next_steps_summary]}
