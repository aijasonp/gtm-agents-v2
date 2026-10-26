import json
from datetime import datetime, timezone

import httpx
import yaml

from gtm_core.agents import load_module
from gtm_core.api import Api
from gtm_core.sources import pagewatch as pw
from gtm_core.store import Store

RULES = yaml.safe_load(open("config/signals.yaml"))
ACCT = {"id": "northwind.example", "name": "Northwind Traders", "domain": "northwind.example"}


def change(url, added=(), removed=(), tags="", day="2026-10-20"):
    return {"url": url, "uuid": "w1", "title": "", "tags": [t for t in tags.split(",") if t],
            "added": list(added), "removed": list(removed), "changed_at": day}


def kinds(findings):
    return [(f.signal_type, f.confidence) for f in findings]


def test_parse_json_apprise_and_template():
    flat = pw.parse_notification({"watch_url": "https://northwind.example/careers", "watch_tag": "gtm:careers, account:northwind.example",
                                  "diff_added": "(added) VP of Sales, Central\n(added) Office Manager"})
    assert flat["tags"] == ["gtm:careers", "account:northwind.example"] and flat["added"] == ["VP of Sales, Central", "Office Manager"]
    text = pw.NOTIFICATION_TEMPLATE.replace("{{watch_url}}", "https://northwind.example/trust").replace(
        "{{watch_uuid}}", "u9").replace("{{watch_title}}", "Trust").replace("{{watch_tag}}", "gtm:trust").replace(
        "{{diff_added}}", "+ We are now SOC 2 Type II certified").replace("{{diff_removed}}", "")
    wrapped = pw.parse_notification({"title": "ChangeDetection.io Notification", "message": text, "type": "info"})
    assert wrapped["url"].endswith("/trust") and wrapped["uuid"] == "u9" and wrapped["added"] == ["We are now SOC 2 Type II certified"]
    for bad in ({"diff_added": "x"}, 42):
        try:
            pw.parse_notification(bad)
            assert False
        except ValueError:
            pass


def test_classify_each_page_kind():
    assert kinds(pw.classify(change("https://northwind.example/careers",
                                    ["VP of Sales, Central", "Revenue Operations Manager", "Barista"]), ACCT, RULES)) == \
        [("hiring_buyer_team", "Medium")]
    assert kinds(pw.classify(change("https://northwind.example/trust", ["Northwind is now SOC 2 Type II certified"]),
                             ACCT, RULES)) == [("audit_or_certification", "High")]
    assert kinds(pw.classify(change("https://northwind.example/about/leadership",
                                    ["Dana Ruiz, Chief Revenue Officer"]), ACCT, RULES)) == [("new_exec_in_buyer_function", "Medium")]
    assert kinds(pw.classify(change("https://northwind.example/newsroom",
                                    ["Northwind launches an AI sales assistant program for every rep"]), ACCT, RULES)) == \
        [("strategic_initiative", "Medium")]
    assert kinds(pw.classify(change("https://northwind.example/pricing", ["Team plan $49"], ["Team plan $39"]), ACCT, RULES)) \
        == [("pricing_change", "Medium")]
    rules = {**RULES, "page_changes": {**RULES["page_changes"], "competitor_tools": ["rivalcrm.example"]}}
    tech = pw.classify(change("https://northwind.example/", ['<script src="https://cdn.rivalcrm.example/t.js">'],
                              ['<script src="https://js.hs-scripts.hubspot.com/1.js">'], "gtm:tech"), ACCT, rules)
    assert kinds(tech) == [("competitor_installed", "Medium"), ("removed_tool", "Medium")]
    assert pw.classify(change("https://northwind.example/careers", ["Barista"]), ACCT, RULES) == []
    assert pw.classify(change("https://northwind.example/random", ["anything"]), ACCT, RULES) == []


def test_api_page_change_stores_mentionable_signals_only_in_dispatch(settings):
    settings.agents_dir = "agents"
    st = Store("sqlite:///:memory:"); st.init()
    st.upsert_account({"id": "northwind.example", "name": "Northwind Traders", "domain": "northwind.example",
                       "industry": "Software", "employees": 900, "country": "US"})
    api = Api(settings, "secret", store=st)
    code, out = api.route("POST", "/v1/page-changes", {}, {"watch_url": "https://careers.northwind.example/jobs/",
                                                             "watch_tag": "gtm:careers", "diff_added": "VP of Sales, Central"})
    assert code == 201 and out["account"] == "northwind.example" and out["kind"] == "careers"
    assert st.one("SELECT source, signal_type FROM signals") == {"source": "sourcing:page_change",
                                                                 "signal_type": "hiring_buyer_team"}
    code, out = api.route("POST", "/v1/page-changes", {}, {"watch_url": "https://unknown.example/careers", "diff_added": "x"})
    assert code == 200 and "no account" in out["skipped"]
    assert api.route("POST", "/v1/page-changes", {}, {"diff_added": "x"})[0] == 400


def test_poll_diffs_two_newest_snapshots_and_moves_the_cursor(ctx_for):
    ctx = ctx_for("signal-sourcing")
    ctx.store.upsert_account({"id": "northwind.example", "name": "Northwind Traders", "domain": "northwind.example",
                              "industry": "Software", "employees": 900, "country": "US"})
    t1, t2 = 1760900000, 1760990000
    routes = {"/api/v1/watch": {"w1": {"url": "https://northwind.example/careers", "last_changed": t2, "tags": ["gtm:careers"]},
                                "w2": {"url": "https://northwind.example/pricing", "last_changed": 100}},
              "/api/v1/watch/w1/history": {str(t1): "p1", str(t2): "p2"},
              f"/api/v1/watch/w1/history/{t1}": "Open roles\nAccountant",
              f"/api/v1/watch/w1/history/{t2}": "Open roles\nAccountant\nDirector of Revenue Operations"}

    def handler(req):
        assert req.headers["x-api-key"] == "k"
        v = routes[req.url.path]
        return httpx.Response(200, json=v) if isinstance(v, dict) else httpx.Response(200, text=v)

    cd = pw.ChangeDetection("https://cd.example", "k", httpx.Client(transport=httpx.MockTransport(handler)))
    eng = load_module(ctx.manifest, "engine")
    now = datetime.fromtimestamp(t2, timezone.utc)
    ctx.store.set_state("sourcing:page_changes_cursor", t1)  # w2 changed before the last poll
    res = eng.poll_page_changes(ctx, now, cd)
    assert res["changes"] == 1 and res["stored"] == 1
    assert ctx.store.get_state("sourcing:page_changes_cursor") == t2
    assert eng.poll_page_changes(ctx, now, cd)["changes"] == 0  # nothing new since the cursor


def test_watch_plan_tags_pages_for_import():
    rows = pw.watch_plan([ACCT])
    assert {r["tags"].split(",")[0] for r in rows} == {"gtm:pricing", "gtm:careers", "gtm:trust", "gtm:leadership",
                                                      "gtm:news", "gtm:tech"}
    assert all("account:northwind.example" in r["tags"] for r in rows)
    assert json.dumps(rows)
