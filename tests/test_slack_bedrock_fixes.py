"""Bedrock gateway, Slack commands without a model, and owner DMs."""
import json

import pytest

from gtm_core import autonomy, slack_commands
from gtm_core.budgets import Budgets
from gtm_core.connectors.slack import owner_slack_id, send_to_owner
from gtm_core.gateway import Gateway, resolve
from gtm_core.store import Store


class FakeBedrock:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def converse(self, **req):
        self.calls.append(req)
        return self.replies.pop(0)


def test_bedrock_resolves_without_a_key(settings, monkeypatch):
    settings.offline = False
    monkeypatch.setenv("GTM_FRONTIER_PROVIDER", "bedrock")
    monkeypatch.setenv("GTM_BEDROCK_REGION", "us-west-2")
    ep = resolve(settings, "frontier")
    assert ep.provider == "bedrock" and ep.base_url == "us-west-2" and ep.api_key is None
    assert "bedrock us-west-2" in ep.describe()


def test_bedrock_tool_loop_and_usage(settings, monkeypatch):
    settings.offline = False
    monkeypatch.setenv("GTM_FRONTIER_PROVIDER", "bedrock")
    store = Store("sqlite:///:memory:")
    store.init()
    fake = FakeBedrock([
        {"output": {"message": {"content": [{"text": "Checking."},
                                            {"toolUse": {"toolUseId": "t1", "name": "deal__inspect", "input": {"deal": "d1"}}}]}},
         "usage": {"inputTokens": 120, "outputTokens": 30}, "stopReason": "tool_use"},
        {"output": {"message": {"content": [{"text": "Deal d1 is stalled 41 days."}]}},
         "usage": {"inputTokens": 200, "outputTokens": 12}, "stopReason": "end_turn"}])
    gw = Gateway(settings, Budgets(store, agent="t"), "t", bedrock_client=fake)
    tools = [{"name": "deal__inspect", "description": "Inspect a deal", "parameters": {"type": "object", "properties": {"deal": {"type": "string"}}}}]
    c1 = gw.chat([{"role": "user", "content": "how is d1?"}], system="be brief", model_class="frontier", tools=tools)
    assert c1.tool_calls == [{"id": "t1", "name": "deal__inspect", "args": {"deal": "d1"}}] and c1.input_tokens == 120
    req = fake.calls[0]
    assert req["system"] == [{"text": "be brief"}] and req["toolConfig"]["tools"][0]["toolSpec"]["name"] == "deal__inspect"
    msgs = [{"role": "user", "content": "how is d1?"},
            {"role": "assistant", "content": c1.text, "tool_calls": c1.tool_calls},
            {"role": "tool", "tool_call_id": "t1", "name": "deal__inspect", "content": json.dumps({"days": 41})}]
    c2 = gw.chat(msgs, model_class="frontier", tools=tools)
    assert c2.text.startswith("Deal d1") and c2.tool_calls == []
    sent = fake.calls[1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[2]["content"][0]["toolResult"]["toolUseId"] == "t1"
    assert store.one("SELECT SUM(input_tokens) AS n FROM token_usage")["n"] == 320


@pytest.fixture
def store():
    s = Store("sqlite:///:memory:")
    s.init()
    return s


def test_commands_need_no_model_and_respect_roles(store, monkeypatch, tmp_path):
    monkeypatch.setenv("GTM_ROOT", str(tmp_path))
    monkeypatch.setenv("GTM_SLACK_APPROVERS", "UAPP")
    monkeypatch.delenv("GTM_SLACK_ADMINS", raising=False)
    monkeypatch.delenv("GTM_STOP", raising=False)
    assert slack_commands.handle("what is stalled for Sam?", "U1", store) is None
    assert slack_commands.handle("run the numbers for me", "U1", store) is None   # not "run <agent> <job>"
    assert "Commands" in slack_commands.handle("help", "U1", store)
    assert "STOP: off" in slack_commands.handle("status", "U1", store)
    out = slack_commands.handle("stop cold -- bounce spike", "U1", store)
    assert "STOP is on for cold" in out
    assert "on for cold" in slack_commands.handle("status", "U1", store)
    assert "Only admins" in slack_commands.handle("resume", "U1", store)
    assert "Resumed" in slack_commands.handle("resume", "UAPP", store)
    rid = store.insert("INSERT INTO approvals (agent, action, payload, status, requested_at) VALUES (?,?,?,?,?)",
                       ("icp-outbound", "sequence_enroll", json.dumps({"contact": {"email": "a@b.example"}}), "pending", "2026-10-29"))
    lst = slack_commands.handle("approvals", "U1", store)
    assert f"#{rid} icp-outbound: sequence_enroll (a@b.example)" in lst
    assert "Only approvers" in slack_commands.handle(f"approve {rid}", "U1", store)


def test_run_command(store, monkeypatch, manifests):
    monkeypatch.setenv("GTM_SLACK_ADMINS", "UADM")
    calls = []

    def runner(settings, m, job):
        calls.append((m.id, job))
        return {"scanned": 3, "stored": 2}
    assert "Only admins" in slack_commands.handle("run signal-sourcing daily_scan", "U1", store, None, manifests, runner)
    out = slack_commands.handle("run signal-sourcing daily_scan", "UADM", store, None, manifests, runner)
    assert out == "signal-sourcing.daily_scan done: scanned 3, stored 2" and calls == [("signal-sourcing", "daily_scan")]
    assert "no job" in slack_commands.handle("run signal-sourcing nope", "UADM", store, None, manifests, runner)
    assert "No agent" in slack_commands.handle("run ghost job", "UADM", store, None, manifests, runner)


def test_briefs_go_to_owner_dm(ctx_for, monkeypatch):
    ctx = ctx_for("rep-brief")
    sent = []
    ctx.slack.post = lambda text, blocks=None, channel=None: sent.append(channel) or {"ok": True}
    ctx.slack.lookup_user_id = lambda email: "ULOOK" if email == "priya@beacon.example" else None
    assert owner_slack_id(ctx, "Priya Shah") == "ULOOK" and ctx.store.get_state("slack_id:priya@beacon.example") == "ULOOK"
    send_to_owner(ctx, "Priya Shah", "hi")
    send_to_owner(ctx, "Sam Rivera", "hi")          # no id, no lookup: team channel
    assert sent == ["ULOOK", None]
    monkeypatch.setenv("GTM_SLACK_DM", "0")
    send_to_owner(ctx, "Priya Shah", "hi")
    assert sent[-1] is None
