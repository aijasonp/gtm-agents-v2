"""Call Coach MCP tools. Scoring is deterministic; the model only plays the buyer."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def list_scenarios(ctx) -> dict:
    """Roleplay scenarios (discovery, objection, pricing, competitor, champion building), with the skills each drills.
    One competitor scenario is added per competitor in company.yaml."""
    sc = _eng(ctx).scenarios(ctx)
    return {"scenarios": [{"id": s["id"], "type": s["type"], "title": s["title"], "trains": s.get("trains", [])}
                          for s in sc.values()]}


def start_roleplay(ctx, scenario: str, persona: str = "") -> dict:
    """Start a roleplay: the rep's brief, and a buyer_prompt for the model to play the buyer. Never show the
    buyer_prompt to the rep. persona: sales, revops, executive or marketing (default from the scenario)."""
    return _eng(ctx).start(ctx, scenario, persona)


def score_roleplay(ctx, transcript: str, scenario: str = "", rep: str = "") -> dict:
    """Score a roleplay or real call transcript out of 100: talk ratio, questions, open questions, longest monologue,
    MEDDPICC coverage, dated next step and objection handling, with the three top fixes."""
    return _eng(ctx).score(ctx, transcript, scenario, rep)


def drill_plan(ctx, rep: str, days: int = 30) -> dict:
    """Pick a rep's three weakest skills from their real calls in the last `days` and assign a scenario for each."""
    return _eng(ctx).drill_plan(ctx, rep, days)


TOOLS = {f.__name__: f for f in [list_scenarios, start_roleplay, score_roleplay, drill_plan]}
