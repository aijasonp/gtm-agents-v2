"""Job title -> seniority and function. Deterministic, so routing and targeting are repeatable.

Agents can pass their own keyword maps (from a references YAML) to tune this per customer.
"""
from __future__ import annotations

import re

SENIORITY = [  # first match wins, most senior first
    ("c_level", [r"\bchief\b", r"\bc[erotfmi]o\b", r"\bcro\b", r"\bcmo\b", r"\bcfo\b", r"\bceo\b", r"\bcto\b",
                 r"\bcoo\b", r"\bciso\b", r"\bfounder\b", r"\bco-founder\b", r"\bpresident\b", r"\bowner\b"]),
    ("vp", [r"\bvp\b", r"\bsvp\b", r"\bevp\b", r"vice president", r"\bhead of\b"]),
    ("director", [r"\bdirector\b", r"\bdir\.?\b"]),
    ("manager", [r"\bmanager\b", r"\bmgr\b", r"\blead\b", r"\bsupervisor\b"]),
    ("ic", [r".*"]),
]

FUNCTIONS = {  # first match wins: specific functions before broad ones
    "revops": [r"rev ?ops", r"revenue operations", r"sales operations", r"sales ops", r"gtm operations",
               r"go-to-market operations", r"enablement"],
    "customer_success": [r"customer success", r"\bcsm\b", r"account manag", r"support", r"customer experience"],
    "security": [r"security", r"\bciso\b", r"infosec", r"\bsoc\b"],
    "sales": [r"\bsales\b", r"\bsdr\b", r"\bbdr\b", r"account exec", r"\bae\b", r"business development",
              r"\brevenue\b", r"\bcro\b", r"partnerships?"],
    "marketing": [r"marketing", r"\bcmo\b", r"demand gen", r"growth", r"brand", r"content"],
    "engineering": [r"engineer", r"developer", r"\bcto\b", r"architect", r"devops", r"\bsre\b"],
    "it": [r"\bit\b", r"information technology", r"\bcio\b", r"systems admin"],
    "finance": [r"financ", r"\bcfo\b", r"controller", r"accounting", r"procurement"],
    "product": [r"product"],
    "executive": [r"\bceo\b", r"founder", r"president", r"general manager", r"\bcoo\b"],
}

SENIORITY_RANK = {"c_level": 5, "vp": 4, "director": 3, "manager": 2, "ic": 1}


def seniority(title: str | None) -> str:
    t = (title or "").lower()
    if not t.strip():
        return "unknown"
    for level, pats in SENIORITY:
        if any(re.search(p, t) for p in pats):
            return level
    return "ic"


def function(title: str | None, functions: dict[str, list[str]] | None = None) -> str:
    t = (title or "").lower()
    for fn, pats in (functions or FUNCTIONS).items():
        if any(re.search(p, t) for p in pats):
            return fn
    return "other"


def classify(title: str | None, functions: dict[str, list[str]] | None = None) -> dict:
    s = seniority(title)
    return {"seniority": s, "function": function(title, functions), "rank": SENIORITY_RANK.get(s, 0)}


def persona_match(title: str | None, buyer_functions: list[str], min_seniority: str = "manager") -> dict:
    """Does this title match the buyer persona? Returns match flag, score 0-100 and why."""
    c = classify(title)
    fn_ok = c["function"] in buyer_functions
    sen_ok = c["rank"] >= SENIORITY_RANK.get(min_seniority, 2)
    score = (60 if fn_ok else 0) + min(40, c["rank"] * 8)
    why = f"{c['seniority']} in {c['function']}" + ("" if fn_ok else " (not a buyer function)")
    return {"match": fn_ok and sen_ok, "score": score, "why": why, **c}
