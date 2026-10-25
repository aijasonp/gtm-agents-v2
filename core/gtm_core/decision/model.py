"""Typed decision models: a state (facts about an account) plus typed questions.

A question has a kind that fixes what a valid answer looks like:

  bool    true or false; scores 1.0 or 0.0
  choice  one of `options`; each option carries its own value from 0 to 1
  score   an integer 1 to 5; scores (n - 1) / 4

Answers that do not match the kind are rejected, never coerced. A question with weight 0
is still asked and returned (for example `primary_pain`, which ICP Outbound uses to pick
the value prop) but does not move the score.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KINDS = {"bool", "choice", "score"}


@dataclass
class Question:
    id: str
    kind: str
    ask: str
    weight: float = 0.0
    options: dict[str, float] = field(default_factory=dict)  # choice only: option -> value 0..1
    rules: dict = field(default_factory=dict)                 # offline evidence rules (see backends.RulesBackend)

    def validate(self, value: Any) -> Any:
        """Return the value when it is a valid answer for this kind, else raise ValueError. None means unknown."""
        if value is None:
            return None
        if self.kind == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no"):
                return value.strip().lower() in ("true", "yes")
            raise ValueError(f"{self.id}: expected true or false, got {value!r}")
        if self.kind == "choice":
            v = str(value).strip()
            if v in self.options:
                return v
            raise ValueError(f"{self.id}: {v!r} is not one of {sorted(self.options)}")
        if self.kind == "score":
            if isinstance(value, bool):
                raise ValueError(f"{self.id}: expected 1 to 5, got {value!r}")
            try:
                n = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{self.id}: expected 1 to 5, got {value!r}") from None
            if n != int(n) or not 1 <= n <= 5:
                raise ValueError(f"{self.id}: expected an integer 1 to 5, got {value!r}")
            return int(n)
        raise ValueError(f"{self.id}: unknown kind {self.kind}")

    def numeric(self, value: Any) -> float | None:
        if value is None:
            return None
        if self.kind == "bool":
            return 1.0 if value else 0.0
        if self.kind == "choice":
            return float(self.options.get(value, 0.0))
        return (int(value) - 1) / 4

    def spec(self) -> dict:
        d = {"id": self.id, "kind": self.kind, "ask": self.ask}
        if self.kind == "choice":
            d["options"] = sorted(self.options)
        if self.kind == "score":
            d["scale"] = "integer 1 (lowest) to 5 (highest)"
        return d


@dataclass
class Answer:
    value: Any
    evidence: str = ""
    source: str = ""        # rules, model, remote
    confidence: float | None = None

    def as_dict(self) -> dict:
        return {"value": self.value, "evidence": self.evidence, "source": self.source, "confidence": self.confidence}


@dataclass
class Verdict:
    model: str
    answers: dict[str, Answer]
    score: float | None      # 0..100 over answered, weighted questions; None when nothing scored was answered
    coverage: float          # share of total question weight that got an answer
    backend: str
    reasons: list[str] = field(default_factory=list)
    cached: bool = False
    shadow: dict | None = None

    def value(self, qid: str, default: Any = None) -> Any:
        a = self.answers.get(qid)
        return a.value if a and a.value is not None else default

    def as_dict(self) -> dict:
        return {"model": self.model, "score": self.score, "coverage": self.coverage, "backend": self.backend,
                "cached": self.cached, "reasons": self.reasons,
                "answers": {k: a.as_dict() for k, a in self.answers.items()}, "shadow": self.shadow}


@dataclass
class DecisionModel:
    name: str
    questions: list[Question]
    version: str = "1"

    @classmethod
    def from_dict(cls, name: str, d: dict, value_props: list[dict] | None = None) -> "DecisionModel":
        qs = []
        for q in d.get("questions", []):
            kind = q.get("kind", "bool")
            if kind not in KINDS:
                raise ValueError(f"question {q.get('id')}: kind must be one of {sorted(KINDS)}")
            opts = q.get("options") or {}
            if q.get("options_from") == "value_props":
                opts = {vp["id"]: 0.0 for vp in (value_props or []) if vp.get("id")}
            if isinstance(opts, list):
                opts = {str(o): 0.0 for o in opts}
            if kind == "choice" and not opts:
                raise ValueError(f"question {q.get('id')}: a choice question needs options")
            qs.append(Question(id=q["id"], kind=kind, ask=q["ask"], weight=float(q.get("weight", 0)),
                               options={str(k): float(v) for k, v in opts.items()}, rules=q.get("rules") or {}))
        ids = [q.id for q in qs]
        if len(ids) != len(set(ids)):
            raise ValueError(f"decision model {name}: duplicate question ids")
        return cls(name=name, questions=qs, version=str(d.get("version", "1")))

    @property
    def by_id(self) -> dict[str, Question]:
        return {q.id: q for q in self.questions}

    def fingerprint(self) -> str:
        """Changes whenever a question, option or rule changes, so cached verdicts expire with the model."""
        raw = json.dumps([[q.id, q.kind, q.ask, q.options, q.rules] for q in self.questions] + [self.version],
                         sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def score(self, answers: dict[str, Answer], multipliers: dict[str, float] | None = None
              ) -> tuple[float | None, float, list[str]]:
        """Weighted score 0..100 over answered questions, coverage 0..1, and reasons."""
        multipliers = multipliers or {}
        total = sum(q.weight * multipliers.get(q.id, 1.0) for q in self.questions if q.weight > 0)
        num = den = 0.0
        reasons = []
        for q in self.questions:
            if q.weight <= 0:
                continue
            a = answers.get(q.id)
            v = q.numeric(a.value) if a else None
            if v is None:
                continue
            w = q.weight * multipliers.get(q.id, 1.0)
            num += w * v
            den += w
            reasons.append(f"{q.id}={a.value}" + (f" ({a.evidence[:60]})" if a.evidence else ""))
        if den == 0:
            return None, 0.0, ["no judged answers"]
        return round(100 * num / den, 1), round(den / total, 3) if total else 0.0, reasons


def load_judgment(icp_yaml: str | Path) -> dict:
    """The `judgment` section of config/icp.yaml (empty dict when absent: judgment off)."""
    p = Path(icp_yaml)
    if not p.exists():
        return {}
    return (yaml.safe_load(p.read_text()) or {}).get("judgment") or {}
