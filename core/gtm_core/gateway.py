"""Model gateway on the customer's own keys: frontier APIs or open-weight models, per tier.

Two tiers, routed independently:
  model_class="cheap"    -> classification, extraction, dedup, chat routing
  model_class="frontier" -> research synthesis and copywriting

Each tier resolves to one endpoint:
  * a model name starting with "claude" and ANTHROPIC_API_KEY set -> Anthropic Messages API
  * anything else -> an OpenAI-compatible /chat/completions endpoint: OpenAI, Azure OpenAI,
    vLLM, Ollama, LM Studio, llama.cpp server, Together, Fireworks, Groq, OpenRouter, DeepInfra...

Per-tier overrides let you run the cheap tier on a local open-weight model and the frontier tier
on Claude (or both local):
  GTM_CHEAP_BASE_URL / GTM_CHEAP_API_KEY / GTM_CHEAP_PROVIDER
  GTM_FRONTIER_BASE_URL / GTM_FRONTIER_API_KEY / GTM_FRONTIER_PROVIDER
falling back to OPENAI_BASE_URL / OPENAI_API_KEY. Local servers (anything not on api.openai.com)
need no key. Budgets are checked before every call and usage is recorded after it.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import httpx

from .budgets import Budgets
from .config import Settings

OPENAI_DEFAULT = "https://api.openai.com/v1"


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    usd: float
    tool_calls: list[dict] = field(default_factory=list)  # [{id, name, args}]
    stop_reason: str = ""


@dataclass
class Endpoint:
    provider: str  # "anthropic" | "openai"
    model: str
    base_url: str
    api_key: str | None

    def describe(self) -> str:
        where = "api.anthropic.com" if self.provider == "anthropic" else self.base_url
        return f"{self.model} via {self.provider} ({where})"


def resolve(settings: Settings, model_class: str) -> Endpoint | None:
    if getattr(settings, "offline", False):
        return None
    tier = "CHEAP" if model_class == "cheap" else "FRONTIER"
    model = settings.model_cheap if model_class == "cheap" else settings.model_frontier
    provider = (os.environ.get(f"GTM_{tier}_PROVIDER") or "").lower()
    if provider == "anthropic" or (not provider and model.startswith("claude") and settings.anthropic_api_key):
        if not settings.anthropic_api_key:
            return None
        return Endpoint("anthropic", model, "https://api.anthropic.com/v1", settings.anthropic_api_key)
    tier_base = os.environ.get(f"GTM_{tier}_BASE_URL")
    base = tier_base or settings.openai_base_url or OPENAI_DEFAULT
    # The OpenAI key only goes to the OpenAI endpoint (or the endpoint OPENAI_BASE_URL names), never to a
    # tier-specific server such as a local vLLM or another vendor.
    key = os.environ.get(f"GTM_{tier}_API_KEY") or (None if tier_base else settings.openai_api_key)
    local = OPENAI_DEFAULT not in base  # self-hosted or third-party server: key optional
    if not key and not local:
        return None
    return Endpoint("openai", model, base.rstrip("/"), key)


class Gateway:
    def __init__(self, settings: Settings, budgets: Budgets, agent: str = "core", client: httpx.Client | None = None):
        self.s = settings
        self.budgets = budgets
        self.agent = agent
        self.http = client or httpx.Client(timeout=float(os.environ.get("GTM_MODEL_TIMEOUT", 180)))

    def model_for(self, model_class: str) -> str:
        return self.s.model_cheap if model_class == "cheap" else self.s.model_frontier

    def endpoint(self, model_class: str) -> Endpoint | None:
        return resolve(self.s, model_class)

    def available(self, model_class: str = "frontier") -> bool:
        return self.endpoint(model_class) is not None

    # ---------- plain completion ----------
    def complete(self, prompt: str, system: str = "", model_class: str = "cheap",
                 max_tokens: int = 1024, cache_system: bool = True) -> Completion:
        return self.chat([{"role": "user", "content": prompt}], system=system, model_class=model_class,
                         max_tokens=max_tokens, cache_system=cache_system)

    # ---------- chat with optional tools ----------
    def chat(self, messages: list[dict], system: str = "", model_class: str = "cheap", max_tokens: int = 1024,
             tools: list[dict] | None = None, cache_system: bool = True) -> Completion:
        """messages use a provider-neutral shape:
            {"role": "user"|"assistant", "content": str}
            {"role": "assistant", "content": str, "tool_calls": [{id, name, args}]}
            {"role": "tool", "tool_call_id": id, "name": name, "content": str}
        tools: [{"name", "description", "parameters": JSON schema}]"""
        self.budgets.check(self.agent)
        ep = self.endpoint(model_class)
        if ep is None:
            raise RuntimeError(f"No model configured for the {model_class} tier: set ANTHROPIC_API_KEY, "
                               "OPENAI_API_KEY, or a GTM_*_BASE_URL for an open-weight server")
        from . import telemetry
        t0 = time.monotonic()
        try:
            if ep.provider == "anthropic":
                out = self._anthropic(ep, system, messages, max_tokens, tools, cache_system)
            else:
                out = self._openai(ep, system, messages, max_tokens, tools)
        except Exception:
            self._trace(telemetry, ep, model_class, 0, 0, 0.0, t0, "error", messages)
            raise
        out.usd = self.budgets.record(self.agent, ep.model, model_class, out.input_tokens, out.output_tokens)
        self._trace(telemetry, ep, model_class, out.input_tokens, out.output_tokens, out.usd, t0, "ok", messages, out.text)
        return out

    def _trace(self, telemetry, ep, model_class, tin, tout, usd, t0, status, messages, text="") -> None:
        try:
            prompt = "\n\n".join(str(m.get("content", ""))[:2000] for m in messages[-3:])
            telemetry.generation(self.budgets.store, self.agent, ep.model, model_class, tin, tout, usd,
                                 int((time.monotonic() - t0) * 1000), status, prompt, text)
        except Exception:  # tracing never breaks a model call
            pass

    def _anthropic(self, ep: Endpoint, system, messages, max_tokens, tools, cache_system) -> Completion:
        sys_block = [{"type": "text", "text": system,
                      **({"cache_control": {"type": "ephemeral"}} if cache_system else {})}] if system else []
        msgs: list[dict] = []
        for m in messages:
            if m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
                    msgs[-1]["content"].append(block)
                else:
                    msgs.append({"role": "user", "content": [block]})
            elif m["role"] == "assistant" and m.get("tool_calls"):
                content = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m["tool_calls"]]
                msgs.append({"role": "assistant", "content": content})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body = {"model": ep.model, "max_tokens": max_tokens, "system": sys_block, "messages": msgs}
        if tools:
            body["tools"] = [{"name": t["name"], "description": t.get("description", ""),
                              "input_schema": t.get("parameters") or {"type": "object", "properties": {}}} for t in tools]
        r = self.http.post(f"{ep.base_url}/messages", json=body,
                           headers={"x-api-key": ep.api_key, "anthropic-version": "2023-06-01",
                                    "content-type": "application/json"})
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        calls = [{"id": b["id"], "name": b["name"], "args": b.get("input") or {}}
                 for b in data.get("content", []) if b.get("type") == "tool_use"]
        u = data.get("usage") or {}
        tin = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        tout = int(u.get("output_tokens") or 0)
        if not u:
            tin, tout = _estimate(body), _estimate(text)
        return Completion(text, ep.model, tin, tout, 0.0, calls, data.get("stop_reason", ""))

    def _openai(self, ep: Endpoint, system, messages, max_tokens, tools) -> Completion:
        msgs: list[dict] = [{"role": "system", "content": system}] if system else []
        for m in messages:
            if m["role"] == "tool":
                msgs.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            elif m["role"] == "assistant" and m.get("tool_calls"):
                msgs.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": json.dumps(c["args"])}} for c in m["tool_calls"]]})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body = {"model": ep.model, "messages": msgs, "max_tokens": max_tokens}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}}}} for t in tools]
        headers = {"authorization": f"Bearer {ep.api_key}"} if ep.api_key else {}
        r = self.http.post(f"{ep.base_url}/chat/completions", headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c.get("function") or {}
            args = fn.get("arguments") or "{}"
            for _ in range(2):  # some servers double-encode the arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"_raw": args}
            if not isinstance(args, dict):
                args = {"_raw": args}
            calls.append({"id": c.get("id") or f"call_{len(calls)}", "name": fn.get("name"), "args": args})
        u = data.get("usage") or {}
        text = msg.get("content") or ""
        tin, tout = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
        if not u:  # server omitted usage: estimate so budgets still trip
            tin, tout = _estimate(body), _estimate(text) + _estimate(calls)
        return Completion(text, ep.model, tin, tout, 0.0, calls, choice.get("finish_reason", ""))


def _estimate(obj) -> int:
    """Rough token count (4 characters per token) when a server returns no usage."""
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return max(1, len(text) // 4)


def check_models(settings: Settings, budgets: Budgets, client: httpx.Client | None = None) -> dict:
    """Ping both tiers with a tiny prompt. Used by `gtm models` and selftest."""
    gw = Gateway(settings, budgets, "core", client)
    out = {}
    for tier in ("cheap", "frontier"):
        ep = gw.endpoint(tier)
        if ep is None:
            out[tier] = {"ok": False, "detail": "not configured (agents use template drafts)"}
            continue
        try:
            c = gw.chat([{"role": "user", "content": "Reply with the single word: ready"}], model_class=tier,
                        max_tokens=10)
            out[tier] = {"ok": True, "detail": ep.describe(), "reply": c.text.strip()[:40],
                         "tokens": c.input_tokens + c.output_tokens}
        except Exception as e:
            out[tier] = {"ok": False, "detail": f"{ep.describe()}: {type(e).__name__}: {str(e)[:200]}"}
    return out
