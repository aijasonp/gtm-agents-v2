import socket
import threading
import time
from contextlib import asynccontextmanager

import pytest

from gtm_core.connectors.mcp_remote import McpConfig, McpError, RemoteMCP, render


def test_render_keeps_types_and_drops_missing():
    assert render({"linkedin_url": "{linkedin}", "email": "{email}"}, {"linkedin": "https://li.example/in/ana"}) == \
        {"linkedin_url": "https://li.example/in/ana"}
    assert render({"titles": "{titles}", "q": "{a} at {b}"}, {"titles": ["VP Sales"], "a": "x", "b": "y"}) == \
        {"titles": ["VP Sales"], "q": "x at y"}


class FakeSession:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def list_tools(self):
        t = type("T", (), {"name": "find_email", "description": "Find a work email\nmore", "inputSchema": {"type": "object"}})
        return type("R", (), {"tools": [t]})()

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return type("R", (), {"isError": False, "structuredContent": self.reply, "content": []})()


def factory(session):
    @asynccontextmanager
    async def cm():
        yield session
    return cm


def test_capability_maps_args_and_results(monkeypatch, tmp_path):
    (tmp_path / "mcp.yaml").write_text("""
servers: {moltsets: {url: https://mcp.example/mcp, token_env: MOLT_T}}
capabilities:
  contact_lookup: {server: moltsets, tool: find_email, args: {linkedin_url: "{linkedin}"},
                   result: {email: data.email, phone: data.phones.0.number}}
  unmapped: {server: moltsets}
""")
    cfg = McpConfig.load(tmp_path / "mcp.yaml")
    assert "MOLT_T is not set" in cfg.ready("contact_lookup")
    monkeypatch.setenv("MOLT_T", "secret")
    assert cfg.ready("contact_lookup") is None and "set `tool`" in cfg.ready("unmapped")
    assert "not mapped" in cfg.ready("people_search")
    s = FakeSession({"data": {"email": "ana@northwind.example", "phones": [{"number": "+1 555 0100"}]}})
    out = cfg.run("contact_lookup", {"linkedin": "https://li.example/in/ana"}, factory(s))
    assert out == {"email": "ana@northwind.example", "phone": "+1 555 0100"}
    assert s.calls == [("find_email", {"linkedin_url": "https://li.example/in/ana"})]
    with pytest.raises(McpError):
        cfg.run("unmapped", {})
    assert RemoteMCP("x", "u", "t", session_factory=factory(s)).tools()[0]["description"] == "Find a work email"


def _free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def test_against_a_real_streamable_http_server():
    """End to end over HTTP with the MCP SDK on both sides, bearer token included."""
    pytest.importorskip("uvicorn")
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        pytest.skip("mcp 2.x server not available")
    import uvicorn
    srv = MCPServer("fake-moltsets")
    seen = {}

    @srv.tool(name="lookup", description="Email for a LinkedIn URL")
    def lookup(linkedin_url: str) -> dict:
        return {"email": "ana@northwind.example", "source": linkedin_url}

    app = srv.streamable_http_app()

    async def auth(scope, receive, send):
        if scope["type"] == "http":
            seen["auth"] = dict(scope["headers"]).get(b"authorization")
        await app(scope, receive, send)

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(auth, host="127.0.0.1", port=port, log_level="error", lifespan="on"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        r = RemoteMCP("fake", f"http://127.0.0.1:{port}/mcp", token="tok-1", timeout=20)
        assert [x["name"] for x in r.tools()] == ["lookup"]
        out = r.call("lookup", {"linkedin_url": "https://li.example/in/ana"})
        got = out.get("result", out)
        assert got["email"] == "ana@northwind.example" and seen["auth"] == b"Bearer tok-1"
    finally:
        server.should_exit = True
        t.join(5)
