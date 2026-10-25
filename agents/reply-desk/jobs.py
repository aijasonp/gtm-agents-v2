"""Reply Desk scheduled jobs (persistent edition)."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gtm_core.agents import load_module
from gtm_core.guardrails import StepCounter


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def _coerce(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x is not None)
    if isinstance(v, dict):
        return json.dumps(v, default=str)
    return str(v)


def read_rows(path: Path) -> list[dict]:
    """Rows from a CSV or JSON export. CSV is read as UTF-8 (with or without BOM), falling back to cp1252.
    Values that are not strings are coerced to strings; non-dict rows are dropped."""
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = data if isinstance(data, list) else (data.get("rows") or [data] if isinstance(data, dict) else [])
    else:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text, newline="")))
    return [{str(k).strip(): _coerce(v) for k, v in r.items() if k is not None} for r in rows if isinstance(r, dict)]


def quarantine(f: Path, err: Exception) -> str:
    """Move a file that cannot be read to failed/ so it never blocks the files behind it."""
    bad = f.parent.parent / "failed"
    bad.mkdir(parents=True, exist_ok=True)
    f.rename(bad / f.name)
    (bad / (f.name + ".error.txt")).write_text(f"{type(err).__name__}: {err}"[:2000])
    return f.name


def ingest_inbox(ctx, now: datetime | None = None) -> dict:
    """Load reply files (CSV/JSON from the sequencer or inbox export) dropped in the inbox, then archive them."""
    inbox = Path(ctx.manifest.config.get("reply_inbox", "data/replies/inbox"))
    if not inbox.exists():
        return {"files": 0, "replies": 0}
    done = inbox.parent / "processed"
    done.mkdir(parents=True, exist_ok=True)
    files = added = 0
    failed, bad_rows = [], 0
    eng = _eng(ctx)
    for f in sorted(list(inbox.glob("*.csv")) + list(inbox.glob("*.json"))):
        try:
            rows = read_rows(f)
        except Exception as e:  # unreadable file: quarantine it, keep going
            failed.append(quarantine(f, e))
            ctx.audit.log("reply_desk.bad_file", file=f.name, error=str(e)[:200])
            continue
        for r in rows:
            try:
                if eng.ingest_row(ctx, r, now):
                    added += 1
            except Exception as e:  # one bad row never blocks the file
                bad_rows += 1
                ctx.audit.log("reply_desk.bad_row", file=f.name, error=str(e)[:200])
        files += 1
        f.rename(done / f.name)
    return {"files": files, "replies": added, "failed_files": failed, "bad_rows": bad_rows}


def process_replies(ctx, now: datetime | None = None) -> dict:
    """Ingest new replies and handle each one. Opt-outs are honored locally before anything else runs."""
    inbox = ingest_inbox(ctx, now)
    eng = _eng(ctx)
    results = []
    with StepCounter(limit=max(ctx.settings.max_loop_steps, 500)) as steps:
        for r in eng.select(ctx, "status='new'", order="received_at"):
            steps.tick(r["id"])
            try:
                out = eng.handle(ctx, r["id"], now)
            except Exception as e:  # one bad reply never blocks the rest
                eng.update(ctx, r["id"], status="error", reason=f"{type(e).__name__}: {e}"[:300])
                continue
            if not out.get("skipped"):
                results.append(out)
    by = {}
    for r in results:
        by[r["class"]] = by.get(r["class"], 0) + 1
    return {"inbox": inbox, "handled": len(results), "classes": by,
            "approvals_queued": sum(len(r["approvals"]) for r in results)}


def reply_digest(ctx, now: datetime | None = None) -> dict:
    """End-of-day summary per owner: what came in, what needs a human, what was handled automatically."""
    now = now or datetime.now(timezone.utc)
    eng = _eng(ctx)
    since = (now - timedelta(days=1)).isoformat()
    per = {}
    for r in eng.select(ctx, "received_at>=? AND status IN ('handled','needs_review')", (since,)):
        per.setdefault(r.get("owner") or "Unassigned", []).append(r)
    for owner, rows in per.items():
        ctx.slack.post(eng.digest(owner, rows))
    return {"owners": len(per), "replies": sum(len(v) for v in per.values())}
