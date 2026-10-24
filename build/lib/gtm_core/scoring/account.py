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
        }


def score_account(acct: dict, signals: list[dict], tax: Taxonomy, icp: IcpProfile,
                  weights: dict[str, float] | None = None, icp_weight: float = 0.4,
                  icp_floor: float = 30.0, now: datetime | None = None) -> AccountScore:
    fit, fit_reasons = icp_fit(acct, icp)
    ss = score_signals(signals, tax, weights, now)
    total = round(icp_weight * fit + (1 - icp_weight) * ss.score, 1)
    reasons = [f"ICP {fit:.0f}: " + "; ".join(fit_reasons[:3])]
    if ss.top:
        reasons.append("Signals: " + ", ".join(f"{c.name} ({c.observed_at[:10]})" for c in ss.top[:3]))
    if ss.rule:
        reasons.append(f"Stacked across {len(ss.categories)} categories (x{ss.multiplier})")
    return AccountScore(acct["id"], acct.get("name", acct["id"]), total, fit, ss.score,
                        tier_for(total, fit, icp_floor), reasons, ss)
