import json
from datetime import datetime, timezone

import httpx
import pytest

from gtm_core.agents import load_module
from gtm_core.executors import register_core_executors
from gtm_core.mcp_server import bind_tools

NOW = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


@pytest.mark.parametrize("raw,country,want", [
    ("(415) 555-0142", "US", "+14155550142"), ("1-415-555-0142 ext 22", "US", "+14155550142"),
    ("+44 20 7946 0018", "US", "+442079460018"), ("020 7946 0018", "GB", "+442079460018"),
    ("0044 20 7946 0018", "US", "+442079460018"), ("030 1234567", "DE", "+49301234567"),
    ("555-0142", "US", None), ("123", "US", None), ("", "US", None)])
def test_phone_normalization(ctx_for, raw, country, want):
    assert _eng(ctx_for("enrichment")).normalize_phone(raw, country) == want


def test_http_provider_env_paths_and_waterfall(ctx_for, monkeypatch):
    ctx = ctx_for("enrichment")
    eng = _eng(ctx)
    seen = []

    def handler(req):
        seen.append(req)
        if "verify" in str(req.url):
            return httpx.Response(200, json={"status": "valid"})
        if req.url.params.get("email") == "nobody@nw.example":
            return httpx.Response(404)
        return httpx.Response(200, json={"data": [{"mobile": "415.555.0101", "work_email": "dana@nw.example"}]})
    monkeypatch.setattr(eng, "HTTP_CLIENT", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("VENDOR_KEY", "secret-123")
    cfg = {"default_country": "US", "ttl_days": 90, "caps": {"per_run_usd": 10, "monthly_usd": 100}, "verifier": "v",
           "order": {"phone": ["vendor"], "email": ["vendor"]},
           "providers": {"vendor": {"type": "http", "url": "https://api.vendor.example/p?email={email}",
                                    "headers": {"Authorization": "Bearer ${VENDOR_KEY}"},
                                    "outputs": {"phone": "data.0.mobile", "email": "data[0].work_email"}, "cost_per_call": 0.1},
                         "v": {"type": "http", "url": "https://verify.example/verify?e={email}", "outputs": {"status": "status"},
                               "accepted": ["valid"], "cost_per_call": 0.01}}}
    r = eng.waterfall(ctx, {"email": "dana@nw.example", "domain": "nw.example"}, ["phone"], eng.new_run(), cfg, NOW)
    assert r["phone"]["value"] == "+14155550101"
    assert seen[0].headers["authorization"] == "Bearer secret-123"
    r2 = eng.waterfall(ctx, {"name": "Dana", "domain": "nw.example"}, ["email"], eng.new_run(), cfg, NOW)
    assert r2["email"]["value"] == "dana@nw.example" and r2["email"]["confidence"] == 0.95  # verified
    miss = eng.waterfall(ctx, {"email": "nobody@nw.example"}, ["phone"], eng.new_run(), cfg, NOW)
    assert miss["phone"]["status"] == "not found"
    monkeypatch.delenv("VENDOR_KEY")
    skipped = eng.waterfall(ctx, {"email": "other@nw.example"}, ["phone"], eng.new_run(), cfg, NOW)
    assert skipped["phone"]["status"] == "not found"
    notes = [r["note"] for r in ctx.store.query("SELECT note FROM enrichment_calls")]
    assert any("missing environment variable VENDOR_KEY" in n for n in notes)
    assert not any("secret-123" in n for n in notes)


def test_rate_limit_sleeps(ctx_for, monkeypatch):
    ctx = ctx_for("enrichment")
    eng = _eng(ctx)
    slept = []
    monkeypatch.setattr(eng, "SLEEP", slept.append)
    monkeypatch.setattr(eng, "HTTP_CLIENT", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    eng._RATE.clear()
    p = eng.HttpProvider("rl", {"url": "https://x.example/{email}", "outputs": {}, "rate_limit_per_minute": 2}, ctx.manifest.root)
    for i in range(3):
        p.lookup({"email": f"a{i}@x.example"})
    assert len(slept) == 1 and slept[0] > 0


def test_tools_and_approval_execution(ctx_for):
    ctx = ctx_for("enrichment")
    ctx.store.upsert_account({"id": "northwind.example", "name": "Northwind", "domain": "northwind.example", "crm_id": "1"})
    ctx.store.upsert("contacts", {"id": "dana.cole@northwind.example", "email": "dana.cole@northwind.example",
                                  "name": "Dana Cole", "crm_id": "c1", "account_id": "northwind.example",
                                  "manual_fields": ["title"], "title": "VP Sales"})
    tools = bind_tools(ctx)
    r = tools["enrich_contact"](contact="dana.cole@northwind.example", fields=["phone", "title"], force=True)
    assert r["changed"] == {"phone": "+14155550142"}  # title is manual: never replaced
    register_core_executors(ctx)
    for a in ctx.approvals.list():
        ctx.approvals.decide(a["id"], True)
    ctx.approvals.execute_approved()
    assert ctx.crm.writes[-1] == {"kind": "contact_update", "crm_id": "c1", "fields": {"phone": "+14155550142"}}
    assert tools["enrich_contact"](contact="nobody")["error"]
    assert tools["coverage_report"]()["target_contacts"] == 0
    assert tools["waterfall_report"](days=7)["calls"] >= 1


def test_dialer_push_is_opt_in_and_needs_approval(ctx_for):
    ctx = ctx_for("enrichment")
    ctx.manifest.config["push_new_phones_to_dialer"] = True
    try:
        ctx.store.upsert("contacts", {"id": "rosa.diaz@fourthcoffee.example", "email": "rosa.diaz@fourthcoffee.example",
                                      "name": "Rosa Diaz", "crm_id": "c9", "owner": "Sam Rivera"})
        _eng(ctx).enrich_contact(ctx, ctx.store.get("contacts", "rosa.diaz@fourthcoffee.example"), ["phone"])
        acts = [a["action"] for a in ctx.approvals.list()]
        assert acts == ["contact_update", "dialer_enqueue"]
        assert not ctx.dialer.queued  # nothing pushed until approved
    finally:
        ctx.manifest.config["push_new_phones_to_dialer"] = False


@pytest.mark.parametrize("raw,country,want", [
    ("+44 (0)20 7946 0958", "US", "+442079460958"), ("030 1234567", "Germany", "+49301234567"),
    ("020 7946 0018", "United Kingdom", "+442079460018"), ("(415) 555-0142", "United States", "+14155550142")])
def test_phone_trunk_prefix_and_country_names(ctx_for, raw, country, want):
    assert _eng(ctx_for("enrichment")).normalize_phone(raw, country) == want


def _http_cfg(url="https://api.vendor.example/p?api_key=${VENDOR_KEY}&name={name}", body=None):
    p = {"type": "http", "url": url, "outputs": {"phone": "phone"}, "cost_per_call": 0.1}
    if body:
        p.update({"method": "POST", "json": body})
    return {"default_country": "US", "ttl_days": 90, "miss_ttl_days": 14, "caps": {"per_run_usd": 10, "monthly_usd": 100},
            "order": {"phone": ["vendor"]}, "providers": {"vendor": p}}


def test_contact_data_is_never_expanded_as_an_env_var(ctx_for, monkeypatch):
    ctx = ctx_for("enrichment")
    eng = _eng(ctx)
    bodies = []

    def handler(req):
        bodies.append(req.content.decode())
        return httpx.Response(200, json={})
    monkeypatch.setattr(eng, "HTTP_CLIENT", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("VENDOR_KEY", "sk-SECRET123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TOPSECRET")
    cfg = _http_cfg(url="https://api.vendor.example/p", body={"key": "${VENDOR_KEY}", "name": "{name}"})
    eng.waterfall(ctx, {"name": "${ANTHROPIC_API_KEY}", "domain": "x.example"}, ["phone"], eng.new_run(), cfg, NOW)
    assert "sk-ant-TOPSECRET" not in bodies[0] and "${ANTHROPIC_API_KEY}" in bodies[0] and "sk-SECRET123" in bodies[0]


def test_errors_never_store_secrets_and_misses_are_cached(ctx_for, monkeypatch):
    ctx = ctx_for("enrichment")
    eng = _eng(ctx)
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if "boom" in str(req.url):
            raise httpx.ConnectError(f"failed to reach {req.url}")
        return httpx.Response(404)
    monkeypatch.setattr(eng, "HTTP_CLIENT", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("VENDOR_KEY", "sk-SECRET123")
    eng.waterfall(ctx, {"name": "boom", "domain": "x.example"}, ["phone"], eng.new_run(), _http_cfg(), NOW)
    notes = " ".join(r["note"] for r in ctx.store.query("SELECT note FROM enrichment_calls"))
    assert "sk-SECRET123" not in notes
    for _ in range(3):
        r = eng.waterfall(ctx, {"name": "Nobody", "domain": "x.example"}, ["phone"], eng.new_run(), _http_cfg(), NOW)
    assert sum("Nobody" in c for c in calls) == 1 and r["phone"]["status"] == "not found (cached)"


def test_bounced_email_is_never_brought_back(ctx_for, monkeypatch):
    ctx = ctx_for("enrichment")
    eng = _eng(ctx)
    monkeypatch.setattr(eng, "HTTP_CLIENT", httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"email": "dana@nw.example"}))))
    ctx.store.upsert("contacts", {"id": "c1", "email": "dana@nw.example", "email_invalid": True, "name": "Dana Cole"})
    cfg = {"default_country": "US", "caps": {"per_run_usd": 10, "monthly_usd": 100}, "order": {"email": ["vendor"]},
           "providers": {"vendor": {"type": "http", "url": "https://v.example/e?n={name}", "outputs": {"email": "email"}}}}
    p = eng.person_from_contact(ctx, ctx.store.get("contacts", "c1"))
    p["domain"] = "nw.example"
    assert "value" not in eng.waterfall(ctx, p, ["email"], eng.new_run(), cfg, NOW)["email"]


def test_requests_left_pending_when_run_is_full(ctx_for):
    from gtm_core.handoffs import Handoffs
    ctx = ctx_for("enrichment")
    ctx.manifest.config["max_per_run"] = 1
    ctx.manifest.config["providers_inline"] = {"order": {"email": ["m"]}, "providers": {"m": {"type": "manual"}}}
    for n in ("a", "b"):
        Handoffs(ctx.store, "reply-desk").send("enrichment", "enrich_request", n,
                                               {"email": f"{n}@x.example", "fields": ["phone"]})
    load_module(ctx.manifest, "jobs").enrich_queue(ctx, now=NOW)
    assert len(ctx.handoffs.pending("enrich_request")) == 1
