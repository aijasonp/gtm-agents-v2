"""MEDDPICC qualification scoring and stage-aware gap detection.

Each element is scored 0 (missing), 1 (partial / claimed) or 2 (confirmed with evidence).
A deal record stores `meddpicc` as {element: {"score": 0-2, "evidence": "...", "source": "..."}}
or as plain strings (non-empty string = 1, unless it starts with "confirmed:").
"""
from __future__ import annotations

ELEMENTS = ["metrics", "economic_buyer", "decision_criteria", "decision_process", "paper_process",
            "identify_pain", "champion", "competition"]
LABELS = {"metrics": "Metrics", "economic_buyer": "Economic buyer", "decision_criteria": "Decision criteria",
          "decision_process": "Decision process", "paper_process": "Paper process", "identify_pain": "Identified pain",
          "champion": "Champion", "competition": "Competition"}

# Elements that should be at least partial (1) or confirmed (2) by each stage. Customers override in YAML.
DEFAULT_STAGE_REQUIREMENTS = {
    "discovery": {"identify_pain": 1},
    "qualification": {"identify_pain": 2, "metrics": 1, "champion": 1},
    "evaluation": {"identify_pain": 2, "metrics": 1, "champion": 1, "decision_criteria": 1, "decision_process": 1,
                   "economic_buyer": 1, "competition": 1},
    "proposal": {"identify_pain": 2, "metrics": 2, "champion": 2, "decision_criteria": 2, "decision_process": 2,
                 "economic_buyer": 1, "competition": 1, "paper_process": 1},
    "negotiation": {e: 2 for e in ELEMENTS},
    "commit": {e: 2 for e in ELEMENTS},
}


def normalize(raw) -> dict[str, dict]:
    out = {}
    raw = raw or {}
    for e in ELEMENTS:
        v = raw.get(e)
        if isinstance(v, dict):
            s = int(v.get("score", 1 if v.get("evidence") else 0))
            out[e] = {"score": max(0, min(2, s)), "evidence": v.get("evidence", ""), "source": v.get("source", "")}
        elif isinstance(v, (int, float)):
            out[e] = {"score": max(0, min(2, int(v))), "evidence": "", "source": ""}
        elif isinstance(v, str) and v.strip():
            conf = v.lower().startswith("confirmed:")
            out[e] = {"score": 2 if conf else 1, "evidence": v.split(":", 1)[1].strip() if conf else v.strip(), "source": "crm"}
        else:
            out[e] = {"score": 0, "evidence": "", "source": ""}
    return out


def merge_evidence(current: dict, found: dict[str, list[str]], source: str) -> dict:
    """Raise missing elements to partial (1) when new evidence is found. Never lowers a score and
    never auto-confirms: confirmation (2) needs a human or an explicit CRM value."""
    cur = normalize(current)
    for e, quotes in (found or {}).items():
        if e in cur and quotes and cur[e]["score"] == 0:
            cur[e] = {"score": 1, "evidence": quotes[0][:300], "source": source}
    return cur


def score(raw) -> dict:
    m = normalize(raw)
    total = sum(v["score"] for v in m.values())
    return {"elements": m, "total": total, "max": 2 * len(ELEMENTS), "pct": round(100 * total / (2 * len(ELEMENTS)))}


def stage_key(stage: str | None, aliases: dict[str, list[str]] | None = None) -> str:
    s = (stage or "").lower()
    for key, names in (aliases or {}).items():
        if any(n.lower() == s or n.lower() in s for n in names):
            return key
    for key in DEFAULT_STAGE_REQUIREMENTS:
        if key in s:
            return key
    return "discovery"


def gaps(raw, stage: str | None, requirements: dict | None = None, aliases: dict | None = None) -> list[dict]:
    reqs = (requirements or DEFAULT_STAGE_REQUIREMENTS).get(stage_key(stage, aliases), {})
    m = normalize(raw)
    out = []
    for e, need in reqs.items():
        have = m[e]["score"]
        if have < need:
            out.append({"element": e, "label": LABELS[e], "have": have, "need": need,
                        "kind": "missing" if have == 0 else "unconfirmed"})
    return out
