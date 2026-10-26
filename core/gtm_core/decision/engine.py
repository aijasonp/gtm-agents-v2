"""Run a decision model for one subject, with caching, fallback and shadow mode.

Config lives in the `judgment` section of config/icp.yaml:

  backend: auto | rules | clef | model | remote | shadow
      auto   = remote when GTM_DECISION_URL is set, else model when a key is set, else rules
  shadow: {primary: rules, candidate: model}
      returns the primary verdict and stores the candidate's answers and agreement next to it,
      so a new backend can be measured on live accounts before it decides anything
  cache_days: verdicts are reused while the state and the model are unchanged and younger than this

Unanswered questions always fall back to the rules backend, so a model outage degrades to the
offline answers instead of to nothing. Learned per-question multipliers (see learn.py) are
read from the weights table as `dq:<model>:<question>`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from ..store import now_iso
from .backends import ClefBackend, ModelBackend, RemoteBackend, RulesBackend
from .model import Answer, DecisionModel, Verdict, load_judgment


@lru_cache(maxsize=16)
def _judgment(path: str, mtime: float) -> dict:
    return load_judgment(path)


def judgment(icp_path: str | Path) -> dict:
    p = Path(icp_path)
    return _judgment(str(p), p.stat().st_mtime if p.exists() else 0.0)


def enabled(cfg: dict) -> bool:
    return bool(cfg) and cfg.get("enabled", True) and bool(cfg.get("models"))


def get_model(cfg: dict, name: str, value_props: list[dict] | None = None) -> DecisionModel | None:
    d = (cfg.get("models") or {}).get(name)
    return DecisionModel.from_dict(name, d, value_props) if d else None


def multipliers(store, model: str) -> dict[str, float]:
    pre = f"dq:{model}:"
    return {k[len(pre):]: v for k, v in store.get_weights().items() if k.startswith(pre)}


def _backend(ctx, name: str, cfg: dict):
    if name == "rules":
        return RulesBackend()
    if name == "model":
        return ModelBackend(ctx)
    if name == "remote":
        return RemoteBackend.from_config(ctx, cfg.get("remote") or {}, getattr(ctx, "decision_client", None))
    if name == "clef":
        return ClefBackend.from_config(ctx, cfg.get("clef") or {}, getattr(ctx, "decision_client", None))
    raise ValueError(f"unknown decision backend {name!r}")


def resolve_backend(ctx, cfg: dict) -> str:
    name = cfg.get("backend", "auto")
    if name != "auto":
        return name
    if _backend(ctx, "clef", cfg).available():
        return "clef"
    if _backend(ctx, "remote", cfg).available():
        return "remote"
    if ModelBackend(ctx).available():
        return "model"
    return "rules"


def _run(ctx, cfg: dict, name: str, model: DecisionModel, state: dict) -> tuple[dict[str, Answer], str]:
    rules = RulesBackend()
    if name == "rules":
        return rules.answer(model, state), "rules"
    b = _backend(ctx, name, cfg)
    got = b.answer(model, state) if b.available() else {}
    missing = [q.id for q in model.questions if q.id not in got]
    if missing:
        got.update(rules.answer(model, state, only=missing))
    used = name if any(a.source == name for a in got.values()) else "rules"
    return got, used


def _hash(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:20]


def decide(ctx, cfg: dict, model: DecisionModel, subject: str, state: dict, now: datetime | None = None,
           refresh: bool = False) -> Verdict:
    """Answer `model` for `subject` (an account id, lead id, ...) from `state`, cached by state hash."""
    now = now or datetime.now(timezone.utc)
    h = _hash(state)
    fp = model.fingerprint()
    mult = multipliers(ctx.store, model.name)
    if not refresh:
        since = (now - timedelta(days=float(cfg.get("cache_days", 30)))).isoformat()
        row = ctx.store.one("SELECT * FROM decisions WHERE model=? AND subject=? AND state_hash=? AND fingerprint=? "
                            "AND created_at>=? ORDER BY id DESC LIMIT 1", (model.name, subject, h, fp, since))
        if row:
            answers = {k: Answer(**v) for k, v in json.loads(row["answers"]).items()}
            score, cov, reasons = model.score(answers, mult)
            return Verdict(model.name, answers, score, cov, row["backend"], reasons, cached=True,
                           shadow=json.loads(row["shadow"]) if row.get("shadow") else None)
    name = resolve_backend(ctx, cfg)
    shadow = None
    if name == "shadow":
        sc = cfg.get("shadow") or {}
        answers, used = _run(ctx, cfg, sc.get("primary", "rules"), model, state)
        cand, cused = _run(ctx, cfg, sc.get("candidate", "model"), model, state)
        both = [q.id for q in model.questions if q.id in answers and q.id in cand]
        agree = sum(1 for q in both if answers[q].value == cand[q].value)
        cscore, _, _ = model.score(cand, mult)
        shadow = {"backend": cused, "score": cscore, "agreement": round(agree / len(both), 3) if both else None,
                  "compared": len(both), "answers": {k: a.as_dict() for k, a in cand.items()}}
    else:
        answers, used = _run(ctx, cfg, name, model, state)
    score, cov, reasons = model.score(answers, mult)
    ctx.store.insert(
        "INSERT INTO decisions (model, subject, state_hash, fingerprint, backend, answers, score, coverage, shadow, "
        "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (model.name, subject, h, fp, used, json.dumps({k: a.as_dict() for k, a in answers.items()}, default=str),
         score, cov, json.dumps(shadow, default=str) if shadow else None, now.replace(microsecond=0).isoformat()
         if now else now_iso()))
    return Verdict(model.name, answers, score, cov, used, reasons, shadow=shadow)


def latest(store, model: str, subject: str) -> dict | None:
    row = store.one("SELECT * FROM decisions WHERE model=? AND subject=? ORDER BY id DESC LIMIT 1", (model, subject))
    if row:
        row["answers"] = json.loads(row["answers"] or "{}")
        row["shadow"] = json.loads(row["shadow"]) if row.get("shadow") else None
    return row


def account_state(acct: dict, signals: list[dict] | None = None, tax=None, contact: dict | None = None) -> dict:
    """The facts a decision may use: firmographics, free-text fields, and recent signal titles."""
    keep = ("name", "domain", "industry", "employees", "revenue", "country", "tech", "description", "keywords",
            "segment", "notes", "funding_stage", "hq")
    a = {k: acct.get(k) for k in keep if acct.get(k) not in (None, "", [])}
    sigs = []
    for s in (signals or [])[:15]:
        t = tax.types.get(s["signal_type"]) if tax else None
        sigs.append({"type": s["signal_type"], "name": t.name if t else s["signal_type"],
                     "title": (s.get("payload") or {}).get("title"), "observed_at": str(s.get("observed_at"))[:10]})
    st = {"account": a, "signals": sigs}
    if contact:
        st["contact"] = {k: contact.get(k) for k in ("title", "function", "seniority") if contact.get(k)}
    return st
