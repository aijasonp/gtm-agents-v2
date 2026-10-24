"""Weekly learning: move each signal type's weight toward its observed lift on outcomes.

lift = P(positive outcome | account had signal) / P(positive outcome), smoothed.
target = base_weight x sqrt(lift); new = 0.7 x current + 0.3 x target, bounded to
[0.25x, 3x] of the taxonomy base weight. Types with fewer than `min_accounts`
accounts are left alone. All data stays in the customer's database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..store import Store
from .taxonomy import Taxonomy

POSITIVE = {"reply_positive", "meeting", "opportunity", "closed_won"}


def reweight(store: Store, tax: Taxonomy, window_days: int = 120, min_accounts: int = 5,
             alpha: float = 1.0, now: datetime | None = None) -> dict[str, dict]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=window_days)).isoformat()
    outcomes = store.query("SELECT account_id, outcome FROM outcomes WHERE observed_at >= ?", (since,))
    if not outcomes:
        return {}
    labeled: dict[str, bool] = {}
    for o in outcomes:
        labeled[o["account_id"]] = labeled.get(o["account_id"], False) or o["outcome"] in POSITIVE
    n_all = len(labeled)
    p_all = (sum(labeled.values()) + alpha) / (n_all + 2 * alpha)

    rows = store.query("SELECT DISTINCT account_id, signal_type FROM signals WHERE observed_at >= ?", (since,))
    with_sig: dict[str, set[str]] = {}
    for r in rows:
        if r["account_id"] in labeled:
            with_sig.setdefault(r["signal_type"], set()).add(r["account_id"])

    current = store.get_weights()
    changes: dict[str, dict] = {}
    for st, accts in with_sig.items():
        if st not in tax.types or len(accts) < min_accounts:
            continue
        pos = sum(1 for a in accts if labeled[a])
        p_sig = (pos + alpha) / (len(accts) + 2 * alpha)
        lift = p_sig / p_all
        base = tax.types[st].base_weight
        cur = current.get(f"signal:{st}", base)
        target = base * lift ** 0.5
        new = min(base * 3, max(base * 0.25, 0.7 * cur + 0.3 * target))
        store.set_weight(f"signal:{st}", round(new, 4))
        changes[st] = {"accounts": len(accts), "positive": pos, "lift": round(lift, 3),
                       "from": round(cur, 4), "to": round(new, 4)}
    return changes
