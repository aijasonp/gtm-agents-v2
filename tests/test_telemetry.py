import json

import httpx

from gtm_core import telemetry, writer
from gtm_core.budgets import Budgets
from gtm_core.gateway import Gateway
from gtm_core.store import Store


def _llm(reply="Subject: Hi\n\nShort note.", status=200):
    def handler(request):
        if status != 200:
            return httpx.Response(status, json={"error": "down"})
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 120, "completion_tokens": 30}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_generation_spans_record_cost_not_content(settings, monkeypatch):
    monkeypatch.delenv("GTM_TRACE_CONTENT", raising=False)
    settings.offline = False
    settings.openai_base_url = "http://llm.local/v1"
    settings.model_cheap = "qwen-test"
    st = Store("sqlite:///:memory:"); st.init()
    telemetry.bind("trace-1")
    gw = Gateway(settings, Budgets(st, 0, 0), "lead-triage", client=_llm())
    assert gw.complete("Secret customer facts", model_class="cheap").text.startswith("Subject")
    sp = st.one("SELECT * FROM spans WHERE kind='generation'")
    assert (sp["trace_id"], sp["model"], sp["input_tokens"], sp["output_tokens"], sp["status"]) == \
        ("trace-1", "qwen-test", 120, 30, "ok")
    assert "Secret" not in (sp["meta"] or "")
    bad = Gateway(settings, Budgets(st, 0, 0), "lead-triage", client=_llm(status=500))
    try:
        bad.complete("x")
    except Exception:
        pass
    assert st.one("SELECT COUNT(*) AS n FROM spans WHERE status='error'")["n"] == 1


def test_draft_span_and_ae_feedback_become_examples(ctx_for):
    ctx = ctx_for("follow-through")
    facts = {"contact_name": "Ana Lopez", "company": "Northwind", "step": "check_in"}
    d = writer.write(ctx, "follow-up email", facts, "One ask.", "Subject: Next step\n\nHi Ana,\n\nIs Thursday still on?")
    did = ctx.store.add_draft("follow-through", "cadence_check_in", d.body, subject=d.subject, status="queued")
    rid = ctx.approvals.request("pipeline_email", {"contact": {"email": "ana@northwind.example"}, "subject": d.subject,
                                                   "body": d.body, "draft_id": did, "approver": "Sam Rivera"})
    ctx.store.execute("UPDATE drafts SET approval_id=? WHERE id=?", (rid, did))
    ctx.approvals.decide(rid, True, by="Sam Rivera", edits={"body": "Hi Ana,\n\nIs Thursday at 2pm still on for the pilot plan?"})
    fb = {r["name"]: r for r in ctx.store.query("SELECT * FROM feedback WHERE approval_id=?", (rid,))}
    assert fb["ae_decision"]["value"] == 1.0 and 0.3 < fb["ae_edit_similarity"]["value"] < 0.98
    assert fb["ae_edit_similarity"]["span_id"]  # linked to the draft span by its text
    ex = telemetry.examples(ctx.store, "cadence_check_in")
    assert ex[0]["facts"] == facts and "2pm" in ex[0]["approved"]["body"] and ex[0]["drafted"]["body"] == d.body
    # a rejection is a zero, with no similarity score
    did2 = ctx.store.add_draft("follow-through", "cadence_check_in", "Another", status="queued")
    rid2 = ctx.approvals.request("pipeline_email", {"contact": {"email": "b@x.example"}, "body": "Another",
                                                    "draft_id": did2, "approver": "Sam Rivera"})
    ctx.approvals.decide(rid2, False, by="Sam Rivera")
    assert [r["name"] for r in ctx.store.query("SELECT name FROM feedback WHERE approval_id=?", (rid2,))] == ["ae_decision"]
    s = telemetry.feedback_summary(ctx.store)["follow-through:cadence_check_in"]
    assert (s["approved"], s["rejected"], s["accept_rate"], s["sent_as_written"]) == (1, 1, 0.5, 0)


def test_langfuse_export_marks_only_what_was_accepted(monkeypatch):
    st = Store("sqlite:///:memory:"); st.init()
    assert "skipped" in telemetry.export_langfuse(st)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example")
    telemetry.bind("t-9")
    g1 = telemetry.generation(st, "icp-outbound", "m", "frontier", 10, 5, 0.01, 300)
    g2 = telemetry.generation(st, "icp-outbound", "m", "frontier", 10, 5, 0.01, 300)
    seen = {}

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        body = json.loads(request.content)
        seen["types"] = [e["type"] for e in body["batch"]]
        bad = next(e["id"] for e in body["batch"] if e["type"] == "generation-create" and e["body"]["id"] == g2)
        return httpx.Response(207, json={"successes": [], "errors": [{"id": bad, "status": 400}]})

    res = telemetry.export_langfuse(st, httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen["url"] == "https://langfuse.example/api/public/ingestion" and seen["auth"].startswith("Basic ")
    assert seen["types"] == ["trace-create", "generation-create", "generation-create"]
    assert res["failed"] == 1
    assert {r["id"]: r["exported"] for r in st.query("SELECT id, exported FROM spans")} == {g1: 1, g2: 0}
