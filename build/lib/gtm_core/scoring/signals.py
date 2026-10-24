"""Deterministic signal math: dedup ids, exponential decay, diminishing returns, stacking."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .taxonomy import Taxonomy


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"^https?://(www\.)?", "", s)
    s = re.sub(r"[?#].*$", "", s)
    return re.sub(r"\s+", " ", s).rstrip("/")


def signal_id(account_id: str, signal_type: str, ref: str, observed_at: str) -> str:
    """Stable id: same account + type + source ref + day = same signal (dedup before any model call)."""
    day = (observed_at or "")[:10]
    raw = f"{account_id}|{signal_type}|{_norm(ref)}|{day}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def decay(observed_at: str, half_life_days: float, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    age = max(0.0, (now - _parse(observed_at)).total_seconds() / 86400)
    return 0.5 ** (age / half_life_days) if half_life_days > 0 else 1.0


@dataclass
class Contribution:
    signal_type: str
    name: str
    category: str
    observed_at: str
    value: float
    say_it: str = ""
    url: str | None = None


@dataclass
class SignalScore:
    score: float                      # 0-100
    raw: float
    multiplier: float
    categories: list[str]
    rule: str | None
    top: list[Contribution] = field(default_factory=list)


def score_signals(signals: list[dict], tax: Taxonomy, weights: dict[str, float] | None = None,
                  now: datetime | None = None, k: float = 1.5) -> SignalScore:
    """signals: dicts with signal_type, observed_at, optional strength/url.

    contribution = weight x strength x decay; repeats of one type get 1, 1/2, 1/4... credit;
    raw sums are squashed to 0-100 with 100*(1-exp(-raw/k)); cross-category stacking multiplies.
    """
    weights = weights or {}
    by_type: dict[str, list[Contribution]] = {}
    for s in signals:
        st = tax.types.get(s["signal_type"])
        if st is None:
            continue
        w = weights.get(f"signal:{st.type}", st.base_weight)
        strength = s.get("strength")
        strength = st.default_strength if strength is None else float(strength)
        v = w * strength * decay(s["observed_at"], st.half_life_days, now)
        by_type.setdefault(st.type, []).append(
            Contribution(st.type, st.name, st.category, s["observed_at"], v, st.say_it, s.get("url")))

    contribs: list[Contribution] = []
    raw = 0.0
    for items in by_type.values():
        items.sort(key=lambda c: c.value, reverse=True)
        for i, c in enumerate(items):
            c.value = c.value * (0.5 ** i)
            raw += c.value
            contribs.append(c)

    strong = [c for c in contribs if c.value >= tax.min_contribution]
    cats = sorted({c.category for c in strong})
    mult, rule = 1.0, None
    for r in tax.rules:
        if len(cats) >= r.min_categories and len(strong) >= r.min_signals and all(q in cats for q in r.requires):
            if r.multiplier > mult:
                mult, rule = r.multiplier, r.id

    base = 100 * (1 - math.exp(-raw / k)) if raw > 0 else 0.0
    score = min(100.0, base * mult)
    contribs.sort(key=lambda c: c.value, reverse=True)
    return SignalScore(round(score, 1), round(raw, 4), mult, cats, rule, contribs[:5])
