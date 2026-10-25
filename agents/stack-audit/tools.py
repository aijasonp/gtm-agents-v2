"""Stack Audit MCP tools. Read-only except the memo, which is saved as a draft."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def stack_summary(ctx, file: str = "") -> dict:
    """Spend, seats, utilization, cost per active seat and notice deadlines for every tool in the inventory."""
    return _eng(ctx).summary(ctx, file or None)


def overlap_matrix(ctx, file: str = "") -> dict:
    """Capabilities covered by two or more tools, with each tool's utilization and cost."""
    eng = _eng(ctx)
    m = eng.overlap(eng.enriched(ctx, file or None))
    return {"overlapping": len(m), "matrix": m}


def renewal_calendar(ctx, days: int = 120, file: str = "") -> dict:
    """Tools whose notice deadline (renewal date minus notice days) falls within N days, soonest first."""
    rows = _eng(ctx).calendar(ctx, int(days), file or None)
    return {"count": len(rows), "renewals": rows}


def savings_scenarios(ctx, file: str = "") -> dict:
    """Cut, consolidate, downsize or keep for every tool, with evidence, the condition to meet first and savings."""
    return _eng(ctx).scenarios(ctx, file or None)


def compare_lists(ctx, tool: str, file: str) -> dict:
    """Side by side: a tool's top-account list (CSV or one per line) vs Signal Scout tier A and B accounts."""
    return _eng(ctx).compare(ctx, tool, file)


def cut_memo(ctx, tool: str, side_by_side_file: str = "") -> dict:
    """Draft the tool-cut memo from the audit (saved as a draft). Optional side-by-side file adds the comparison."""
    eng = _eng(ctx)
    sbs = eng.compare(ctx, tool, side_by_side_file) if side_by_side_file else None
    if sbs and sbs.get("error"):
        return sbs
    return eng.memo(ctx, tool, side_by_side=sbs)


TOOLS = {f.__name__: f for f in [stack_summary, overlap_matrix, renewal_calendar, savings_scenarios, compare_lists, cut_memo]}
