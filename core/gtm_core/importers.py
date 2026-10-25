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
    added = dupes = unknown = invalid = 0
    for r in _rows(path):
        st = r.get("signal_type")
        if st not in tax.types:
            unknown += 1
            continue
        if not r.get("account_id") or not r.get("observed_at"):
            invalid += 1
            continue
        ref = r.get("url") or r.get("title") or ""
        sig = {"id": signal_id(r["account_id"], st, ref, r["observed_at"]), "account_id": r["account_id"],
               "signal_type": st, "category": tax.types[st].category, "source": r.get("source", "import"),
               "url": r.get("url"), "observed_at": r["observed_at"], "strength": _num(r.get("strength")),
               "payload": {"title": r.get("title", "")}}
        try:
            ok = ctx.store.add_signal(sig)
        except ValueError:  # unreadable date: skip this row, keep the rest
            invalid += 1
            continue
        if ok:
            added += 1
        else:
            dupes += 1
    ctx.audit.log("import.signals", added=added, duplicates=dupes, unknown_types=unknown, invalid=invalid, file=path.name)
    return {"added": added, "duplicates": dupes, "unknown_types": unknown, "invalid": invalid}


def import_outcomes(ctx, path: Path) -> dict:
    n = 0
    for r in _rows(path):
        ctx.store.add_outcome(r["account_id"], r["outcome"], _num(r.get("value")) or 1.0,
                              r.get("source", "import"), r.get("observed_at"))
        n += 1
    return {"outcomes": n}


# ---------- generic records: contacts, leads, deals, tasks, meetings ----------
def _clean(r: dict) -> dict:
    return {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k and v not in (None, "")}


def import_contacts(ctx, path: Path) -> dict:
    from . import personas
    n = 0
    for r in map(_clean, _rows(path)):
        if not (r.get("email") or r.get("id")):
            continue
        r["id"] = r.get("id") or r["email"].lower()
        if not r.get("account_id") and r.get("email") and "@" in r["email"]:
            acct = ctx.store.account_by_domain(r["email"].split("@", 1)[1])
            r["account_id"] = acct["id"] if acct else None
        cls = personas.classify(r.get("title"))
        r.setdefault("seniority", cls["seniority"])
        r.setdefault("function", cls["function"])
        ctx.store.upsert("contacts", r)
        n += 1
    ctx.audit.log("import.contacts", count=n, file=path.name)
    return {"contacts": n}


def lead_id(r: dict) -> str:
    import hashlib
    key = f"{(r.get('email') or '').lower()}|{r.get('source', '')}|{(r.get('received_at') or '')[:10]}"
    return "lead-" + hashlib.sha1(key.encode()).hexdigest()[:12]


def import_leads(ctx, path: Path) -> dict:
    added = dupes = 0
    for r in map(_clean, _rows(path)):
        if not r.get("email"):
            continue
        r["email"] = r["email"].lower()
        r["id"] = r.get("id") or lead_id(r)
        if ctx.store.get("leads", r["id"]):
            dupes += 1
            continue
        r.setdefault("status", "new")
        if not r.get("domain"):
            r["domain"] = r["email"].split("@", 1)[1]
        ctx.store.upsert("leads", r)
        added += 1
    ctx.audit.log("import.leads", added=added, duplicates=dupes, file=path.name)
    return {"leads": added, "duplicates": dupes}


def import_deals(ctx, path: Path) -> dict:
    from .sync import upsert_deal
    n = 0
    for r in map(_clean, _rows(path)):
        if not (r.get("id") or r.get("crm_id")):
            continue
        r["id"] = r.get("id") or f"deal-{r['crm_id']}"
        if "amount" in r:
            r["amount"] = _num(r["amount"])
        md = {k.split(".", 1)[1]: r.pop(k) for k in list(r) if k.startswith("meddpicc.")}
        if md:
            r["meddpicc"] = {**(r.get("meddpicc") or {}), **md}
        upsert_deal(ctx, r)
        n += 1
    ctx.audit.log("import.deals", count=n, file=path.name)
    return {"deals": n}


def import_tasks(ctx, path: Path) -> dict:
    n = 0
    for r in map(_clean, _rows(path)):
        if not r.get("title"):
            continue
        import hashlib
        r["id"] = r.get("id") or "task-" + hashlib.sha1(f"{r['title']}|{r.get('deal_id')}|{r.get('due_at')}".encode()).hexdigest()[:12]
        r.setdefault("status", "open")
        ctx.store.upsert("tasks", r)
        n += 1
    return {"tasks": n}


def import_meetings(ctx, path: Path) -> dict:
    """A JSON/CSV list of meetings (transcript inline or `transcript_file`), or a folder of
    transcript files (.txt/.vtt/.srt/.json) with optional same-name .meta.json files."""
    n = 0
    items: list[dict] = []
    if path.is_dir():
        for f in sorted(path.iterdir()):
            if f.suffix.lower() not in (".txt", ".vtt", ".srt", ".json") or f.name.endswith(".meta.json"):
                continue
            meta_f = f.with_name(f.stem + ".meta.json")
            meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
            items.append({"id": meta.get("id") or f.stem, **meta, "transcript": f.read_text(errors="ignore"),
                          "source": meta.get("source", "file")})
    else:
        for r in map(_clean, _rows(path)):
            tf = r.pop("transcript_file", None)
            if tf:
                p = (path.parent / tf) if not Path(tf).is_absolute() else Path(tf)
                r["transcript"] = p.read_text(errors="ignore") if p.exists() else ""
            items.append(r)
    for m in items:
        if not m.get("id"):
            continue
        if isinstance(m.get("attendees"), str):
            m["attendees"] = [a.strip() for a in m["attendees"].split(";") if a.strip()]
        ctx.store.upsert("meetings", m)
        n += 1
    ctx.audit.log("import.meetings", count=n, file=path.name)
    return {"meetings": n}


RECORD_IMPORTERS = {"accounts": import_accounts, "signals": import_signals, "outcomes": import_outcomes,
                    "contacts": import_contacts, "leads": import_leads, "deals": import_deals, "tasks": import_tasks,
                    "meetings": import_meetings}
