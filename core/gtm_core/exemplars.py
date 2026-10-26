"""Drafter tuning from AE decisions: approved emails become few-shot examples, AE edits become rules.

Every drafted send that an AE approves is a labeled example: the facts it was written from (telemetry draft
span) and the text the AE actually sent (approval feedback). This module turns those into two things the
writer uses, both computed in code, offline, from the customer's own database:

  exemplars      per writer kind (the `kind` passed to writer.write), a small, varied set of approved emails that pass the Copy QA Gate today.
                 `build()` rebuilds the set and stamps a version; `select()` picks the k closest to a new
                 draft's facts by feature overlap (persona, industry, signal, angle, motion), ties by rank.
  edit patterns  word runs AEs delete or rewrite again and again (a word-level diff of draft vs sent), handed
                 to the model as "AEs usually remove: ...". A phrase needs `min_count` separate edits to count.

`optimize_dspy()` is an optional pass with DSPy (pip install dspy) on a frontier model: BootstrapFewShot
searches the approved examples for the demos that score best on a held-out split, scored by the same gate
plus similarity to what the AE sent. Its picks only replace the deterministic set when they score higher on
that split, and they pass through the same gate, so the writer never depends on DSPy being installed.

Exemplar facts never reach the new draft: the prompt says to copy tone, length and structure only.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone

from . import copy_gate, telemetry
from .store import Store, now_iso

SCHEMA = """CREATE TABLE IF NOT EXISTS exemplars (
  id TEXT PRIMARY KEY, kind TEXT, rank INTEGER, version TEXT, source TEXT, features TEXT, facts TEXT, subject TEXT,
  body TEXT, similarity REAL, compiled_at TEXT)"""
FEATURE_KEYS = ("persona", "title", "industry", "signal_type", "signal_source", "angle", "angle_key", "value_prop",
                "motion", "stage", "tier", "event", "kind")
WORD = re.compile(r"[a-z0-9']+")


def ensure(store: Store) -> None:
    if not getattr(store, "_exemplar_schema", False):
        store.execute(SCHEMA)
        store.execute("CREATE INDEX IF NOT EXISTS exemplars_kind ON exemplars (kind, rank)")
        store._exemplar_schema = True


def _walk(facts, prefix="") -> dict:
    out = {}
    if isinstance(facts, dict):
        for k, v in facts.items():
            out.update(_walk(v, k))
    elif isinstance(facts, (str, int, float)) and prefix:
        out[prefix] = facts
    return out


def features(facts: dict) -> set[str]:
    """Stable, low-cardinality labels from a draft's facts: key=value for known keys, with titles bucketed."""
    flat = _walk(facts or {})
    out = set()
    for k in FEATURE_KEYS:
        v = flat.get(k)
        if v in (None, ""):
            continue
        v = str(v).strip().lower()
        if k in ("persona", "title"):
            v = _seniority(v)
            k = "persona"
        out.add(f"{k}={v[:60]}")
    return out


def _seniority(title: str) -> str:
    for label, words in (("c_level", ("chief", "cro", "ceo", "cfo", "coo")), ("vp", ("vp", "vice president")),
                         ("head", ("head of",)), ("director", ("director",)), ("manager", ("manager",))):
        if any(re.search(rf"\b{re.escape(w)}\b", title) for w in words):
            return label
    return "other"


def _gate_ok(body: str, banned: list[str], max_words: int, pass_mark: int) -> bool:
    return copy_gate.check(body, banned, max_words=max_words, pass_mark=pass_mark).passed


def candidates(store: Store, kind: str, banned: list[str] | None = None, max_words: int = 150, pass_mark: int = 32,
               min_similarity: float = 0.0) -> list[dict]:
    """Approved examples of one kind that pass the gate as sent, newest first, one per distinct body."""
    seen, out = set(), []
    for ex in telemetry.examples(store, min_similarity=min_similarity, limit=2000, writer_kind=kind):
        body = (ex["approved"].get("body") or "").strip()
        key = re.sub(r"\s+", " ", body.lower())
        if not body or key in seen or not _gate_ok(body, banned or [], max_words, pass_mark):
            continue
        seen.add(key)
        out.append({**ex, "features": sorted(features(ex["facts"]))})
    return out


def pick_diverse(cands: list[dict], n: int) -> list[dict]:
    """Greedy: each pick adds the most features not yet covered; ties go to the AE-edited one, then the newer."""
    left, chosen, covered = list(cands), [], set()
    while left and len(chosen) < n:
        best = max(range(len(left)), key=lambda i: (len(set(left[i]["features"]) - covered),
                                                    -left[i]["similarity"], -i))
        c = left.pop(best)
        chosen.append(c)
        covered |= set(c["features"])
    return chosen


def build(store: Store, kinds: list[str] | None = None, per_kind: int = 8, banned: list[str] | None = None,
            max_words: int = 150, pass_mark: int = 32, min_examples: int = 3, now: datetime | None = None) -> dict:
    """Rebuild the exemplar set for each kind with at least `min_examples` approved sends. Deterministic."""
    ensure(store)
    if kinds is None:
        telemetry.ensure(store)
        kinds = sorted({r["name"] for r in store.query(
            "SELECT DISTINCT s.name FROM feedback f JOIN spans s ON s.id=f.span_id "
            "WHERE f.name='ae_edit_similarity' AND s.name IS NOT NULL")})
    stamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    report = {}
    for kind in kinds:
        cands = candidates(store, kind, banned, max_words, pass_mark)
        if len(cands) < min_examples:
            report[kind] = {"examples": len(cands), "kept": 0, "skipped": f"needs {min_examples} approved sends"}
            continue
        chosen = pick_diverse(cands, per_kind)
        version = hashlib.sha1(json.dumps([c["approved"] for c in chosen], sort_keys=True).encode()).hexdigest()[:10]
        _replace(store, kind, chosen, version, "rules", stamp)
        report[kind] = {"examples": len(cands), "kept": len(chosen), "version": version}
    return report


def _replace(store: Store, kind: str, chosen: list[dict], version: str, source: str, stamp: str) -> None:
    store.execute("DELETE FROM exemplars WHERE kind=?", (kind,))
    for i, c in enumerate(chosen):
        store.execute("INSERT INTO exemplars (id, kind, rank, version, source, features, facts, subject, body, similarity, "
                      "compiled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (f"{kind}:{i}", kind, i, version, source, json.dumps(c["features"]),
                       json.dumps(c["facts"], default=str)[:8000], c["approved"].get("subject") or "",
                       c["approved"].get("body") or "", c["similarity"], stamp))


def select(store: Store, kind: str, facts: dict, k: int = 3) -> list[dict]:
    """The k stored exemplars closest to these facts (shared features), ties by compiled rank."""
    try:
        ensure(store)
        rows = store.query("SELECT * FROM exemplars WHERE kind=? ORDER BY rank", (kind,))
    except Exception:  # a store without the table (minimal test contexts)
        return []
    want = features(facts)
    scored = sorted(rows, key=lambda r: (-len(want & set(json.loads(r["features"] or "[]"))), r["rank"]))
    return [{"id": r["id"], "subject": r["subject"], "body": r["body"], "version": r["version"]} for r in scored[:k]]


STOP = {"the", "a", "an", "and", "to", "of", "in", "for", "on", "at", "is", "it", "you", "your", "we", "our", "i",
        "with", "that", "this", "be", "are", "as", "or", "if", "so", "me", "my", "hi", "sam"}


def _cuts(before: str, after: str, max_words: int = 8) -> set[str]:
    """Word runs the AE deleted or replaced, trimmed of filler words at the edges."""
    import difflib
    b, a = WORD.findall((before or "").lower()), WORD.findall((after or "").lower())
    out = set()
    for op, i1, i2, _, _ in difflib.SequenceMatcher(None, b, a, autojunk=False).get_opcodes():
        if op not in ("delete", "replace"):
            continue
        run = b[i1:i2]
        while run and run[0] in STOP:
            run = run[1:]
        while run and run[-1] in STOP:
            run = run[:-1]
        if run and len(run) <= max_words:
            out.add(" ".join(run))
    return out


def edit_patterns(store: Store, kind: str | None = None, min_count: int = 3, limit: int = 8,
                  max_similarity: float = 0.98) -> list[dict]:
    """Phrases AEs deleted or rewrote in at least `min_count` separate approved edits, most frequent first."""
    counts: Counter = Counter()
    for ex in telemetry.examples(store, limit=2000, writer_kind=kind):
        if ex["similarity"] >= max_similarity:
            continue  # sent as written: nothing was cut
        counts.update(_cuts(ex["drafted"].get("body") or "", ex["approved"].get("body") or ""))
    keep = [{"phrase": g, "count": c} for g, c in counts.items() if c >= min_count]
    keep.sort(key=lambda x: (-x["count"], x["phrase"]))
    return keep[:limit]


def prompt_block(store: Store, kind: str, facts: dict, k: int = 3, patterns: bool = True) -> tuple[str, list[str]]:
    """Text appended to the writer's prompt, and the exemplar ids used (recorded on the draft span)."""
    ex = select(store, kind, facts, k)
    parts, ids = [], [e["id"] for e in ex]
    if ex:
        shots = "\n\n".join(f"Example {i + 1}:\n" + (f"Subject: {e['subject']}\n" if e["subject"] else "") + e["body"]
                            for i, e in enumerate(ex))
        parts.append("Approved emails our AEs sent for this kind of message. Match their tone, length and structure. "
                     "Never reuse their names, companies, numbers or details.\n\n" + shots)
    if patterns:
        try:
            cut = [p["phrase"] for p in edit_patterns(store, kind)]
        except Exception:
            cut = []
        if cut:
            parts.append("AEs usually remove these from drafts, so leave them out: " + ", ".join(f'"{c}"' for c in cut))
    return "\n\n".join(parts), ids


# ---------- optional DSPy pass ----------
def score(drafted: str, approved: str, banned: list[str] | None = None, max_words: int = 150, pass_mark: int = 32) -> float:
    """The optimizer's metric: 0 when the draft fails the gate, else its similarity to what the AE sent."""
    if not _gate_ok(drafted or "", banned or [], max_words, pass_mark):
        return 0.0
    return telemetry.similarity(drafted or "", approved or "")


def optimize_dspy(store: Store, kind: str, model: str, banned: list[str] | None = None, max_words: int = 150,
                  pass_mark: int = 32, max_demos: int = 4, holdout: float = 0.3, lm=None) -> dict:
    """BootstrapFewShot over approved examples; keeps its demos only if they beat the current set on the holdout."""
    try:
        import dspy
    except ImportError:
        return {"skipped": "dspy not installed (pip install dspy)"}
    ensure(store)
    cands = candidates(store, kind, banned, max_words, pass_mark)
    if len(cands) < 8:
        return {"skipped": f"needs 8 approved sends of {kind}, have {len(cands)}"}
    cands = sorted(cands, key=lambda c: hashlib.sha1(json.dumps(c["approved"], sort_keys=True).encode()).hexdigest())
    cut = max(2, int(len(cands) * holdout))
    test, train = cands[:cut], cands[cut:]

    class Draft(dspy.Signature):
        """Write a short sales email from the facts only. Plain words, one clear ask, no em dashes."""
        facts: str = dspy.InputField()
        instructions: str = dspy.InputField()
        email: str = dspy.OutputField(desc="the email body only")

    def ex(c):
        return dspy.Example(facts=json.dumps(c["facts"], default=str), instructions=c["instructions"],
                            email=c["approved"].get("body") or "").with_inputs("facts", "instructions")

    def metric(gold, pred, trace=None):
        return score(pred.email, gold.email, banned, max_words, pass_mark)

    dspy.configure(lm=lm or dspy.LM(model, max_tokens=700))
    student = dspy.Predict(Draft)

    def evaluate(program) -> float:
        vals = [metric(e, program(facts=e.facts, instructions=e.instructions)) for e in map(ex, test)]
        return round(sum(vals) / len(vals), 4)

    current = select(store, kind, {}, max_demos)
    base = dspy.Predict(Draft)
    base.demos = [dspy.Example(facts="", instructions="", email=c["body"]) for c in current]
    base_score = evaluate(base)
    tuned = dspy.BootstrapFewShot(metric=metric, max_bootstrapped_demos=max_demos,
                                  max_labeled_demos=max_demos).compile(student, trainset=[ex(c) for c in train])
    tuned_score = evaluate(tuned)
    demos = [d for p in tuned.predictors() for d in p.demos]
    res = {"kind": kind, "train": len(train), "holdout": len(test), "current_score": base_score,
           "dspy_score": tuned_score, "demos": len(demos), "replaced": False}
    if tuned_score > base_score and demos:
        by_body = {(c["approved"].get("body") or "").strip(): c for c in cands}
        chosen = [by_body[d.email.strip()] for d in demos if (d.email or "").strip() in by_body]
        if chosen:
            version = "dspy-" + hashlib.sha1(json.dumps([c["approved"] for c in chosen]).encode()).hexdigest()[:8]
            _replace(store, kind, chosen, version, "dspy", now_iso())
            res.update(replaced=True, version=version)
    return res
