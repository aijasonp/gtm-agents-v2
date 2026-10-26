"""Drafting and extraction on the customer's model keys, with a deterministic floor.

write()    -> outbound copy (email, LinkedIn, recap). Frontier model drafts from the
              facts given, with up to `exemplars` (config, default 3) approved emails of the
              same kind as style examples and the phrases AEs usually cut, the Copy QA Gate
              scores it, and failures go back for up to `max_rewrites` rewrites. With no model key configured, the agent's own
              template is used so every agent still runs (demo, evals, air-gapped).
extract()  -> structured JSON from text (cheap model). Returns None when no key is
              configured or the reply is not valid JSON; callers keep their
              rule-based result in that case.
narrate()  -> short internal prose (briefs, summaries). Falls back to the given text.

Prompts carry facts only. The model is told to use nothing outside them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import copy_gate
from .budgets import BudgetExceeded

FACTS_RULE = ("Use only the facts provided. Never invent names, numbers, customers, quotes or events. "
              "If a fact you would need is missing, leave it out rather than guess.")
STYLE_RULE = ("Write like a busy, competent person: short sentences, plain words, no em dashes, no exclamation "
              "marks, no hype words, one clear ask.")


@dataclass
class Draft:
    subject: str
    body: str
    score: int
    passed: bool
    source: str  # "model" or "template"
    attempts: int = 1
    fix: list[str] = field(default_factory=list)
    exemplars: list[str] = field(default_factory=list)  # ids of the approved examples shown to the model

    def as_dict(self) -> dict:
        return {"subject": self.subject, "body": self.body, "gate_score": self.score, "gate_passed": self.passed,
                "source": self.source, "attempts": self.attempts, "fix": self.fix}


def model_available(ctx, model_class: str = "frontier") -> bool:
    try:
        return ctx.gateway.available(model_class)
    except AttributeError:  # minimal contexts in tests
        s = ctx.settings
        return bool(s.anthropic_api_key or s.openai_api_key)


def _skill_text(ctx) -> str:
    try:
        text = ctx.manifest.path(ctx.manifest.skill).read_text()
    except OSError:
        return ""
    return re.sub(r"^---\n.*?\n---\n?", "", text, flags=re.S)


def _banned(ctx) -> list[str]:
    path = ctx.manifest.config.get("banned_file")
    return copy_gate.load_banned(ctx.manifest.path(path) if path else None)


def split_subject(text: str) -> tuple[str, str]:
    text = text.strip()
    m = re.match(r"(?is)^\s*subject\s*:\s*(.+?)\n+(.*)$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", text


def _gate(ctx, body: str, max_words: int):
    return copy_gate.check(body, _banned(ctx), max_words=max_words,
                           pass_mark=int(ctx.manifest.config.get("pass_mark", 32)))


def write(ctx, kind: str, facts: dict, instructions: str, fallback: str, max_words: int = 120,
          max_rewrites: int = 2, subject_fallback: str = "") -> Draft:
    """Draft outbound copy from facts, enforce the Copy QA Gate, fall back to the template.
    The finished draft and its facts are recorded as a trace span, so the AE's later approval or edit
    becomes a labeled example for the drafter."""
    d = _write(ctx, kind, facts, instructions, fallback, max_words, max_rewrites, subject_fallback)
    try:
        from . import telemetry
        telemetry.draft_span(ctx.store, ctx.manifest.id, kind, facts, instructions, d.subject, d.body, d.score,
                             d.passed, d.source, d.attempts, exemplars=d.exemplars)
    except Exception:  # minimal contexts in tests, or a store without telemetry tables
        pass
    return d


def _exemplars(ctx, kind: str, facts: dict) -> tuple[str, list[str]]:
    """Few-shot block from AE-approved sends (core/gtm_core/exemplars.py). Empty until `build` has run."""
    k = int(ctx.manifest.config.get("exemplars", 3) or 0)
    if k <= 0:
        return "", []
    try:
        from . import exemplars
        return exemplars.prompt_block(ctx.store, kind, facts, k)
    except Exception:  # minimal contexts, or a store without telemetry tables
        return "", []


def _write(ctx, kind: str, facts: dict, instructions: str, fallback: str, max_words: int = 120,
           max_rewrites: int = 2, subject_fallback: str = "") -> Draft:
    if not model_available(ctx):
        subj, body = split_subject(fallback)
        g = _gate(ctx, body, max_words)
        return Draft(subj or subject_fallback, body, g.score, g.passed, "template", 0, g.failures())

    system = "\n\n".join([_skill_text(ctx), FACTS_RULE, STYLE_RULE])
    shots, used = _exemplars(ctx, kind, facts)
    prompt = (f"Task: write a {kind}.\n{instructions}\n\nFacts (JSON):\n{json.dumps(facts, default=str, indent=1)}\n\n"
              + (shots + "\n\n" if shots else "") +
              f"Keep the body under {max_words} words. If it is an email, put 'Subject: ...' on the first line. "
              "Return only the message.")
    attempts, last = 0, None
    try:
        while attempts <= max_rewrites:
            attempts += 1
            out = ctx.gateway.complete(prompt, system=system, model_class="frontier", max_tokens=700).text
            subj, body = split_subject(out)
            g = _gate(ctx, body, max_words)
            last = Draft(subj or subject_fallback, body, g.score, g.passed, "model", attempts, g.failures(), used)
            if g.passed:
                return last
            prompt = (f"Rewrite this {kind} so it passes these checks. Fix every item, keep the facts.\n"
                      f"Failures: {'; '.join(g.failures())}\n\nDraft:\n{out}\n\nFacts (JSON):\n"
                      f"{json.dumps(facts, default=str, indent=1)}\nReturn only the message.")
    except BudgetExceeded:
        raise
    except Exception as e:  # model or network failure: never block the workflow
        ctx.audit.log("writer.error", kind=kind, error=str(e)[:300])
    if last and last.passed:
        return last
    subj, body = split_subject(fallback)
    g = _gate(ctx, body, max_words)
    if last and last.score > g.score:
        return last
    return Draft(subj or subject_fallback, body, g.score, g.passed, "template", attempts, g.failures())


def _parse_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        end = max(text.rfind("}"), text.rfind("]"))
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None


def extract(ctx, task: str, text: str, schema_hint: str, max_tokens: int = 1200):
    """Structured extraction with the cheap model. None when unavailable or unparseable."""
    if not model_available(ctx, "cheap"):
        return None
    prompt = (f"{task}\n\nReturn JSON only, matching this shape:\n{schema_hint}\n\n"
              f"Quote short evidence from the text for every field you fill. Use null when the text does not say.\n\n"
              f"Text:\n{text[:60000]}")
    try:
        out = ctx.gateway.complete(prompt, system=FACTS_RULE, model_class="cheap", max_tokens=max_tokens).text
    except BudgetExceeded:
        raise
    except Exception as e:
        ctx.audit.log("writer.error", kind="extract", error=str(e)[:300])
        return None
    return _parse_json(out)


def narrate(ctx, task: str, facts: dict, fallback: str, max_words: int = 200) -> tuple[str, str]:
    """Short internal prose from facts. Returns (text, source)."""
    if not model_available(ctx):
        return fallback, "template"
    prompt = (f"{task}\nUnder {max_words} words. Plain words, no em dashes, no filler.\n\n"
              f"Facts (JSON):\n{json.dumps(facts, default=str, indent=1)}")
    try:
        out = ctx.gateway.complete(prompt, system=_skill_text(ctx) + "\n\n" + FACTS_RULE, model_class="frontier",
                                   max_tokens=900).text.strip()
        return (out or fallback), ("model" if out else "template")
    except BudgetExceeded:
        raise
    except Exception as e:
        ctx.audit.log("writer.error", kind="narrate", error=str(e)[:300])
        return fallback, "template"
