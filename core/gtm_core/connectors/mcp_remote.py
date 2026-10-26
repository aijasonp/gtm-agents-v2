"""Hosted MCP servers as connectors: HubSpot, Apollo, Floqer, MoltSets, or any streamable-HTTP MCP server.

config/mcp.yaml lists each server (URL, token env var) and maps runtime capabilities to one tool on one server:

    capabilities:
      contact_lookup:                  # used by the Enrichment waterfall (provider type: mcp)
        server: moltsets
        tool: <tool name from `gtm mcp tools moltsets`>
        args: {linkedin_url: "{linkedin}"}
        result: {email: "email", phone: "mobile.number"}

Tool names differ by vendor and change between versions, so none are guessed here: run
`gtm mcp tools <server>` to see what a server offers and fill in the map during install. A capability with no
tool set is reported as not configured, never called.

Results are read from the tool's structured content, or from JSON in its text content, then picked by dotted
paths (`a.b.0.c`). These capabilities read or enrich; nothing here writes to a CRM or contacts a buyer.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import yaml

_VAR = re.compile(r"\{(\w+)\}")


class McpError(RuntimeError):
    pass


def _dig(data: Any, path: str) -> Any:
    cur = data
    for part in str(path).split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def render(template: Any, values: dict) -> Any:
    """Fill {var} placeholders; an argument whose variables are all missing is dropped (returns None)."""
    if isinstance(template, dict):
        out = {k: render(v, values) for k, v in template.items()}
        return {k: v for k, v in out.items() if v not in (None, "")}
    if isinstance(template, list):
        return [render(v, values) for v in template]
    if isinstance(template, str):
        whole = re.fullmatch(r"\{(\w+)\}", template)
        if whole:  # a bare placeholder keeps the value's own type (a list stays a list, a number a number)
            v = values.get(whole.group(1))
            return None if v in (None, "", []) else v
        names = _VAR.findall(template)
        if names and all(values.get(n) in (None, "") for n in names):
            return None
        return _VAR.sub(lambda m: str(values.get(m.group(1)) or ""), template)
    return template


def _content(result: Any) -> Any:
    """Structured content when the server returns it, else JSON parsed from the first text block."""
    sc = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if sc:
        return sc
    if isinstance(result, dict):
        return result.get("structuredContent") or result
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    return {}


class RemoteMCP:
    """One hosted MCP server over streamable HTTP, with a bearer token. Calls run synchronously."""

    def __init__(self, name: str, url: str, token: str | None = None, headers: dict | None = None,
                 timeout: float = 60, session_factory=None):
        self.name, self.url, self.timeout = name, url, timeout
        self.headers = {**(headers or {}), **({"Authorization": f"Bearer {token}"} if token else {})}
        self._factory = session_factory  # tests inject an async context manager yielding a session

    async def _with_session(self, fn):
        if self._factory is not None:
            async with self._factory() as s:
                return await fn(s)
        from mcp import ClientSession
        try:  # mcp >= 2
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
            cm = streamable_http_client(self.url, http_client=create_mcp_http_client(headers=self.headers))
        except ImportError:  # mcp 1.x
            from mcp.client.streamable_http import streamablehttp_client
            cm = streamablehttp_client(self.url, headers=self.headers)
        async with cm as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                return await fn(s)

    def _run(self, fn):
        import anyio
        box: dict = {}

        def go():
            try:
                box["v"] = anyio.run(self._with_session, fn)
            except BaseException as e:  # surfaced below with the server name
                box["e"] = e
        t = threading.Thread(target=go, daemon=True)  # a fresh event loop, safe inside async callers too
        t.start()
        t.join(self.timeout)
        if t.is_alive():
            raise McpError(f"{self.name}: no answer within {self.timeout:.0f}s")
        if "e" in box:
            raise McpError(f"{self.name}: {box['e']}") from box["e"]
        return box.get("v")

    def tools(self) -> list[dict]:
        async def fn(s):
            res = await s.list_tools()
            return [{"name": t.name, "description": (t.description or "").strip().splitlines()[0] if t.description else "",
                     "input_schema": getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)}
                    for t in res.tools]
        return self._run(fn)

    def call(self, tool: str, args: dict) -> Any:
        async def fn(s):
            res = await s.call_tool(tool, args)
            if getattr(res, "isError", False) or getattr(res, "is_error", False):
                raise McpError(f"{self.name}.{tool} returned an error: {_content(res)}")
            return _content(res)
        return self._run(fn)


class McpConfig:
    def __init__(self, data: dict):
        self.servers = data.get("servers") or {}
        self.capabilities = data.get("capabilities") or {}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "McpConfig":
        p = Path(path or Path(os.environ.get("GTM_CONFIG_DIR", "config")) / "mcp.yaml")
        try:
            return cls(yaml.safe_load(p.read_text()) or {})
        except FileNotFoundError:
            return cls({})

    def server(self, name: str, factory=None) -> RemoteMCP:
        s = self.servers.get(name)
        if not s:
            raise McpError(f"server {name!r} is not in config/mcp.yaml")
        url = os.environ.get(s.get("url_env", ""), "") or s.get("url")
        if not url:
            raise McpError(f"server {name}: set {s.get('url_env') or 'url'}")
        token = os.environ.get(s.get("token_env", ""), "") or None
        return RemoteMCP(name, url, token, s.get("headers"), float(s.get("timeout", 60)), factory)

    def ready(self, capability: str) -> str | None:
        """None when the capability can run, else why not."""
        c = self.capabilities.get(capability)
        if not c:
            return f"capability {capability!r} is not mapped in config/mcp.yaml"
        if not c.get("tool"):
            return f"{capability}: set `tool` (run `gtm mcp tools {c.get('server')}` to list them)"
        s = self.servers.get(c.get("server") or "")
        if not s:
            return f"{capability}: server {c.get('server')!r} is not defined"
        if s.get("token_env") and not os.environ.get(s["token_env"]):
            return f"{capability}: {s['token_env']} is not set"
        if not (s.get("url") or os.environ.get(s.get("url_env", ""), "")):
            return f"{capability}: no URL for server {c.get('server')}"
        return None

    def run(self, capability: str, values: dict, factory=None) -> dict:
        """Call the mapped tool with rendered args; returns {field: value} from the result map (raw when unmapped)."""
        why = self.ready(capability)
        if why:
            raise McpError(why)
        c = self.capabilities[capability]
        data = self.server(c["server"], factory).call(c["tool"], render(c.get("args") or {}, values) or {})
        if not c.get("result"):
            return data if isinstance(data, dict) else {"result": data}
        return {k: v for k, path in c["result"].items() if (v := _dig(data, path)) not in (None, "", [])}
