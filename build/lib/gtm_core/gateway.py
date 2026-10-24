"""Model gateway on the customer's own keys.

model_class="cheap"    -> classification, extraction, dedup
model_class="frontier" -> research synthesis and copywriting

Providers: Anthropic Messages API, or any OpenAI-compatible endpoint (OpenAI,
Azure OpenAI, vLLM / open-weight servers). Budgets are checked before every call
and usage is recorded after it.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from .budgets import Budgets
from .config import Settings


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    usd: float


class Gateway:
    def __init__(self, settings: Settings, budgets: Budgets, agent: str = "core", client: httpx.Client | None = None):
        self.s = settings
        self.budgets = budgets
        self.agent = agent
        self.http = client or httpx.Client(timeout=120)

    def model_for(self, model_class: str) -> str:
        return self.s.model_cheap if model_class == "cheap" else self.s.model_frontier

    def complete(self, prompt: str, system: str = "", model_class: str = "cheap",
                 max_tokens: int = 1024, cache_system: bool = True) -> Completion:
        self.budgets.check(self.agent)
        model = self.model_for(model_class)
        if model.startswith("claude") and self.s.anthropic_api_key:
            text, tin, tout = self._anthropic(model, system, prompt, max_tokens, cache_system)
        elif self.s.openai_api_key:
            text, tin, tout = self._openai(model, system, prompt, max_tokens)
        else:
            raise RuntimeError("No model key configured: set ANTHROPIC_API_KEY or OPENAI_API_KEY")
        usd = self.budgets.record(self.agent, model, model_class, tin, tout)
        return Completion(text, model, tin, tout, usd)

    def _anthropic(self, model, system, prompt, max_tokens, cache_system):
        sys_block = [{"type": "text", "text": system,
                      **({"cache_control": {"type": "ephemeral"}} if cache_system else {})}] if system else []
        r = self.http.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.s.anthropic_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": sys_block,
                  "messages": [{"role": "user", "content": prompt}]},
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        u = data.get("usage", {})
        tin = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        return text, tin, u.get("output_tokens", 0)

    def _openai(self, model, system, prompt, max_tokens):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        r = self.http.post(
            f"{self.s.openai_base_url.rstrip('/')}/chat/completions",
            headers={"authorization": f"Bearer {self.s.openai_api_key}"},
            json={"model": model, "messages": msgs, "max_tokens": max_tokens},
        )
        r.raise_for_status()
        data = r.json()
        u = data.get("usage", {})
        return data["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
