"""CSV / JSON importers for accounts, signals and outcomes (the zero-integration path)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .scoring import signal_id
from .scoring.taxonomy import load_taxonomy


def _rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else data.get("rows", [])
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _num(v, cast=float):
    try:
        return cast(float(v)) if v not in (None, "") else None
    except ValueError:
        return None


def import_accounts(ctx, path: Path) -> dict:
    n = 0
    for r in _rows(path):
        if not r.get("name"):
            continue
        acct = dict(r)
        acct["id"] = r.get("id") or r.get("domain") or r["name"].lower().replace(" ", "-")
        acct["employees"] = _num(r.get("employees"), int)
        acct["revenue"] = _num(r.get("revenue"))
        if isinstance(acct.get("tech"), str):
            acct["tech"] = [t.strip() for t in acct["tech"].split(";") if t.strip()]
        ctx.store.upsert_account(acct)
        n += 1
    ctx.audit.log("import.accounts", count=n, file=path.name)
    return {"accounts": n}


def import_signals(ctx, path: Path) -> dict:
    tax = load_taxonomy(ctx.manifest.path(ctx.manifest.config.get("taxonomy", "skill/references/signal-taxonomy.yaml")))
    added = dupes = unknown = 0
    for r in _rows(path):
        st = r.get("signal_type")
        if st not in tax.types:
            unknown += 1
            continue
        ref = r.get("url") or r.get("title") or ""
        sig = {"id": signal_id(r["account_id"], st, ref, r["observed_at"]), "account_id": r["account_id"],
               "signal_type": st, "category": tax.types[st].category, "source": r.get("source", "import"),
               "url": r.get("url"), "observed_at": r["observed_at"], "strength": _num(r.get("strength")),
               "payload": {"title": r.get("title", "")}}
        if ctx.store.add_signal(sig):
            added += 1
        else:
            dupes += 1
    ctx.audit.log("import.signals", added=added, duplicates=dupes, unknown_types=unknown, file=path.name)
    return {"added": added, "duplicates": dupes, "unknown_types": unknown}


def import_outcomes(ctx, path: Path) -> dict:
    n = 0
    for r in _rows(path):
        ctx.store.add_outcome(r["account_id"], r["outcome"], _num(r.get("value")) or 1.0,
                              r.get("source", "import"), r.get("observed_at"))
        n += 1
    return {"outcomes": n}
