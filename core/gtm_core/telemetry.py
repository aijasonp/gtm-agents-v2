"""Traces and feedback: what every model call cost, what every draft was built from, and what the AE did with it.

Everything is written to the customer's own database first. Nothing leaves it unless Langfuse is configured.

  spans     one row per model call (generation) and per finished draft (draft). A draft span keeps the facts
            it was written from and the text that came out, so an approved draft becomes a training example.
  feedback  one row per AE decision on a drafted send: ae_decision (1 approved, 0 rejected) and
            ae_edit_similarity (1.0 = sent as written, lower = the AE rewrote it), with the before and after.

Prompts and model outputs are not stored on generation spans unless GTM_TRACE_CONTENT=1. Draft spans keep their
facts and text locally (they are the training examples) but send them to Langfuse only with GTM_TRACE_CONTENT=1.

Langfuse (optional): set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST (default
https://cloud.langfuse.com, or your self-hosted URL). `export_langfuse()` sends traces, generations and
scores through the public ingestion API and marks what it sent; Ops Monitor runs it every 5 minutes.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from .store import Store, now_iso

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS spans (
      id TEXT PRIMARY KEY, trace_id TEXT, agent TEXT, kind TEXT, name TEXT, model TEXT, model_class TEXT,
      input_tokens INTEGER, output_tokens INTEGER, usd DOUBLE PRECISION, latency_ms INTEGER, status TEXT,
      body_hash TEXT, facts TEXT, output TEXT, meta TEXT, started_at TEXT, ended_at TEXT, exported INTEGER)""",
    "CREATE INDEX IF NOT EXISTS ix_spans_hash ON spans(body_hash)",
    "CREATE INDEX IF NOT EXISTS ix_spans_export ON spans(exported)",
    """CREATE TABLE IF NOT EXISTS feedback (
      id TEXT PRIMARY KEY, trace_id TEXT, span_id TEXT, draft_id INTEGER, approval_id INTEGER, agent TEXT, kind TEXT,
      name TEXT, value DOUBLE PRECISION, comment TEXT, before TEXT, after TEXT, decided_by TEXT, created_at TEXT,
      exported INTEGER)""",
    "CREATE INDEX IF NOT EXISTS ix_feedback_export ON feedback(exported)",
]

TRACE: ContextVar[str | None] = ContextVar("gtm_trace", default=None)


def ensure(store: Store) -> None:
    if not getattr(store, "_telemetry_schema", False):
        for s in SCHEMA:
            store.execute(s.replace("DOUBLE PRECISION", "REAL") if store.kind == "sqlite" else s)
        store._telemetry_schema = True


def bind(trace_id: str) -> None:
    """Every span recorded in this context belongs to this trace (one job run, one tool call)."""
    TRACE.set(trace_id)


def current() -> str:
    return TRACE.get() or "untraced"


def body_hash(body: str) -> str:
    return hashlib.sha256(" ".join((body or "").split()).encode()).hexdigest()[:24]


def _content() -> bool:
    return os.environ.get("GTM_TRACE_CONTENT") == "1"


def generation(store: Store, agent: str, model: str, model_class: str, input_tokens: int, output_tokens: int,
               usd: float, latency_ms: int, status: str = "ok", prompt: str = "", output: str = "") -> str:
    ensure(store)
    sid = uuid.uuid4().hex
    meta = {"prompt": prompt[:4000], "output": output[:4000]} if _content() else {}
    store.execute("INSERT INTO spans (id, trace_id, agent, kind, name, model, model_class, input_tokens, output_tokens, "
                  "usd, latency_ms, status, meta, started_at, ended_at, exported) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                  (sid, current(), agent, "generation", f"{agent}:{model_class}", model, model_class, input_tokens,
                   output_tokens, usd, latency_ms, status, json.dumps(meta), now_iso(), now_iso()))
    return sid


def draft_span(store: Store, agent: str, kind: str, facts: dict, instructions: str, subject: str, body: str,
               gate_score: int, passed: bool, source: str, attempts: int, exemplars: list | None = None) -> str:
    """The finished draft with the facts it came from. Matched to the stored draft by its body text."""
    ensure(store)
    sid = uuid.uuid4().hex
    store.execute("INSERT INTO spans (id, trace_id, agent, kind, name, model, status, body_hash, facts, output, meta, "
                  "started_at, ended_at, exported) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                  (sid, current(), agent, "draft", kind, source, "passed" if passed else "failed", body_hash(body),
                   json.dumps(facts, default=str)[:20000], json.dumps({"subject": subject, "body": body}),
                   json.dumps({"instructions": instructions[:2000], "gate_score": gate_score, "attempts": attempts,
                               "exemplars": exemplars or []}),
                   now_iso(), now_iso()))
    return sid


def similarity(before: str, after: str) -> float:
    return round(difflib.SequenceMatcher(None, before or "", after or "").ratio(), 4)


def _drafts_for(store: Store, rid: int, payload: dict) -> list[dict]:
    ids = set(int(x) for x in (payload.get("draft_ids") or []) if str(x).isdigit())
    if str(payload.get("draft_id") or "").isdigit():
        ids.add(int(payload["draft_id"]))
    rows = store.query("SELECT * FROM drafts WHERE approval_id=?", (rid,))
    for i in ids - {r["id"] for r in rows}:
        r = store.one("SELECT * FROM drafts WHERE id=?", (i,))
        if r:
            rows.append(r)
    return rows


def _final_text(payload: dict, draft: dict, index: int) -> tuple[str, str]:
    """(subject, body) as approved: the payload's own copy, or the matching step of a sequence."""
    steps = payload.get("steps")
    if steps and index < len(steps):
        return steps[index].get("subject", ""), steps[index].get("body", "")
    if "body" in payload:
        return payload.get("subject", ""), payload.get("body", "")
    return draft.get("subject") or "", draft.get("body") or ""


def on_decision(store: Store, rid: int, action: str, payload: dict, approved: bool, by: str) -> int:
    """Feedback rows for each draft behind this approval. Returns how many were written."""
    ensure(store)
    n = 0
    drafts = sorted(_drafts_for(store, rid, payload), key=lambda d: d["id"])
    order = [int(x) for x in payload.get("draft_ids") or [] if str(x).isdigit()]
    for d in drafts:
        idx = order.index(d["id"]) if d["id"] in order else 0
        span = store.one("SELECT id, trace_id FROM spans WHERE kind='draft' AND body_hash=? ORDER BY started_at DESC "
                         "LIMIT 1", (body_hash(d.get("body") or ""),))
        subj, body = _final_text(payload, d, idx)
        before = json.dumps({"subject": d.get("subject") or "", "body": d.get("body") or ""})
        after = json.dumps({"subject": subj, "body": body})
        rows = [("ae_decision", 1.0 if approved else 0.0, action)]
        if approved:
            rows.append(("ae_edit_similarity", similarity((d.get("subject") or "") + "\n" + (d.get("body") or ""),
                                                          subj + "\n" + body), action))
        for name, value, comment in rows:
            store.execute("INSERT INTO feedback (id, trace_id, span_id, draft_id, approval_id, agent, kind, name, value, "
                          "comment, before, after, decided_by, created_at, exported) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                          (uuid.uuid4().hex, (span or {}).get("trace_id"), (span or {}).get("id"), d["id"], rid,
                           d.get("agent"), d.get("kind"), name, value, comment, before, after, by, now_iso()))
            n += 1
    return n


# ---------- reads ----------
def feedback_summary(store: Store, days: int = 28, now: datetime | None = None) -> dict:
    """Per agent and draft kind: approvals, rejections, and how much the AE changed what they approved."""
    ensure(store)
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
    rows = store.query("SELECT agent, kind, name, value FROM feedback WHERE created_at>=?", (since,))
    out: dict = {}
    for r in rows:
        k = f"{r['agent']}:{r['kind']}"
        o = out.setdefault(k, {"approved": 0, "rejected": 0, "sims": []})
        if r["name"] == "ae_decision":
            o["approved" if r["value"] >= 1 else "rejected"] += 1
        elif r["name"] == "ae_edit_similarity":
            o["sims"].append(r["value"])
    for o in out.values():
        s = o.pop("sims")
        o["sent_as_written"] = sum(1 for x in s if x >= 0.98)
        o["avg_similarity"] = round(sum(s) / len(s), 3) if s else None
        total = o["approved"] + o["rejected"]
        o["accept_rate"] = round(o["approved"] / total, 3) if total else None
    return out


def examples(store: Store, kind: str | None = None, min_similarity: float = 0.0, limit: int = 500,
             writer_kind: str | None = None) -> list[dict]:
    """Approved drafts with the facts they were written from and the text the AE approved (the gold answer).
    `kind` filters on the stored draft kind, `writer_kind` on the kind the writer was asked for."""
    ensure(store)
    sql = ("SELECT f.after, f.value, f.kind, f.agent, s.name, s.facts, s.meta, s.output FROM feedback f "
           "JOIN spans s ON s.id=f.span_id WHERE f.name='ae_edit_similarity' AND f.value>=?")
    p: list = [min_similarity]
    if kind:
        sql += " AND f.kind=?"
        p.append(kind)
    if writer_kind:
        sql += " AND s.name=?"
        p.append(writer_kind)
    out = []
    for r in store.query(sql + " ORDER BY f.created_at DESC, f.id LIMIT ?", (*p, limit)):
        out.append({"agent": r["agent"], "kind": r["kind"], "writer_kind": r["name"], "similarity": r["value"], "facts": json.loads(r["facts"] or "{}"),
                    "instructions": json.loads(r["meta"] or "{}").get("instructions", ""),
                    "drafted": json.loads(r["output"] or "{}"), "approved": json.loads(r["after"] or "{}")})
    return out


# ---------- Langfuse ----------
def langfuse_config() -> dict | None:
    pk, sk = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
    if not (pk and sk):
        return None
    return {"host": os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/"), "pk": pk, "sk": sk}


def _event(kind: str, body: dict, ts: str | None) -> dict:
    return {"id": uuid.uuid4().hex, "timestamp": ts or now_iso(), "type": kind, "body": body}


def export_langfuse(store: Store, client=None, batch_size: int = 200) -> dict:
    """Send unexported spans and feedback to Langfuse. Marks rows exported only after a 2xx (or 207) reply."""
    cfg = langfuse_config()
    if not cfg:
        return {"skipped": "Langfuse not configured (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)"}
    ensure(store)
    import httpx
    http = client or httpx.Client(timeout=30)
    spans = store.query("SELECT * FROM spans WHERE exported=0 ORDER BY started_at LIMIT ?", (batch_size,))
    fb = store.query("SELECT * FROM feedback WHERE exported=0 AND trace_id IS NOT NULL ORDER BY created_at LIMIT ?",
                     (batch_size,))
    if not spans and not fb:
        return {"sent": 0}
    batch, seen = [], set()
    for s in spans:
        if s["trace_id"] not in seen:
            seen.add(s["trace_id"])
            batch.append(_event("trace-create", {"id": s["trace_id"], "name": s["agent"], "timestamp": s["started_at"],
                                                 "metadata": {"agent": s["agent"]}}, s["started_at"]))
        body = {"id": s["id"], "traceId": s["trace_id"], "name": s["name"], "startTime": s["started_at"],
                "endTime": s["ended_at"], "metadata": {"kind": s["kind"], "status": s["status"]}}
        if s["kind"] == "generation":
            body.update({"model": s["model"], "usage": {"input": s["input_tokens"] or 0, "output": s["output_tokens"] or 0,
                                                         "unit": "TOKENS"}})
            if s.get("usd") is not None:
                body["costDetails"] = {"total": s["usd"]}
            meta = json.loads(s.get("meta") or "{}")
            if meta.get("prompt"):
                body.update({"input": meta["prompt"], "output": meta.get("output")})
            batch.append(_event("generation-create", body, s["started_at"]))
        else:
            meta = json.loads(s.get("meta") or "{}")
            if os.environ.get("GTM_TRACE_CONTENT") == "1":  # buyer facts and email text leave only on opt-in
                body.update({"input": json.loads(s.get("facts") or "{}"), "output": json.loads(s.get("output") or "{}")})
            body["metadata"] = {k: meta.get(k) for k in ("gate_score", "attempts", "exemplars")}
            batch.append(_event("span-create", body, s["started_at"]))
    for f in fb:
        batch.append(_event("score-create", {"id": f["id"], "traceId": f["trace_id"], "observationId": f["span_id"],
                                             "name": f["name"], "value": f["value"],
                                             "comment": f"{f['kind']} by {f['decided_by']}"}, f["created_at"]))
    r = http.post(f"{cfg['host']}/api/public/ingestion", json={"batch": batch}, auth=(cfg["pk"], cfg["sk"]))
    if r.status_code not in (200, 201, 207):
        return {"error": f"Langfuse returned {r.status_code}", "body": r.text[:300]}
    failed = set()
    if r.status_code == 207:
        try:
            failed = {e.get("id") for e in (r.json().get("errors") or [])}
        except ValueError:
            failed = set()
    ok_ids = {e["body"]["id"] for e in batch if e["id"] not in failed}
    for s in spans:
        if s["id"] in ok_ids:
            store.execute("UPDATE spans SET exported=1 WHERE id=?", (s["id"],))
    for f in fb:
        if f["id"] in ok_ids:
            store.execute("UPDATE feedback SET exported=1 WHERE id=?", (f["id"],))
    return {"sent": len(batch), "spans": len(spans), "scores": len(fb), "failed": len(failed)}
