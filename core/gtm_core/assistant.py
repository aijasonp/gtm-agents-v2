"""The GTM assistant: one chat interface over every installed agent's tools.

This is what replaces a hosted agent shell. Ask in plain words, from the terminal (`gtm ask`,
`gtm assistant`) or Slack (`gtm slack-bot`); the model picks tools across all agents, the tools
compute from the customer's database, and anything that writes is queued for approval.

Works on Claude, OpenAI or any open-weight model with tool calling served behind an
OpenAI-compatible endpoint (vLLM, Ollama, Together, Fireworks, OpenRouter...). Pick the tier with
GTM_ASSISTANT_TIER (cheap | frontier). With many agents installed, smaller open-weight models do
better with fewer tools: limit them with GTM_ASSISTANT_AGENTS=lead-triage,rep-brief,...
"""
from __future__ import annotations

import inspect
import json
import os
import re
import typing
from dataclasses import dataclass, field

from .agents import Context, Manifest, discover
from .config import Settings
from .guardrails import StepCounter
from .store import Store

SYSTEM = """You are the GTM assistant for a sales and marketing team. You answer with data from tools, never from memory.

Rules:
- Use tools for every number, score, list, deal, account or draft. If no tool covers it, say so.
- Tools that write (CRM, sequences, dialer, notes, tasks) only queue a request for human approval. Say "queued for approval #N". Never say anything was sent or updated.
- Be brief: a few lines or a short list. Plain words, no em dashes, no filler.
- When a tool returns an error, say what is missing and how to fix it in one line.
- Never invent names, emails, numbers, customers or quotes."""

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


def _schema_for(fn) -> dict:
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    props, required = {}, []
    for name, p in sig.parameters.items():
        if name == "ctx" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        t = hints.get(name, str)
        origin = typing.get_origin(t)
        import types as _types
        if origin is typing.Union or origin is getattr(_types, "UnionType", None):
            args = [a for a in typing.get_args(t) if a is not type(None)]
            t = args[0] if args else str
            origin = typing.get_origin(t)
        jt = _PY_TO_JSON.get(origin or t, "string")
        prop = {"type": jt}
        if jt == "array":
            prop["items"] = {"type": "string"}
        props[name] = prop
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def _desc(fn) -> str:
    return " ".join((fn.__doc__ or "").split())[:900]


@dataclass
class Tool:
    name: str        # "<agent>__<tool>" with dashes as underscores
    agent: str
    fn: typing.Callable
    schema: dict
    description: str


@dataclass
class Answer:
    text: str
    trace: list[dict] = field(default_factory=list)
    usd: float = 0.0


class Assistant:
    def __init__(self, settings: Settings, store: Store | None = None, agents: list[str] | None = None,
                 manifests: dict[str, Manifest] | None = None, gateway=None):
        self.s = settings
        self.store = store or Store(settings.database_url)
        self.store.init()
        ms = manifests or discover(settings.agents_dir)
        wanted = agents or [a.strip() for a in os.environ.get("GTM_ASSISTANT_AGENTS", "").split(",") if a.strip()]
        self.manifests = {k: v for k, v in ms.items() if not wanted or k in wanted}
        self.tier = os.environ.get("GTM_ASSISTANT_TIER", "frontier")
        self.tools: dict[str, Tool] = {}
        self.ctxs: dict[str, Context] = {}
        from .mcp_server import bind_tools
        for m in self.manifests.values():
            ctx = Context.build(settings, m, store=self.store)
            self.ctxs[m.id] = ctx
            for tname, fn in bind_tools(ctx).items():
                name = re.sub(r"[^a-zA-Z0-9_]", "_", f"{m.id}__{tname}")[:64]
                self.tools[name] = Tool(name, m.id, fn, _schema_for(fn), f"[{m.name}] {_desc(fn)}")
        core = next(iter(self.ctxs.values()), None)
        self.gateway = gateway or (core.gateway if core else None)

    def tool_specs(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "parameters": t.schema} for t in self.tools.values()]

    def call_tool(self, name: str, args: dict) -> str:
        t = self.tools.get(name)
        if t is None:
            return json.dumps({"error": f"unknown tool {name}"})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return json.dumps({"error": "arguments must be a JSON object"})
        if not isinstance(args, dict):
            return json.dumps({"error": "arguments must be a JSON object"})
        allowed = set(t.schema["properties"])
        clean = {k: v for k, v in args.items() if k in allowed}
        missing = [r for r in t.schema["required"] if r not in clean]
        if missing:
            return json.dumps({"error": f"missing arguments: {', '.join(missing)}"})
        try:
            out = t.fn(**clean)
        except Exception as e:  # the model sees the error and can recover
            return json.dumps({"error": f"{type(e).__name__}: {str(e)[:300]}"})
        text = json.dumps(out, default=str)
        limit = int(os.environ.get("GTM_ASSISTANT_TOOL_CHARS", 8000))
        return text if len(text) <= limit else text[:limit] + '..."(truncated)"'

    def ask(self, question: str, history: list[dict] | None = None, max_steps: int = 8) -> Answer:
        if self.gateway is None or not self.gateway.available(self.tier):
            return Answer("No model is configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY or GTM_FRONTIER_BASE_URL "
                          "(open-weight server), then run `gtm models`.")
        messages = list(history or []) + [{"role": "user", "content": question}]
        trace, usd = [], 0.0
        specs = self.tool_specs()
        with StepCounter(limit=max_steps) as steps:
            while True:
                steps.tick("assistant")
                c = self.gateway.chat(messages, system=SYSTEM, model_class=self.tier, max_tokens=1500, tools=specs)
                usd += c.usd
                if not c.tool_calls:
                    return Answer(c.text.strip(), trace, usd)
                messages.append({"role": "assistant", "content": c.text, "tool_calls": c.tool_calls})
                for call in c.tool_calls:
                    result = self.call_tool(call["name"], call.get("args") or {})
                    trace.append({"tool": call["name"], "args": call.get("args"), "result": result[:300]})
                    messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result})


# ---------------- Slack bot (Socket Mode: no public URL needed) ----------------
APPROVE_RE = re.compile(r"^\s*(approve|reject)\s+#?(\d+(?:\s*[, ]\s*\d+)*)\s*$", re.I)


def handle_message(assistant: Assistant, text: str, user: str, history: list[dict]) -> str:
    """Slack message -> reply. `approve 12` / `reject 12, 13` are handled without a model and only for
    users listed in GTM_SLACK_APPROVERS."""
    from .approvals import Approvals
    m = APPROVE_RE.match(text or "")
    if m:
        approvers = {u.strip() for u in os.environ.get("GTM_SLACK_APPROVERS", "").split(",") if u.strip()}
        if user not in approvers:
            return "Only approvers can do that. Ask an admin to add your Slack ID to GTM_SLACK_APPROVERS."
        ids = [int(x) for x in re.findall(r"\d+", m.group(2))]
        out = []
        for rid in ids:
            try:
                Approvals(assistant.store, "core").decide(rid, m.group(1).lower() == "approve", by=f"slack:{user}")
                out.append(f"#{rid} {m.group(1).lower()}d")
            except (KeyError, ValueError) as e:
                out.append(f"#{rid}: {e}")
        return "; ".join(out) + ". Approved actions run on the next `gtm approvals ... execute` or scheduled run."
    return assistant.ask(text, history).text or "(no answer)"


def run_slack_bot(settings: Settings) -> None:  # pragma: no cover - needs a live Slack workspace
    try:
        from slack_sdk import WebClient
        from slack_sdk.socket_mode import SocketModeClient
        from slack_sdk.socket_mode.request import SocketModeRequest
        from slack_sdk.socket_mode.response import SocketModeResponse
    except ImportError:
        raise SystemExit("pip install 'gtm-agents[slack]' (slack_sdk) to run the Slack bot")
    app_token, bot_token = os.environ.get("SLACK_APP_TOKEN"), settings.slack_bot_token
    if not app_token or not bot_token:
        raise SystemExit("set SLACK_APP_TOKEN (xapp-, Socket Mode) and SLACK_BOT_TOKEN (xoxb-)")
    allowed = {u.strip() for u in os.environ.get("GTM_SLACK_ALLOWED_USERS", "").split(",") if u.strip()}
    allow_all = os.environ.get("GTM_SLACK_ALLOW_ALL") == "1"
    if not allowed and not allow_all:
        raise SystemExit("set GTM_SLACK_ALLOWED_USERS (Slack user IDs), or GTM_SLACK_ALLOW_ALL=1 for every workspace member")
    assistant = Assistant(settings)
    web = WebClient(token=bot_token)
    client = SocketModeClient(app_token=app_token, web_client=web)
    auth = web.auth_test()
    bot_id, team_id = auth["user_id"], auth.get("team_id")

    def on_event(c: SocketModeClient, req: SocketModeRequest):
        if req.type != "events_api":
            return
        c.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        ev = req.payload.get("event", {})
        if ev.get("bot_id") or ev.get("subtype") or ev.get("type") not in ("app_mention", "message"):
            return
        if ev.get("type") == "message" and ev.get("channel_type") != "im":
            return
        user = ev.get("user", "")
        if ev.get("user_team") and team_id and ev["user_team"] != team_id:
            return  # Slack Connect: people from other companies never reach the agents
        if not allow_all and user not in allowed:
            return
        text = re.sub(rf"<@{bot_id}>", "", ev.get("text", "")).strip()
        thread = ev.get("thread_ts") or ev.get("ts")
        key = f"slack_thread:{ev.get('channel')}:{thread}"
        history = assistant.store.get_state(key, [])[-10:]
        try:
            reply = handle_message(assistant, text, user, history)
        except Exception as e:
            reply = f"Something failed: {type(e).__name__}. Check `gtm selftest`."
        if reply.strip():
            assistant.store.set_state(key, (history + [{"role": "user", "content": text},
                                                       {"role": "assistant", "content": reply}])[-20:])
        web.chat_postMessage(channel=ev["channel"], thread_ts=thread, text=reply)

    client.socket_mode_request_listeners.append(on_event)
    client.connect()
    print(f"slack bot connected with {len(assistant.tools)} tools from {len(assistant.manifests)} agents")
    import threading
    threading.Event().wait()
