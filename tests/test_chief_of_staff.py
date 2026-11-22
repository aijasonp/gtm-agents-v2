"""Chief of staff: routes each request to one to three agents, so only their tools and skills reach the model."""
import json

import httpx

from gtm_core.assistant import Assistant, handle_message
from gtm_core.chief_of_staff import ChiefOfStaff, Step
from gtm_core.gateway import Gateway
from gtm_core.store import Store


def _cos(settings, manifests, handler=None):
    st = Store("sqlite:///:memory:"); st.init()
    if handler is None:
        return ChiefOfStaff(settings, store=st, manifests=manifests)
    settings.offline = False
    settings.anthropic_api_key, settings.model_frontier, settings.model_cheap = "k", "claude-sonnet-5-5", "claude-haiku-5-5"
    a = Assistant(settings, store=st, manifests=manifests)
    a.gateway = Gateway(settings, next(iter(a.ctxs.values())).budgets, "core",
                        client=httpx.Client(transport=httpx.MockTransport(handler)))
    return ChiefOfStaff(settings, assistant=a)


def _text(t):
    return httpx.Response(200, json={"content": [{"type": "text", "text": t}], "usage": {"input_tokens": 9, "output_tokens": 3}})


def test_keywords_route_without_a_model(settings, manifests):
    c = _cos(settings, manifests)
    p = c.route("why are we losing deals and what are our loss reasons this year")
    assert p.method == "keywords" and p.steps[0].agents == ["opportunity-analyst"]
    p = c.route("give me the CEO exec brief")
    assert p.steps[0].agents == ["exec-brief"]
    assert c.route("prep me for the Contoso call").steps[0].agents == ["sales-execution"]


def test_catalog_lists_agents_not_tools(settings, manifests):
    c = _cos(settings, manifests)
    cat = c.catalog()
    assert all(f"- {a}:" in cat for a in manifests)
    assert "find_opportunities" not in cat and "win_loss(" not in cat
    assert len(cat) < len(json.dumps(c.a.tool_specs())) / 4


def test_step_sends_only_the_routed_agents_tools(settings, manifests):
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if len(bodies) == 1:  # the step: tools loaded, then answer
            return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t1",
                                                          "name": "opportunity_analyst__win_loss", "input": {}}],
                                             "stop_reason": "tool_use", "usage": {"input_tokens": 50, "output_tokens": 9}})
        return _text("Win rate is 50%.")

    c = _cos(settings, manifests, handler)
    ans = c.ask("what is our win rate by loss reason")
    tools = {t["name"] for t in bodies[0]["tools"]}
    assert tools and all(t.startswith("opportunity_analyst__") for t in tools)
    assert len(tools) == len(manifests["opportunity-analyst"].tools) < len(c.a.tools) / 10
    assert "Skill: Opportunity Analyst" in json.dumps(bodies[0]["system"])
    assert ans.text.startswith("Win rate is 50%.") and "via Opportunity Analyst, 8 tools loaded" in ans.text
    assert ans.trace[0]["route"] == ["opportunity-analyst"]


def test_model_routes_ambiguous_requests_with_catalog_only(settings, manifests):
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if len(bodies) == 1:
            assert "tools" not in body  # the router never sees tool definitions
            assert "- opportunity-analyst:" in json.dumps(body["system"])
            return _text('{"steps": [{"agents": ["opportunity-analyst"], "task": "List lost deals over $50k"},'
                         ' {"agents": ["product-marketing", "not-an-agent"], "task": "Battlecard for who beat us"}]}')
        return _text(f"answer {len(bodies)}")

    c = _cos(settings, manifests, handler)
    ans = c.ask("tell me about the big ones that got away and how to fight back")
    routes = [t["route"] for t in ans.trace if "route" in t]
    assert routes == [["opportunity-analyst"], ["product-marketing"]]
    step2_tools = {t["name"] for t in bodies[2]["tools"]}
    assert all(t.startswith("product_marketing__") for t in step2_tools)
    assert "answer 2" in json.dumps(bodies[2]["system"])  # step 2 sees step 1's result
    assert "*Opportunity Analyst*" in ans.text and "*Product Marketing*" in ans.text


def test_router_can_ask_a_clarifying_question(settings, manifests):
    c = _cos(settings, manifests, lambda r: _text('{"reply": "Which quarter do you mean?"}'))
    assert c.ask("how did we do").text == "Which quarter do you mean?"


def test_tool_outside_the_route_is_never_run(settings, manifests):
    c = _cos(settings, manifests)
    out = json.loads(c.a.call_tool("crm_hygiene__find_duplicate_accounts", {}, agents=["opportunity-analyst"]))
    assert "unknown tool" in out["error"]


def test_oversized_step_is_split(settings, manifests):
    c = _cos(settings, manifests)
    c.max_tools = 10
    steps = c._fit(Step(["opportunity-analyst", "signal-sourcing"], "x"))
    assert [s.agents for s in steps] == [["opportunity-analyst"], ["signal-sourcing"]]


def test_follow_up_sticks_to_last_route_without_a_model(settings, manifests):
    c = _cos(settings, manifests)
    p = c.route("and for last quarter?", last_route=["opportunity-analyst"])
    assert p.method == "sticky" and p.steps[0].agents == ["opportunity-analyst"]
    assert "pipeline" in c.route("hello").reply


def test_slack_route_command_and_commands_still_instant(settings, manifests):
    c = _cos(settings, manifests)
    out = handle_message(c, "route pull every closed lost opportunity", "U1", [])
    assert "opportunity-analyst (8 tools)" in out
    assert "Commands" in handle_message(c, "help", "U1", [])
