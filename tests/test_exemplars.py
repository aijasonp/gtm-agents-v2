import json

from gtm_core import exemplars, telemetry, writer

KIND = "follow-up email"


def body(name, ask, extra=""):
    return (f"Hi {name},\n\nThanks for the time on Tuesday. You said the pilot needs sign off from finance by the 30th."
            f"{extra} I can send the two page summary for that review. {ask}\n\nSam")


def approve(ctx, facts, drafted, sent, kind=KIND, subject="Pilot summary"):
    """One drafted send, linked to its span, approved by the owner with `sent` as the final body."""
    telemetry.draft_span(ctx.store, "follow-through", kind, facts, "One ask.", subject, drafted, 40, True, "model", 1)
    did = ctx.store.add_draft("follow-through", "cadence_check_in", drafted, subject=subject, status="queued")
    rid = ctx.approvals.request("pipeline_email", {"contact": {"email": "x@northwind.example"}, "subject": subject,
                                                   "body": drafted, "draft_id": did, "approver": "Sam Rivera"})
    ctx.store.execute("UPDATE drafts SET approval_id=? WHERE id=?", (rid, did))
    ctx.approvals.decide(rid, True, by="Sam Rivera", edits=None if sent == drafted else {"body": sent})


def seed(ctx):
    rows = [({"title": "VP Sales", "industry": "Software"}, "Ana", "Want it by Friday?"),
            ({"title": "Chief Revenue Officer", "industry": "Logistics"}, "Ben", "Should I send it Thursday?"),
            ({"title": "Director of Sales", "industry": "Software"}, "Cy", "Is Monday early enough?"),
            ({"title": "VP Sales", "industry": "Healthcare"}, "Di", "Does Friday work for the review?")]
    for facts, name, ask in rows:
        sent = body(name, ask)
        approve(ctx, facts, body(name, ask, " Per our conversation, this matters."), sent)
    approve(ctx, rows[0][0], body("Ana", "Want it by Friday?"), body("Ana", "Want it by Friday?"))  # same body again
    approve(ctx, {"title": "VP Sales"}, "Hi Eve,\n\nWe can unlock seamless synergy for your team. Want a call?\n\nSam",
            "Hi Eve,\n\nWe can unlock seamless synergy for your team. Want a call?\n\nSam")  # fails the gate as sent


def test_build_keeps_gate_passing_distinct_varied_examples(ctx_for):
    ctx = ctx_for("follow-through")
    seed(ctx)
    rep = exemplars.build(ctx.store, per_kind=3)
    assert rep[KIND]["examples"] == 4 and rep[KIND]["kept"] == 3 and rep[KIND]["version"]
    rows = ctx.store.query("SELECT * FROM exemplars WHERE kind=? ORDER BY rank", (KIND,))
    feats = [set(json.loads(r["features"])) for r in rows]
    assert len(set().union(*feats)) >= 5  # greedy coverage: personas and industries spread out
    assert not any("unlock" in r["body"] for r in rows)
    assert exemplars.build(ctx.store, per_kind=3) == rep  # same data, same set, same version
    assert exemplars.build(ctx.store, ["meeting recap"])["meeting recap"]["kept"] == 0


def test_select_prefers_shared_features(ctx_for):
    ctx = ctx_for("follow-through")
    seed(ctx)
    exemplars.build(ctx.store)
    got = exemplars.select(ctx.store, KIND, {"contact": {"title": "Chief Revenue Officer"}, "industry": "Logistics"}, k=1)
    assert "Hi Ben" in got[0]["body"]
    assert exemplars.select(ctx.store, "nothing here", {}) == []


def test_edit_patterns_find_what_aes_cut(ctx_for):
    ctx = ctx_for("follow-through")
    seed(ctx)
    pats = exemplars.edit_patterns(ctx.store, KIND, min_count=3)
    assert pats == [{"phrase": "per our conversation this matters", "count": 4}]
    assert exemplars.edit_patterns(ctx.store, KIND, min_count=5) == []


class FakeGateway:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def available(self, model_class="frontier"):
        return True

    def complete(self, prompt, **kw):
        self.prompts.append(prompt)
        return type("R", (), {"text": self.reply})()


def test_writer_shows_examples_and_cuts_and_records_them(ctx_for):
    ctx = ctx_for("follow-through")
    seed(ctx)
    exemplars.build(ctx.store)
    ctx.gateway = FakeGateway("Subject: Summary\n\n" + body("Fay", "Want it by Friday?"))
    d = writer.write(ctx, KIND, {"title": "VP Sales", "industry": "Software"}, "One ask.", "Subject: x\n\nHi")
    p = ctx.gateway.prompts[0]
    assert "Example 1:" in p and "Never reuse their names" in p and '"per our conversation this matters"' in p
    assert d.source == "model" and len(d.exemplars) == 3
    span = ctx.store.one("SELECT meta FROM spans WHERE kind='draft' ORDER BY started_at DESC, rowid DESC LIMIT 1")
    assert json.loads(span["meta"])["exemplars"] == d.exemplars
    ctx.manifest.config["exemplars"] = 0
    writer.write(ctx, KIND, {}, "One ask.", "Subject: x\n\nHi")
    assert "Example 1:" not in ctx.gateway.prompts[-1]


def test_dspy_pass_is_optional_and_metric_is_gate_then_similarity(ctx_for):
    good = body("Ana", "Want it by Friday?")
    assert exemplars.score(good, good) == 1.0
    assert exemplars.score("We unlock synergy. Call?", good) == 0.0
    ctx = ctx_for("quality-monitor")
    tools = __import__("gtm_core.agents", fromlist=["load_module"]).load_module(ctx.manifest, "tools")
    assert "GTM_DSPY_MODEL" in tools.optimize_drafter(ctx, KIND)["skipped"]
    res = exemplars.optimize_dspy(ctx.store, KIND, "openai/none")
    assert "skipped" in res  # dspy missing, or too few approved sends
