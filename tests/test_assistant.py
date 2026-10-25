"""Assistant tool loop on both provider shapes, with fake model servers."""
import json

import httpx

from gtm_core.assistant import Assistant, handle_message
from gtm_core.gateway import Gateway, resolve
from gtm_core.store import Store


def _assistant(settings, manifests, handler, provider="anthropic", monkeypatch=None):
    settings.offline = False
    if provider == "anthropic":
        settings.anthropic_api_key, settings.model_frontier = "k", "claude-sonnet-5-5"
    else:
        settings.anthropic_api_key, settings.model_frontier = None, "qwen3-32b"
        monkeypatch.setenv("GTM_FRONTIER_BASE_URL", "http://vllm.internal:8000/v1")
    st = Store("sqlite:///:memory:"); st.init()
    st.upsert_account({"id": "proseware.example", "name": "Proseware", "domain": "proseware.example",
                       "industry": "Software", "employees": 350, "country": "US"})
    ms = {k: manifests[k] for k in ("signal-scout", "lead-triage", "copy-qa-gate")}
    a = Assistant(settings, store=st, manifests=ms)
    a.gateway = Gateway(settings, next(iter(a.ctxs.values())).budgets, "core",
                        client=httpx.Client(transport=httpx.MockTransport(handler)))
    return a


def test_anthropic_tool_loop(settings, manifests):
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        if len(calls) == 1:
            assert any(t["name"] == "signal_scout__score_account" for t in body["tools"])
            return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t1", "name": "signal_scout__score_account",
                                                          "input": {"account": "proseware.example"}}],
                                             "stop_reason": "tool_use", "usage": {"input_tokens": 50, "output_tokens": 10}})
        tool_result = body["messages"][-1]["content"][0]
        assert tool_result["type"] == "tool_result" and "Proseware" in tool_result["content"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Proseware is tier C."}],
                                         "usage": {"input_tokens": 80, "output_tokens": 8}})
    a = _assistant(settings, manifests, handler)
    ans = a.ask("How is Proseware scoring?")
    assert ans.text == "Proseware is tier C." and ans.trace[0]["tool"] == "signal_scout__score_account"


def test_openai_compatible_open_weight_loop(settings, manifests, monkeypatch):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        body = json.loads(req.content)
        if len(seen) == 1:
            assert "authorization" not in {k.lower() for k in req.headers}  # local server, no key
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "copy_qa_gate__check_copy",
                                                              "arguments": json.dumps({"text": "Worth 15 minutes Tuesday?"})}}]},
                "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 40, "completion_tokens": 9}})
        assert body["messages"][-1]["role"] == "tool"
        return httpx.Response(200, json={"choices": [{"message": {"content": "It passes."}}],
                                         "usage": {"prompt_tokens": 60, "completion_tokens": 3}})
    a = _assistant(settings, manifests, handler, provider="openai", monkeypatch=monkeypatch)
    assert resolve(settings, "frontier").provider == "openai"
    ans = a.ask("check this copy")
    assert ans.text == "It passes." and seen[0].startswith("http://vllm.internal:8000/v1/chat/completions")


def test_slack_approve_needs_allowlist(settings, manifests, monkeypatch):
    a = _assistant(settings, manifests, lambda r: httpx.Response(500))
    rid = a.ctxs["lead-triage"].approvals.request("crm_task", {"subject": "x"})
    assert "Only approvers" in handle_message(a, f"approve {rid}", "U1", [])
    monkeypatch.setenv("GTM_SLACK_APPROVERS", "U1")
    assert f"#{rid} approved" in handle_message(a, f"approve #{rid}", "U1", [])


def test_no_model_is_explained(settings, manifests):
    settings.offline = True
    st = Store("sqlite:///:memory:"); st.init()
    a = Assistant(settings, store=st, manifests={"copy-qa-gate": manifests["copy-qa-gate"]})
    assert "No model is configured" in a.ask("hi").text


def test_schema_unions_and_bad_args(settings, manifests):
    from gtm_core.assistant import _schema_for

    def f(ctx, names: list[str] | None = None, n: int = 3):
        """x"""
    sch = _schema_for(f)
    assert sch["properties"]["names"]["type"] == "array" and sch["properties"]["n"]["type"] == "integer"
    st = Store("sqlite:///:memory:"); st.init()
    a = Assistant(settings, store=st, manifests={"copy-qa-gate": manifests["copy-qa-gate"]})
    assert "JSON object" in a.call_tool("copy_qa_gate__check_copy", ["not", "a", "dict"])
    assert "passed" in a.call_tool("copy_qa_gate__check_copy", '{"text": "Worth 15 minutes Tuesday?"}')


def test_gateway_keys_and_usage(settings, monkeypatch):
    from gtm_core.budgets import Budgets
    settings.offline, settings.openai_api_key, settings.model_cheap = False, "sk-openai", "qwen3"
    monkeypatch.setenv("GTM_CHEAP_BASE_URL", "http://local:8000/v1")
    seen = []

    def handler(req):
        seen.append(req.headers.get("authorization"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "t", "arguments": json.dumps(json.dumps({"x": 1}))}}]}}],
            "usage": {"prompt_tokens": None, "completion_tokens": None}})
    st = Store("sqlite:///:memory:"); st.init()
    gw = Gateway(settings, Budgets(st, agent="core"), client=httpx.Client(transport=httpx.MockTransport(handler)))
    c = gw.chat([{"role": "user", "content": "hi"}], model_class="cheap")
    assert seen == [None]                      # OpenAI key never sent to a tier-specific server
    assert c.tool_calls[0]["args"] == {"x": 1}  # double-encoded args decoded
    assert c.input_tokens == 0                  # null usage handled
