"""Backends that answer a decision model's questions about one state.

  rules   offline and deterministic. Answers only from evidence terms and numeric bands set
          in config; anything without evidence stays unknown. Used in tests, evals and as
          the per-question fallback for every other backend.
  model   the customer's own model through the gateway (cheap tier). Every answer must
          quote evidence found in the state; an answer whose evidence is not in the state
          is dropped as unknown, so the model cannot invent facts about an account.
  remote  an HTTP decision service (for example one hosted on Cloudflare Workers AI or any
          typed-decision runtime). POST {model, version, state, questions}; it returns
          {answers: {id: {value, evidence, confidence}}}. Same validation as `model`.

Every backend returns validated answers only. Invalid answers are logged and dropped.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .model import Answer, DecisionModel, Question


def state_text(state: dict) -> str:
    """Flatten the state into lowercase text for evidence matching."""
    parts: list[str] = []

    def walk(v: Any):
        if v is None:
            return
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple, set)):
            for x in v:
                walk(x)
        else:
            parts.append(str(v))
    walk(state)
    return _norm(" ".join(parts))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _field_text(state: dict, fields: list[str] | None) -> str:
    if not fields:
        return state_text(state)
    acct = state.get("account", {})
    picked = {}
    for f in fields:
        if f == "signals":
            picked[f] = state.get("signals")
        elif f in acct:
            picked[f] = acct[f]
        elif f in state:
            picked[f] = state[f]
    return state_text(picked)


def _hit(text: str, terms: list[str]) -> str | None:
    for t in terms or []:
        tt = _norm(str(t))
        if tt and re.search(r"(?<![a-z0-9])" + re.escape(tt) + r"(?![a-z0-9])", text):
            return str(t)
    return None


class RulesBackend:
    name = "rules"

    def answer(self, model: DecisionModel, state: dict, only: list[str] | None = None) -> dict[str, Answer]:
        out: dict[str, Answer] = {}
        for q in model.questions:
            if only is not None and q.id not in only:
                continue
            a = self.one(q, state)
            if a is not None:
                out[q.id] = a
        return out

    def one(self, q: Question, state: dict) -> Answer | None:
        r = q.rules or {}
        if not r:
            return None
        text = _field_text(state, r.get("fields"))
        if q.kind == "bool":
            t = _hit(text, r.get("no_any"))
            if t:
                return Answer(False, f"mentions '{t}'", self.name)
            t = _hit(text, r.get("yes_any"))
            if t:
                return Answer(True, f"mentions '{t}'", self.name)
            return self._band(q, state, r)
        if q.kind == "choice":
            for opt, terms in (r.get("match") or {}).items():
                t = _hit(text, terms if isinstance(terms, list) else [terms])
                if t and str(opt) in q.options:
                    return Answer(str(opt), f"mentions '{t}'", self.name)
            return self._band(q, state, r)
        if q.kind == "score":
            levels = r.get("levels") or {}
            for lvl in sorted(levels, key=lambda x: -int(x)):
                t = _hit(text, levels[lvl])
                if t:
                    return Answer(int(lvl), f"mentions '{t}'", self.name)
            return self._band(q, state, r)
        return None

    def _band(self, q: Question, state: dict, r: dict) -> Answer | None:
        """Numeric bands: {field: employees, bands: [[lo, hi, answer], ...]} with lo inclusive, hi exclusive."""
        f, bands = r.get("field"), r.get("bands")
        if not f or not bands:
            return None
        v = (state.get("account") or {}).get(f)
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        for lo, hi, ans in bands:
            if float(lo) <= v < float(hi if hi is not None else "inf"):
                try:
                    return Answer(q.validate(ans), f"{f} = {v:g}", self.name)
                except ValueError:
                    return None
        return None


def _validated(model: DecisionModel, raw: dict, state: dict, source: str, log=None) -> dict[str, Answer]:
    """Keep only answers that match the question kind and quote evidence present in the state."""
    text = state_text(state)
    out: dict[str, Answer] = {}
    qs = model.by_id
    for qid, a in (raw or {}).items():
        q = qs.get(qid)
        if q is None:
            continue
        if not isinstance(a, dict):
            a = {"value": a}
        try:
            v = q.validate(a.get("value"))
        except ValueError as e:
            if log:
                log("decision.invalid", question=qid, error=str(e)[:200], source=source)
            continue
        if v is None:
            continue
        ev = str(a.get("evidence") or "").strip()
        if not ev or _norm(ev) not in text:
            if log:
                log("decision.unsupported", question=qid, evidence=ev[:120], source=source)
            continue
        conf = a.get("confidence")
        try:
            conf = None if conf is None else max(0.0, min(1.0, float(conf)))
        except (TypeError, ValueError):
            conf = None
        out[qid] = Answer(v, ev[:300], source, conf)
    return out


SYSTEM = ("You answer typed questions about one company using only the facts given. "
          "For every answer quote the exact words from the facts that support it as `evidence`. "
          "If the facts do not say, answer null. Never guess. Return JSON only.")


def _prompt(model: DecisionModel, state: dict) -> str:
    return (f"Decision model: {model.name}\n\nQuestions (JSON):\n{json.dumps([q.spec() for q in model.questions], indent=1)}\n\n"
            "Return JSON: {\"answers\": {\"<question id>\": {\"value\": <bool | option | 1-5 | null>, "
            "\"evidence\": \"<exact quote from facts>\", \"confidence\": <0-1>}}}\n\n"
            f"Facts (JSON):\n{json.dumps(state, default=str, indent=1)[:20000]}")


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return d.get("answers", d) if isinstance(d, dict) else {}


class ModelBackend:
    name = "model"

    def __init__(self, ctx):
        self.ctx = ctx

    def available(self) -> bool:
        try:
            return bool(self.ctx.gateway.available("cheap"))
        except AttributeError:
            return False

    def answer(self, model: DecisionModel, state: dict, only: list[str] | None = None) -> dict[str, Answer]:
        if not self.available():
            return {}
        from ..budgets import BudgetExceeded
        try:
            out = self.ctx.gateway.complete(_prompt(model, state), system=SYSTEM, model_class="cheap",
                                            max_tokens=900).text
        except BudgetExceeded:
            raise
        except Exception as e:
            self.ctx.audit.log("decision.error", backend=self.name, error=str(e)[:300])
            return {}
        return _validated(model, _parse(out), state, self.name, self.ctx.audit.log)


class RemoteBackend:
    name = "remote"

    def __init__(self, ctx, url: str | None = None, token: str | None = None, timeout: float = 20, client=None):
        self.ctx = ctx
        self.url = url
        self.token = token
        self.timeout = timeout
        self.client = client

    @classmethod
    def from_config(cls, ctx, cfg: dict, client=None) -> "RemoteBackend":
        url = os.environ.get(cfg.get("url_env", "GTM_DECISION_URL"), "") or cfg.get("url", "")
        token = os.environ.get(cfg.get("token_env", "GTM_DECISION_TOKEN"), "")
        return cls(ctx, url or None, token or None, float(cfg.get("timeout", 20)), client)

    def available(self) -> bool:
        return bool(self.url) and not getattr(self.ctx.settings, "offline", False)

    def answer(self, model: DecisionModel, state: dict, only: list[str] | None = None) -> dict[str, Answer]:
        if not self.available():
            return {}
        import httpx
        http = self.client or httpx.Client(timeout=self.timeout)
        body = {"model": model.name, "version": model.fingerprint(), "state": state,
                "questions": [q.spec() for q in model.questions if only is None or q.id in only]}
        headers = {"authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            r = http.post(self.url, json=body, headers=headers)
            r.raise_for_status()
            raw = r.json()
        except Exception as e:
            self.ctx.audit.log("decision.error", backend=self.name, error=str(e)[:300])
            return {}
        return _validated(model, raw.get("answers", {}) if isinstance(raw, dict) else {}, state, self.name,
                          self.ctx.audit.log)


class ClefBackend:
    """Cloudflare Workers AI Clef: a typed decision model (state plus typed questions in, a probability per
    option out). Clef does not quote evidence, so an answer is kept only when its confidence clears
    `min_confidence`; anything below falls back to the rules backend like an unanswered question.

    Question kinds map to Clef's primitives: bool -> noul (probability true), choice -> choice over the
    options, score -> score over five levels "1".."5". Endpoint:
    POST https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}
    with {"state": ..., "questions": {id: {type, instructions, criteria}}}; the reply is wrapped as
    {"success": true, "result": {"answers": {...}}}.
    """
    name = "clef"
    BASE = "https://api.cloudflare.com/client/v4/accounts"

    def __init__(self, ctx, account: str | None, token: str | None, model: str = "clef", min_confidence: float = 0.7,
                 timeout: float = 30, client=None):
        self.ctx = ctx
        self.account, self.token = account, token
        self.model = model if model in ("clef", "clef-flash") else "clef"
        self.min_confidence = float(min_confidence)
        self.timeout = timeout
        self.client = client

    @classmethod
    def from_config(cls, ctx, cfg: dict, client=None) -> "ClefBackend":
        return cls(ctx, os.environ.get(cfg.get("account_env", "CLOUDFLARE_ACCOUNT_ID")) or None,
                   os.environ.get(cfg.get("token_env", "CLOUDFLARE_AUTH_TOKEN")) or None, cfg.get("model", "clef"),
                   float(cfg.get("min_confidence", 0.7)), float(cfg.get("timeout", 30)), client)

    def available(self) -> bool:
        return bool(self.account and self.token) and not getattr(self.ctx.settings, "offline", False)

    @staticmethod
    def question(q: Question) -> dict:
        if q.kind == "bool":
            return {"type": "noul", "instructions": q.ask}
        if q.kind == "choice":
            return {"type": "choice", "instructions": q.ask, "criteria": sorted(q.options)}
        return {"type": "score", "instructions": f"{q.ask} Answer on a scale of 1 (lowest) to 5 (highest).",
                "criteria": ["1", "2", "3", "4", "5"]}

    @staticmethod
    def _pick(probs) -> tuple[str | None, float | None]:
        if isinstance(probs, dict) and probs:
            k = max(probs, key=lambda x: float(probs[x]))
            return str(k), float(probs[k])
        if isinstance(probs, list) and probs:
            i = max(range(len(probs)), key=lambda j: float(probs[j]))
            return str(i), float(probs[i])
        return None, None

    def read(self, q: Question, a: dict) -> tuple[object, float | None]:
        """(value in our kind, confidence) from one Clef answer, or (None, None) when it cannot be read."""
        conf = a.get("confidence")
        if q.kind == "bool":
            p = a.get("noul")
            if p is None:
                return None, None
            p = float(p)
            return p >= 0.5, float(conf) if conf is not None else max(p, 1 - p)
        if q.kind == "choice":
            v = a.get("choice")
            if v is None:
                v, pc = self._pick(a.get("probabilities"))
                conf = conf if conf is not None else pc
            return v, None if conf is None else float(conf)
        label, pc = self._pick(a.get("probabilities"))
        legend = {str(k): str(v) for k, v in (a.get("legend") or {}).items()}
        if label is not None and legend and label in legend:
            label = legend[label]  # probabilities keyed by index: the legend names the level
        elif isinstance(a.get("probabilities"), list) and label is not None:
            label = str(int(label) + 1)  # index list with no legend: position 0 is level "1"
        if label is None and a.get("score") is not None:
            s = a["score"]
            label = legend.get(str(round(float(s)))) or None
            if label is None and 1 <= float(s) <= 5:
                label = str(round(float(s)))
        conf = conf if conf is not None else pc
        try:
            return (int(label) if label is not None else None), None if conf is None else float(conf)
        except ValueError:
            return None, None

    def answer(self, model: DecisionModel, state: dict, only: list[str] | None = None) -> dict[str, Answer]:
        if not self.available():
            return {}
        import httpx
        qs = [q for q in model.questions if only is None or q.id in only]
        body = {"state": state, "questions": {q.id: self.question(q) for q in qs}}
        http = self.client or httpx.Client(timeout=self.timeout)
        url = f"{self.BASE}/{self.account}/ai/run/@cf/cloudflare/{self.model}"
        try:
            r = http.post(url, json=body, headers={"authorization": f"Bearer {self.token}"})
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError(f"Clef error: {data.get('errors')}")
            raw = (data.get("result") or data).get("answers") or {}
        except Exception as e:
            self.ctx.audit.log("decision.error", backend=self.name, error=str(e)[:300])
            return {}
        out: dict[str, Answer] = {}
        for q in qs:
            a = raw.get(q.id)
            if not isinstance(a, dict):
                continue
            v, conf = self.read(q, a)
            try:
                v = q.validate(v)
            except ValueError as e:
                self.ctx.audit.log("decision.invalid", question=q.id, error=str(e)[:200], source=self.name)
                continue
            if v is None or conf is None or conf < self.min_confidence:
                self.ctx.audit.log("decision.low_confidence", question=q.id, confidence=conf, source=self.name)
                continue
            out[q.id] = Answer(v, f"clef p={conf:.2f}", self.name, round(conf, 3))
        return out
