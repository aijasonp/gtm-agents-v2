"""Weekly learning for judged ICP questions, from real email engagement.

For each scored question, accounts that were emailed are split by their answer
(numeric value >= 0.5 vs below). lift = smoothed engagement of the high group divided by
the low group, where engagement = 0.4 x human open + 0.6 x reply per thread.
target = sqrt(lift); new multiplier = 0.7 x current + 0.3 x target, bounded to [0.5, 2.0].
Questions with fewer than `min_per_side` emailed accounts on either side are left alone.

The report also shows open and reply rates by judged ICP band, which is the check that
better fit is producing better opens.
"""
from __future__ import annotations

import json
from datetime import datetime

from .. import engagement
from .model import DecisionModel

BANDS = [("80-100", 80), ("60-79", 60), ("40-59", 40), ("0-39", 0)]


def _band(score: float | None) -> str:
    if score is None:
        return "unjudged"
    for name, lo in BANDS:
        if score >= lo:
            return name
    return "0-39"


def learn(store, model: DecisionModel, window_days: int = 120, min_per_side: int = 20, smoothing: float = 0.02,
          weights: dict | None = None, now: datetime | None = None) -> dict:
    since = engagement.since_days(window_days, now)
    threads = [t for t in engagement.threads(store, since) if t.get("account_id")]
    latest: dict[str, dict] = {}
    for r in store.query("SELECT subject, answers, score FROM decisions WHERE model=? ORDER BY id", (model.name,)):
        latest[r["subject"]] = {"answers": json.loads(r["answers"] or "{}"), "score": r["score"]}
    bands: dict[str, list] = {}
    for t in threads:
        bands.setdefault(_band((latest.get(t["account_id"]) or {}).get("score")), []).append(t)
    report = {"threads": len(threads), "by_icp_band": {k: engagement.rates(v) for k, v in sorted(bands.items())},
              "questions": {}}
    pre = f"dq:{model.name}:"
    current = store.get_weights()
    for q in model.questions:
        if q.weight <= 0:
            continue
        hi, lo = [], []
        for t in threads:
            a = (latest.get(t["account_id"]) or {}).get("answers", {}).get(q.id)
            v = q.numeric(a.get("value")) if a and a.get("value") is not None else None
            if v is None:
                continue
            (hi if v >= 0.5 else lo).append(engagement.outcome(t, weights))
        entry = {"high_n": len(hi), "low_n": len(lo)}
        if len(hi) < min_per_side or len(lo) < min_per_side:
            entry["skipped"] = f"needs {min_per_side} emailed accounts on each side"
            report["questions"][q.id] = entry
            continue
        mh, ml = sum(hi) / len(hi), sum(lo) / len(lo)
        lift = (mh + smoothing) / (ml + smoothing)
        cur = current.get(pre + q.id, 1.0)
        new = min(2.0, max(0.5, 0.7 * cur + 0.3 * min(2.0, max(0.5, lift ** 0.5))))
        store.set_weight(pre + q.id, round(new, 4))
        entry.update({"high_engagement": round(mh, 3), "low_engagement": round(ml, 3), "lift": round(lift, 3),
                      "from": round(cur, 4), "to": round(new, 4)})
        report["questions"][q.id] = entry
    return report
