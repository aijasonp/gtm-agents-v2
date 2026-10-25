"""Rep Feedback scheduled jobs and executors."""
from __future__ import annotations

import os

from gtm_core.agents import load_module
from gtm_core.approvals import executor


def weekly_feedback_digest(ctx) -> dict:
    """Weekly: feedback counts by status and the files open feedback points at."""
    d = load_module(ctx.manifest, "engine").digest(ctx)
    if d["total"]:
        lines = [f"*Rep Feedback*: {d['total']} items; " + ", ".join(f"{k} {v}" for k, v in sorted(d["by_status"].items()))]
        lines += [f"- {t}: {n} open" for t, n in d["open_by_target"].items()]
        if d["open_by_target"]:
            lines.append("Ask for a proposal to turn open feedback into a pull request.")
        ctx.slack.post("\n".join(lines))
    return d


_CTX = {}


def register_executors(ctx):
    _CTX["ctx"] = ctx

    @executor("github_pr")
    def _pr(payload: dict) -> dict:
        c = _CTX["ctx"]
        return load_module(c.manifest, "engine").github_pr(
            c, payload, os.environ.get("GITHUB_TOKEN"), os.environ.get("GTM_FEEDBACK_REPO"),
            os.environ.get("GTM_FEEDBACK_BASE") or None)
