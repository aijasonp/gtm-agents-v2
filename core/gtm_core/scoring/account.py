"""Combine ICP fit and signal heat into one account priority score and tier."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .icp import IcpProfile, icp_fit
from .signals import SignalScore, score_signals
from .taxonomy import Taxonomy

TIERS = [("A", 75), ("B", 55), ("C", 35)]


def tier_for(score: float, icp: float, icp_floor: float) -> str:
    if icp < icp_floor:
        return "X"  # out of ICP: never surfaced, whatever the signals
    for t, cut in TIERS:
        if score >= cut:
            return t
    return "D"


@dataclass
class AccountScore:
    account_id: str
    name: str
    score: float
    icp: float
    signal: float
    tier: str
    reasons: list[str] = field(default_factory=list)
    signals: SignalScore | None = None
    rule_icp: float | None = None
    judged: dict | None = None

    def as_dict(self) -> dict:
        return {
            "account_id": self.account_id, "name": self.name, "score": self.score, "icp": self.icp,
            "signal": self.signal, "tier": self.tier, "reasons": self.reasons,
            "top_signals": [
                {"type": c.signal_type, "name": c.name, "category": c.category, "observed_at": c.observed_at,
                 "value": round(c.value, 3), "say_it": c.say_it, "url": c.url}
                for c in (self.signals.top if self.signals else [])
            ],
            "stack_rule": self.signals.rule if self.signals else None,
            "rule_icp": self.rule_icp, "judged": self.judged,
        }


def score_account(acct: dict, signals: list[dict], tax: Taxonomy, icp: IcpProfile,
                  weights: dict[str, float] | None = None, icp_weight: float = 0.4,
                  icp_floor: float = 30.0, now: datetime | None = None, judged: dict | None = None,
                  signal_multiplier: float = 1.0) -> AccountScore:
    """judged: {score 0-100, coverage 0-1, blend 0-1, reasons} from a decision model, or None.
    An excluded industry stays a hard zero whatever the judgment says."""
    rule_fit, fit_reasons = icp_fit(acct, icp)
    fit = rule_fit
    excluded = bool(fit_reasons) and fit_reasons[0].startswith("excluded industry")
    if judged and judged.get("score") is not None and not excluded:
        b = max(0.0, min(1.0, float(judged.get("blend", 0.5)) * float(judged.get("coverage", 1.0))))
        fit = round((1 - b) * rule_fit + b * float(judged["score"]), 1)
    ss = score_signals(signals, tax, weights, now)
    sig = round(min(100.0, ss.score * signal_multiplier), 1)
    total = round(icp_weight * fit + (1 - icp_weight) * sig, 1)
    reasons = [f"ICP {fit:.0f}: " + "; ".join(fit_reasons[:3])]
    if judged and judged.get("score") is not None and not excluded:
        reasons.append(f"Judged fit {judged['score']:.0f} (rule {rule_fit:.0f}, coverage {float(judged.get('coverage', 1)):.0%}): "
                       + "; ".join((judged.get("reasons") or [])[:3]))
    if signal_multiplier != 1.0:
        reasons.append(f"Signal relevance x{signal_multiplier:.2f}")
    if ss.top:
        reasons.append("Signals: " + ", ".join(f"{c.name} ({c.observed_at[:10]})" for c in ss.top[:3]))
    if ss.rule:
        reasons.append(f"Stacked across {len(ss.categories)} categories (x{ss.multiplier})")
    return AccountScore(acct["id"], acct.get("name", acct["id"]), total, fit, sig,
                        tier_for(total, fit, icp_floor), reasons, ss, rule_icp=rule_fit, judged=judged)
