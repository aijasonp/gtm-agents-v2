import json
from datetime import datetime, timezone

from gtm_core.agents import load_module
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def _seed(ctx):
    ctx.store.upsert_account({"id": "northwind.example", "name": "Northwind Logistics", "domain": "northwind.example",
                              "crm_id": "1001", "industry": "Logistics", "employees": 600, "country": "US"})
    ctx.store.upsert("contacts", {"id": "dana@northwind.example", "email": "dana@northwind.example", "name": "Dana Cole",
                                  "title": "VP of Sales", "account_id": "northwind.example"})
    ctx.store.upsert("deals", {"id": "d1", "account_id": "northwind.example", "name": "NW", "owner": "Sam Rivera",
                               "stage": "Evaluation", "status": "open"})


def test_inbox_job_alerts_owner_and_archives(ctx_for, tmp_path):
    ctx = ctx_for("social-signals")
    _seed(ctx)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "li.json").write_text(json.dumps([
        {"platform": "linkedin", "post_title": "Ranking accounts", "post_url": "https://example.com/p/1",
         "name": "Dana Cole", "company": "Northwind Logistics", "type": "comment",
         "comment": "Is there a trial?", "timestamp": "2026-10-22T10:00:00Z"}]))
    ctx.manifest.config = {**ctx.manifest.config, "engagement_inbox": str(inbox)}
    out = load_module(ctx.manifest, "jobs").ingest_engagement(ctx, now=NOW)
    assert out["files"] == 1 and out["signals"] == 1 and out["resolved_contact"] == 1
    assert not list(inbox.glob("*.json")) and (tmp_path / "processed" / "li.json").exists()
    msg = ctx.slack.sent[-1]["text"]
    assert "Social Signals for Sam Rivera" in msg and "Dana Cole" in msg and "buying question" in msg
    sig = ctx.store.signals_for("northwind.example")[0]
    assert sig["signal_type"] == "social_buying_question" and sig["payload"]["topic"] == "Ranking accounts"


def test_tools(ctx_for):
    ctx = ctx_for("social-signals")
    _seed(ctx)
    t = bind_tools(ctx)
    r = t["resolve_person"](name="Dana Cole", company="Northwind Logistics, Inc.")
    assert r["contact_id"] == "dana@northwind.example" and r["method"] == "name + company"
    assert ctx.store.insights("social_engagement") == []  # resolve writes nothing
    t["add_engagement"](engager_name="Dana Cole", engager_company="Northwind Logistics", engagement_type="share",
                        post_title="Forecast hygiene", engaged_at="2026-10-22T10:00:00Z")
    assert t["engagement_for"](account="northwind.example")["count"] == 1
    top = t["top_engagers"](days=3650)["people"]
    assert top[0]["name"] == "Dana Cole" and top[0]["owner"] == "Sam Rivera"
    rep = load_module(ctx.manifest, "jobs").weekly_creator_report(ctx, now=NOW)
    assert rep["creators"] == 1 and "creator report" in ctx.slack.sent[-1]["text"]


def test_unknown_types_and_people_are_safe(ctx_for):
    ctx = ctx_for("social-signals")
    eng = load_module(ctx.manifest, "engine")
    out = eng.ingest(ctx, [{"name": "X", "type": "bookmark", "post_title": "p"},
                           {"type": "comment", "post_title": "p"},
                           {"name": "Nobody", "company": "Nowhere", "type": "comment", "comment": "hi"}], NOW)
    assert out["stats"]["skipped"] == 2 and out["stats"]["unresolved"] == 1 and out["stats"]["signals"] == 0


def test_non_ascii_names_never_collide(ctx_for):
    eng = load_module(__import__("gtm_core.agents", fromlist=["Manifest"]).Manifest.load("agents/social-signals"), "engine")
    assert eng.norm_name("王伟") != eng.norm_name("李娜") and eng.norm_name("王伟")
    assert eng.norm_name("José  Núñez") == eng.norm_name("josé núñez")


def test_bad_file_is_quarantined_and_suppressed_people_are_marked(ctx_for, tmp_path):
    from gtm_core import suppression
    ctx = ctx_for("social-signals")
    _seed(ctx)
    suppression.suppress(ctx.store, "dana@northwind.example", "opt-out")
    inbox = tmp_path / "eng" / "inbox"; inbox.mkdir(parents=True)
    (inbox / "a.json").write_text("[{broken")
    (inbox / "b.json").write_text(json.dumps([{"platform": "linkedin", "post_title": "Ranking accounts",
                                                "post_url": "https://example.com/p/1", "name": "Dana Cole",
                                                "company": "Northwind Logistics", "type": "comment",
                                                "comment": "Is there a trial?", "timestamp": "2026-10-22T10:00:00Z"}]))
    ctx.manifest.config = {**ctx.manifest.config, "engagement_inbox": str(inbox)}
    out = load_module(ctx.manifest, "jobs").ingest_engagement(ctx, now=NOW)
    assert out["failed_files"] == ["a.json"] and out["files"] == 1
    assert "DO NOT CONTACT" in ctx.slack.sent[-1]["text"]
