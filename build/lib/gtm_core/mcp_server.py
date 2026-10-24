"""MCP server exposing an agent's deterministic tools to Claude, ChatGPT or any MCP client.

Each agent's tools.py defines TOOLS = {name: fn(ctx, **kwargs) -> dict}. Only the tool
names listed in agent.yaml are exposed. Tools that write go through the approval queue.
"""
from __future__ import annotations

import functools
import inspect
import json

from .agents import Context, Manifest, load_module
from .config import Settings


def _server_class():
    try:  # mcp >= 2
        from mcp.server.mcpserver import MCPServer
        return MCPServer
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP
        return FastMCP


def bind_tools(ctx: Context) -> dict:
    mod = load_module(ctx.manifest, "tools")
    if mod is None:
        return {}
    available = getattr(mod, "TOOLS", {})
    missing = [t for t in ctx.manifest.tools if t not in available]
    if missing:
        raise KeyError(f"{ctx.manifest.id}: tools listed in agent.yaml but not defined: {missing}")
    bound = {}
    for name in ctx.manifest.tools:
        fn = available[name]
        sig = inspect.signature(fn)
        params = [p for p in sig.parameters.values() if p.name != "ctx"]

        @functools.wraps(fn)
        def wrapper(*args, __fn=fn, **kwargs):
            ctx.audit.log("tool.call", tool=__fn.__name__, args=kwargs)
            return __fn(ctx, *args, **kwargs)

        wrapper.__signature__ = sig.replace(parameters=params)
        bound[name] = wrapper
    return bound


def serve(settings: Settings, m: Manifest, transport: str = "stdio") -> None:  # pragma: no cover
    ctx = Context.build(settings, m)
    server = _server_class()(m.name, instructions=m.description or None)
    for name, fn in bind_tools(ctx).items():
        server.tool(name=name, description=(fn.__doc__ or "").strip())(fn)
    server.run(transport=transport)


def describe(settings: Settings, m: Manifest) -> str:
    ctx = Context.build(settings, m)
    return json.dumps({n: (f.__doc__ or "").strip().splitlines()[0] for n, f in bind_tools(ctx).items()}, indent=2)
