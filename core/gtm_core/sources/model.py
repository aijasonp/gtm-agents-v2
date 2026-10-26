"""One sourced signal, before it becomes a row in the signals table."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Finding:
    account_id: str
    source: str            # filing | initiative | hiring | exec_change | funding
    signal_type: str       # a type in the Signal Scout taxonomy
    detail: str            # the exact dated, company-specific fact or sentence
    url: str
    observed_at: str       # ISO date of the filing, announcement or posting
    confidence: str = "Medium"   # High | Medium
    topics: list[str] = field(default_factory=list)
    amount: str | None = None    # stated dollar figure, initiatives and funding only
    meta: dict = field(default_factory=dict)  # filing form, section, role, person, provider

    @property
    def strength(self) -> float:
        return 1.0 if self.confidence == "High" else 0.7

    def as_dict(self) -> dict:
        d = asdict(self)
        d["strength"] = self.strength
        return d
