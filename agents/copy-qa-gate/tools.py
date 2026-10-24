"""Copy QA Gate MCP tools."""
from __future__ import annotations

from gtm_core import copy_gate


def _banned(ctx):
    return copy_gate.load_banned(ctx.manifest.path(ctx.manifest.config.get("banned_file", "")))


def check_copy(ctx, text: str, max_words: int = 0) -> dict:
    """Score one piece of outbound copy (0-40, 32 passes) and list exactly what to fix."""
    cfg = ctx.manifest.config
    r = copy_gate.check(text, _banned(ctx), max_words=max_words or int(cfg.get("max_words", 120)),
                        pass_mark=int(cfg.get("pass_mark", 32)))
    return {"score": r.score, "max": 40, "passed": r.passed, "fix": r.failures(), "checks": r.checks}


def check_batch(ctx, texts: list[str]) -> dict:
    """Score several drafts at once; returns pass rate and the failures per draft."""
    out = [check_copy(ctx, t) for t in texts]
    return {"pass_rate": round(sum(o["passed"] for o in out) / len(out), 2) if out else 0.0,
            "results": [{"index": i, "score": o["score"], "passed": o["passed"], "fix": o["fix"]} for i, o in enumerate(out)]}


TOOLS = {"check_copy": check_copy, "check_batch": check_batch}
