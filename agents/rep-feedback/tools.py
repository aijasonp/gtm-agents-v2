"""Rep Feedback MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def submit_feedback(ctx, agent: str, text: str, draft_id: int | None = None, rep: str = "") -> dict:
    """File a rep's feedback on an agent's output. Returns the file it would change and why."""
    return _eng(ctx).submit(ctx, agent, text, draft_id, rep)


def list_feedback(ctx, status: str = "open") -> dict:
    """Feedback by status: open, proposed, queued, pr_opened. Empty status lists all."""
    rows = _eng(ctx).feedback(ctx, status)
    return {"count": len(rows), "feedback": rows}


def propose_change(ctx, feedback_ids: list[str]) -> dict:
    """Draft the rule lines and a diff for feedback that points at the same file. Changes nothing."""
    return _eng(ctx).propose(ctx, feedback_ids)


def open_pr(ctx, proposal_id: str) -> dict:
    """Queue a GitHub pull request for a proposal. A person must approve before the PR is opened."""
    return _eng(ctx).open_pr(ctx, proposal_id)


TOOLS = {f.__name__: f for f in [submit_feedback, list_feedback, propose_change, open_pr]}
