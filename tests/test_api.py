import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gtm_core.api import Api, make_handler
from gtm_core.store import Store


@pytest.fixture
def server(settings):
    settings.agents_dir = "agents"
    st = Store("sqlite:///:memory:"); st.init()
    st.upsert_account({"id": "proseware.example", "name": "Proseware", "domain": "proseware.example", "industry": "Software",
                       "employees": 350, "country": "US", "crm_id": "9"})
    api = Api(settings, "secret", store=st, approver_token="approver-secret", approver_name="Jason", allow_execute=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", st
    httpd.shutdown()


def call(base, method, path, body=None, token="secret"):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_api_auth_and_lead_flow(server):
    base, st = server
    assert call(base, "GET", "/v1/health", token="wrong")[0] == 401
    code, out = call(base, "POST", "/v1/leads", {"email": "omar@proseware.example", "name": "Omar Haddad",
                                                "title": "VP of Sales", "company": "Proseware", "source": "demo_request"})
    assert code == 201 and out["triaged"][0]["tier"] == "hot"
    assert call(base, "POST", "/v1/leads", {"email": "omar@proseware.example", "source": "demo_request"})[1]["duplicates"] == 1
    A = "approver-secret"
    assert call(base, "GET", "/v1/approvals")[0] == 403  # intake token cannot see or approve
    assert call(base, "POST", "/v1/approvals/1/approve")[0] == 403
    pending = call(base, "GET", "/v1/approvals", token=A)[1]["approvals"]
    assert {p["action"] for p in pending} == {"crm_contact", "crm_task", "sequence_enroll"}
    for p in pending:
        assert call(base, "POST", f"/v1/approvals/{p['id']}/approve", {"by": "someone-else"}, token=A)[0] == 200
    assert call(base, "POST", f"/v1/approvals/{pending[0]['id']}/approve", token=A)[0] == 409
    res = call(base, "POST", "/v1/approvals/execute", token=A)[1]["results"]
    assert len(res) == 3 and all("result" in r for r in res), res
    assert call(base, "POST", "/v1/approvals/execute", token=A)[1]["results"] == []  # never twice
    decided = call(base, "GET", "/v1/approvals?status=executed", token=A)[1]["approvals"]
    assert {d["decided_by"] for d in decided} == {"Jason"}


def test_api_meetings_and_bad_input(server):
    base, _ = server
    assert call(base, "POST", "/v1/meetings", {"id": "m1", "transcript": "Sam: hi\nDana: hello"})[0] == 201
    assert call(base, "POST", "/v1/leads", {"name": "no email"})[1]["errors"]
    assert call(base, "GET", "/v1/nope")[0] == 404
    assert call(base, "POST", "/v1/leads", ["not an object"])[0] == 400
    assert call(base, "POST", "/v1/leads", {"email": {"x": 1}})[0] == 400
    assert call(base, "POST", "/v1/signals", {"account_id": "nobody.example", "signal_type": "funding_round",
                                              "observed_at": "2026-10-01"})[1]["rejected"] == 1
    assert call(base, "POST", "/v1/signals", {"account_id": "proseware.example", "signal_type": "funding_round",
                                              "observed_at": "not a date"})[1]["rejected"] == 1


def test_api_execute_off_by_default(settings):
    st = Store("sqlite:///:memory:"); st.init()
    settings.agents_dir = "agents"
    api = Api(settings, "secret", store=st, approver_token="a")
    assert api.route("POST", "/v1/approvals/execute", {}, None, "approver")[0] == 403
    with pytest.raises(RuntimeError):
        Api(settings, "same", store=st, approver_token="same")


def test_api_replies_and_engagement_go_to_inboxes(server, tmp_path, monkeypatch):
    base, st = server
    monkeypatch.chdir(tmp_path)
    code, out = call(base, "POST", "/v1/replies", [{"from_email": "a@b.example", "body": "Yes, send times"}, {"body": "no sender"}])
    assert code == 202 and out == {"queued": 1, "rejected": 1, "agent": "reply-desk"}
    code, out = call(base, "POST", "/v1/engagement", {"engager_name": "Kai Moore", "engagement_type": "comment",
                                                      "platform": "linkedin"})
    assert code == 202 and out["queued"] == 1
    assert list((tmp_path / "data/replies/inbox").glob("api-*.json"))


def test_concurrent_reply_posts_all_land(server, tmp_path, monkeypatch):
    import concurrent.futures as cf
    base, _ = server
    monkeypatch.chdir(tmp_path)
    with cf.ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda i: call(base, "POST", "/v1/replies", {"from_email": f"p{i}@b.example", "body": "hi",
                                                                         "subject": ["a", "b"]})[0], range(8)))
    assert codes == [202] * 8
    files = list((tmp_path / "data/replies/inbox").glob("api-*.json"))
    assert len(files) == 8
    assert json.loads(files[0].read_text())[0]["subject"] == "a, b"
