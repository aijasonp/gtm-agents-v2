"""ICP fit, 0-100, from firmographics. Deterministic and explainable."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class IcpProfile:
    industries: list[str] = field(default_factory=list)          # target industries (case-insensitive substring)
    exclude_industries: list[str] = field(default_factory=list)  # hard zero
    employees: tuple[int, int] = (150, 1500)                     # sweet spot
    revenue: tuple[float, float] | None = None                   # USD, optional
    countries: list[str] = field(default_factory=list)           # empty = any
    tech_any: list[str] = field(default_factory=list)            # stack terms that raise fit
    weights: dict[str, float] = field(default_factory=lambda: {
        "industry": 0.35, "employees": 0.30, "country": 0.10, "revenue": 0.10, "tech": 0.15})

    @classmethod
    def from_yaml(cls, path: str | Path) -> "IcpProfile":
        d = yaml.safe_load(Path(path).read_text()) or {}
        p = cls()
        p.industries = [s.lower() for s in d.get("industries", [])]
        p.exclude_industries = [s.lower() for s in d.get("exclude_industries", [])]
        if "employees" in d:
            p.employees = (int(d["employees"][0]), int(d["employees"][1]))
        if d.get("revenue"):
            p.revenue = (float(d["revenue"][0]), float(d["revenue"][1]))
        p.countries = [s.upper() for s in d.get("countries", [])]
        p.tech_any = [s.lower() for s in d.get("tech_any", [])]
        p.weights.update(d.get("weights", {}))
        return p


def _range_fit(v: float | None, lo: float, hi: float) -> float | None:
    """1.0 inside [lo, hi]; falls off on a log scale outside (half credit at 2x away)."""
    if v is None or v <= 0:
        return None
    if lo <= v <= hi:
        return 1.0
    import math
    ratio = lo / v if v < lo else v / hi
    return max(0.0, 1 - math.log2(ratio) / 2)


def icp_fit(acct: dict, p: IcpProfile) -> tuple[float, list[str]]:
    ind = (acct.get("industry") or "").lower()
    reasons: list[str] = []
    if ind and any(x in ind for x in p.exclude_industries):
        return 0.0, [f"excluded industry: {acct.get('industry')}"]

    parts: dict[str, float | None] = {}
    if p.industries:
        parts["industry"] = (1.0 if any(x in ind for x in p.industries) else 0.2) if ind else None
    parts["employees"] = _range_fit(acct.get("employees"), *p.employees)
    if p.countries:
        c = (acct.get("country") or "").upper()
        parts["country"] = (1.0 if c in p.countries else 0.0) if c else None
    if p.revenue:
        parts["revenue"] = _range_fit(acct.get("revenue"), *p.revenue)
    if p.tech_any:
        tech = " ".join(acct.get("tech", []) if isinstance(acct.get("tech"), list) else [str(acct.get("tech", ""))]).lower()
        parts["tech"] = (1.0 if any(t in tech for t in p.tech_any) else 0.3) if tech.strip() else None

    known = {k: v for k, v in parts.items() if v is not None}
    if not known:
        return 50.0, ["no firmographics; neutral fit"]
    wsum = sum(p.weights.get(k, 0) for k in known)
    score = sum(p.weights.get(k, 0) * v for k, v in known.items()) / wsum if wsum else 0.5
    for k, v in sorted(known.items(), key=lambda kv: -kv[1]):
        reasons.append(f"{k} fit {v:.0%}")
    missing = [k for k, v in parts.items() if v is None]
    if missing:
        reasons.append("unknown: " + ", ".join(missing))
    return round(100 * score, 1), reasons
