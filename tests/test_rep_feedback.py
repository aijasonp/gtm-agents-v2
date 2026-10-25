import base64
import json

import httpx
import pytest

from gtm_core.agents import load_module
from gtm_core.mcp_server import bind_tools


def test_feedback_to_pr(ctx_for, monkeypatch):
    ctx = ctx_for("rep-feedback")
    t = bind_tools(ctx)
    a = t["submit_feedback"](agent="icp-outbound", text="Bumps read like templates", rep="Sam Rivera")
    b = t["submit_feedback"](agent="icp-outbound", text="Breakup emails are too long")
    assert a["target"] == "agents/icp-outbound/skill/SKILL.md"
    assert t["list_feedback"]()["count"] == 2
    p = t["propose_change"](feedback_ids=[a["feedback_id"], b["feedback_id"]])
    assert p["rules"] == ["Bumps read like templates", "Breakup emails are too long"]
    q = t["open_pr"](proposal_id=p["proposal_id"])
    assert t["open_pr"](proposal_id=p["proposal_id"])["error"] == "proposal is queued"

    calls = []
    remote = "# ICP Outbound\n\n## Rules\n\n- Existing rule.\n"

    def h(req):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        path = req.url.path
        if path == "/repos/acme/gtm":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "abc"}})
        if path.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if path.endswith("/contents/agents/icp-outbound/skill/SKILL.md") and req.method == "GET":
            return httpx.Response(200, json={"content": base64.b64encode(remote.encode()).decode(), "sha": "f1"})
        if req.method == "PUT":
            return httpx.Response(200, json={})
        if path.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.example/acme/gtm/pull/7", "number": 7})
        return httpx.Response(404)
    eng = load_module(ctx.manifest, "engine")
    monkeypatch.setattr(eng, "HTTP_CLIENT", httpx.Client(transport=httpx.MockTransport(h)))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GTM_FEEDBACK_REPO", "acme/gtm")
    load_module(ctx.manifest, "jobs").register_executors(ctx)
    # the executor uses load_module too; make sure it sees the patched client
    monkeypatch.setattr(load_module(ctx.manifest, "engine"), "HTTP_CLIENT", eng.HTTP_CLIENT)
    ctx.approvals.decide(q["queued_for_approval"], True)
    res = ctx.approvals.execute_one(q["queued_for_approval"])
    put = next(c for c in calls if c[0] == "PUT")
    content = base64.b64decode(put[2]["content"]).decode()
    assert content == "# ICP Outbound\n\n## Rules\n\n- Existing rule.\n- Bumps read like templates\n- Breakup emails are too long\n"
    assert put[2]["branch"] == f"rep-feedback/{p['proposal_id']}" and put[2]["sha"] == "f1"
    assert t["list_feedback"](status="pr_opened")["count"] == 2
    assert res is not None
    d = load_module(ctx.manifest, "jobs").weekly_feedback_digest(ctx)
    assert d["by_status"] == {"pr_opened": 2}


def test_refusals(ctx_for, monkeypatch):
    ctx = ctx_for("rep-feedback")
    eng = load_module(ctx.manifest, "engine")
    assert eng.submit(ctx, "../library", "x")["error"]
    with pytest.raises(ValueError):
        eng.github_pr(ctx, {"target": "library/x/SKILL.md", "rules": [], "branch": "b", "title": "t", "body": "",
                            "proposal_id": "p"}, "tok", "acme/gtm")
    with pytest.raises(ValueError):
        eng.github_pr(ctx, {"target": "config/icp.yaml"}, None, None)
