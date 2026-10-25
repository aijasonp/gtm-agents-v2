"""Deal Inspection MCP tools."""
from __future__ import annotations

from gtm_core import meddpicc, writer
from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _deal(ctx, deal: str):
    return _eng(ctx).find_deal(ctx, deal)


def inspect_deal(ctx, deal: str) -> dict:
    """Full inspection of one deal (id, CRM id, name or account): risk, drivers, MEDDPICC gaps, recommendation, fixes."""
    d = _deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found; import deals or run sync_deals"}
    eng = _eng(ctx)
    i = eng.inspect(ctx, d)
    eng.record(ctx, i)
    return {**i, "text": eng.format_one(i)}


def list_at_risk(ctx, owner: str = "", limit: int = 10, min_risk: int = 30) -> dict:
    """Open deals at or above a risk score, worst first. Optional owner filter."""
    res = [i for i in _eng(ctx).inspect_all(ctx, owner=owner, persist=False) if i["risk"] >= min_risk][:limit]
    keep = ("deal_id", "name", "owner", "stage", "amount", "risk", "recommendation", "drivers")
    return {"count": len(res), "deals": [{k: i[k] for k in keep} for i in res]}


def meddpicc_gaps(ctx, deal: str) -> dict:
    """MEDDPICC scores for a deal and the gaps for its current stage (missing data vs unconfirmed)."""
    d = _deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found"}
    eng = _eng(ctx)
    r = eng.rules(ctx)
    s = meddpicc.score(d.get("meddpicc"))
    return {"deal": d.get("name"), "stage": d.get("stage"), "stage_key": eng.stage_key(ctx, d.get("stage")),
            "total": s["total"], "max": s["max"], "elements": s["elements"],
            "gaps": meddpicc.gaps(d.get("meddpicc"), d.get("stage"), r.get("meddpicc_requirements"), r.get("stage_aliases")),
            "negative_evidence": eng.negative_evidence(ctx, d)}


def update_meddpicc(ctx, deal: str, element: str, evidence: str, confirmed: bool = False) -> dict:
    """Record MEDDPICC evidence for a deal. Updates the local record and queues the CRM field write for approval.
    element: metrics, economic_buyer, decision_criteria, decision_process, paper_process, identify_pain, champion, competition."""
    if element not in meddpicc.ELEMENTS:
        return {"error": f"element must be one of {meddpicc.ELEMENTS}"}
    if not evidence.strip():
        return {"error": "evidence is required: quote what the buyer said or did"}
    d = _deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found"}
    return _eng(ctx).set_element(ctx, d, element, evidence, confirmed)


def recommend_action(ctx, deal: str) -> dict:
    """Progress, fix or disqualify for one deal, with the rule that fired and the specific next actions."""
    d = _deal(ctx, deal)
    if not d:
        return {"error": f"deal '{deal}' not found"}
    eng = _eng(ctx)
    i = eng.inspect(ctx, d)
    fallback = (f"{i['recommendation'].upper()}: {i['rule']}. " + " ".join(i["actions"])).strip()
    text, src = writer.narrate(ctx, "Explain this deal recommendation to the deal owner in three sentences. "
                               "Keep the recommendation and the actions exactly as given.",
                               {k: i[k] for k in ("name", "stage", "risk", "drivers", "recommendation", "rule", "actions",
                                                  "negative_evidence")}, fallback, max_words=90)
    return {"deal": i["name"], "recommendation": i["recommendation"], "rule": i["rule"], "risk": i["risk"],
            "actions": i["actions"], "summary": text, "summary_source": src}


TOOLS = {f.__name__: f for f in [inspect_deal, list_at_risk, meddpicc_gaps, update_meddpicc, recommend_action]}
