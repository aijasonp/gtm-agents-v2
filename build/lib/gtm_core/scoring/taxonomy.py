"""Signal taxonomy: categories, signal types, base weights, half-lives and stacking rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SignalType:
    type: str
    name: str
    category: str
    base_weight: float = 0.5
    half_life_days: float = 30.0
    default_strength: float = 1.0
    say_it: str = ""  # how a rep may reference it in copy ("" = do not mention directly)


@dataclass
class StackRule:
    id: str
    name: str
    min_categories: int = 2
    min_signals: int = 2
    multiplier: float = 1.15
    requires: list[str] = field(default_factory=list)  # category ids that must be present


@dataclass
class Taxonomy:
    version: str
    types: dict[str, SignalType]
    categories: dict[str, str]
    rules: list[StackRule]
    min_contribution: float = 0.15  # decayed contribution that counts toward stacking

    def get(self, signal_type: str) -> SignalType:
        if signal_type not in self.types:
            raise KeyError(f"unknown signal type '{signal_type}'")
        return self.types[signal_type]


def load_taxonomy(path: str | Path) -> Taxonomy:
    data = yaml.safe_load(Path(path).read_text())
    types: dict[str, SignalType] = {}
    cats: dict[str, str] = {}
    for c in data["categories"]:
        cats[c["id"]] = c["name"]
        for s in c["signals"]:
            if s["type"] in types:
                raise ValueError(f"duplicate signal type {s['type']}")
            types[s["type"]] = SignalType(
                type=s["type"], name=s["name"], category=c["id"],
                base_weight=float(s.get("base_weight", 0.5)),
                half_life_days=float(s.get("half_life_days", c.get("half_life_days", 30))),
                default_strength=float(s.get("default_strength", 1.0)),
                say_it=s.get("say_it", ""),
            )
    rules = [StackRule(**r) for r in data.get("stacking_rules", [])]
    for r in rules:
        for req in r.requires:
            if req not in cats:
                raise ValueError(f"rule {r.id} requires unknown category {req}")
    return Taxonomy(version=str(data.get("version", "1")), types=types, categories=cats, rules=rules,
                    min_contribution=float(data.get("min_contribution", 0.15)))
