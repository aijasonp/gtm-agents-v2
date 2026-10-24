"""Copy QA gate: deterministic checks every outbound draft must pass before it reaches a rep.

Checks: banned phrases, em dashes, sentence length, readability, length budget,
exclamation marks, unverifiable claims, and a single clear ask. Each check
returns points; 32 of 40 passes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BANNED = [
    "delve", "leverage", "utilize", "robust", "seamless", "seamlessly", "synergy", "game-changer",
    "game changer", "cutting-edge", "best-in-class", "world-class", "revolutionize", "unlock",
    "empower", "elevate", "supercharge", "streamline", "holistic", "tapestry", "testament",
    "in today's fast-paced", "in today's digital", "ever-evolving", "navigate the complexities",
    "i hope this email finds you well", "i hope this finds you well", "just checking in",
    "just following up", "touching base", "circle back", "quick question", "reach out",
    "i wanted to", "at the end of the day", "it's worth noting", "in conclusion",
    "look no further", "pain points", "thought leader", "move the needle", "low-hanging fruit",
]

CLAIM_PATTERNS = [r"\b\d{2,3}%\s+(?:of|more|less|faster|increase|reduction)", r"\b\d+x\b", r"guarantee"]


@dataclass
class GateResult:
    score: int
    passed: bool
    checks: dict[str, dict] = field(default_factory=dict)

    def failures(self) -> list[str]:
        return [f"{k}: {v['note']}" for k, v in self.checks.items() if v["points"] < v["max"]]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip())
    return [p for p in parts if re.search(r"[A-Za-z]", p)]


def _syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups) - (1 if w.endswith("e") and len(groups) > 1 else 0)
    return max(1, n)


def flesch(text: str) -> float:
    sents = _sentences(text)
    words = re.findall(r"[A-Za-z']+", text)
    if not sents or not words:
        return 100.0
    syl = sum(_syllables(w) for w in words)
    return 206.835 - 1.015 * (len(words) / len(sents)) - 84.6 * (syl / len(words))


def load_banned(path: str | Path | None) -> list[str]:
    if path and Path(path).exists():
        extra = [l.strip().lower() for l in Path(path).read_text().splitlines() if l.strip() and not l.startswith("#")]
        return sorted(set(DEFAULT_BANNED + extra))
    return DEFAULT_BANNED


def check(text: str, banned: list[str] | None = None, max_words: int = 120, pass_mark: int = 32) -> GateResult:
    banned = banned or DEFAULT_BANNED
    low = text.lower()
    words = re.findall(r"[A-Za-z']+", text)
    sents = _sentences(text)
    c: dict[str, dict] = {}

    hits = [b for b in banned if re.search(r"(?<![a-z])" + re.escape(b) + r"(?![a-z])", low)]
    c["banned_phrases"] = {"max": 10, "points": max(0, 10 - 4 * len(hits)),
                           "note": ", ".join(hits) if hits else "none"}

    dashes = text.count("—") + text.count(" -- ")
    c["em_dashes"] = {"max": 6, "points": 0 if dashes else 6, "note": f"{dashes} found"}

    longest = max((len(re.findall(r"[A-Za-z']+", s)) for s in sents), default=0)
    c["sentence_length"] = {"max": 6, "points": 6 if longest <= 25 else (3 if longest <= 35 else 0),
                            "note": f"longest sentence {longest} words"}

    fk = flesch(text)
    c["readability"] = {"max": 6, "points": 6 if fk >= 60 else (3 if fk >= 45 else 0), "note": f"Flesch {fk:.0f}"}

    n = len(words)
    c["length"] = {"max": 4, "points": 4 if n <= max_words else (2 if n <= max_words * 1.5 else 0),
                   "note": f"{n} words (budget {max_words})"}

    ex = text.count("!")
    c["exclamations"] = {"max": 2, "points": 2 if ex == 0 else 0, "note": f"{ex} found"}

    claims = [m.group(0) for p in CLAIM_PATTERNS for m in re.finditer(p, low)]
    c["unverified_claims"] = {"max": 3, "points": 3 if not claims else 0,
                              "note": ("needs a source: " + ", ".join(claims)) if claims else "none"}

    asks = len(re.findall(r"\?", text))
    c["single_ask"] = {"max": 3, "points": 3 if asks == 1 else (1 if asks == 2 else 0), "note": f"{asks} questions"}

    total = sum(v["points"] for v in c.values())
    return GateResult(total, total >= pass_mark, c)
