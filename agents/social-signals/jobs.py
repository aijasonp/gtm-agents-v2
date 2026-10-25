"""Social Signals scheduled jobs (persistent edition)."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
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


def ingest_engagement(ctx, now: datetime | None = None) -> dict:
    """Load engagement exports from the inbox, resolve and score them, alert owners, archive the files."""
    eng = _eng(ctx)
    inbox = Path(ctx.manifest.config.get("engagement_inbox", "data/engagement/inbox"))
    totals: dict = {"files": 0}
    results = []
    if inbox.exists():
        done = inbox.parent / "processed"
        done.mkdir(parents=True, exist_ok=True)
        with StepCounter(limit=max(ctx.settings.max_loop_steps, 100)) as steps:
            for f in sorted(list(inbox.glob("*.csv")) + list(inbox.glob("*.json"))):
                steps.tick(f.name)
                try:
                    rows = read_rows(f)
                except Exception as e:  # unreadable file: quarantine it, keep going
                    totals.setdefault("failed_files", []).append(quarantine(f, e))
                    ctx.audit.log("social_signals.bad_file", file=f.name, error=str(e)[:200])
                    continue
                try:
                    out = eng.ingest(ctx, rows, now)
                except Exception:  # a bad row somewhere: process row by row so the good ones land
                    out = {"stats": {"bad_rows": 0}, "results": []}
                    for row in rows:
                        try:
                            one = eng.ingest(ctx, [row], now)
                        except Exception as e:
                            out["stats"]["bad_rows"] += 1
                            ctx.audit.log("social_signals.bad_row", file=f.name, error=str(e)[:200])
                            continue
                        for k, v in one["stats"].items():
                            out["stats"][k] = out["stats"].get(k, 0) + v
                        out["results"] += one["results"]
                totals["files"] += 1
                for k, v in out["stats"].items():
                    totals[k] = totals.get(k, 0) + v
                results += out["results"]
                f.rename(done / f.name)
    for msg in eng.format_alerts(ctx, results):
        ctx.slack.post(msg)
    return totals


def weekly_creator_report(ctx, now: datetime | None = None) -> dict:
    """Which creators and posts drove engagement from target accounts this week."""
    eng = _eng(ctx)
    rep = eng.creator_report(ctx, 7, now)
    ctx.slack.post(eng.format_creator_report(rep))
    return {"creators": len(rep["creators"]), "top_posts": len(rep["top_posts"])}
