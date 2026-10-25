"""Lemlist, Clay and notetaker connectors against mocked HTTP."""
import json
from datetime import datetime, timezone

import httpx

from gtm_core import engagement
from gtm_core.agents import load_module
from gtm_core.connectors import clay, notetakers
from gtm_core.connectors.sequencer import LemlistSequencer

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_lemlist_enroll_and_stop():
    seen = []

    def h(req):
        seen.append((req.method, str(req.url), req.headers.get("authorization"), req.content))
        return httpx.Response(200, json={"_id": "lea_1"})
    s = LemlistSequencer("key123", "cam_9", client=_client(h))
    s.enroll({"email": "omar@proseware.example", "name": "Omar Haddad", "company": "Proseware"},
             [{"subject": "S1", "body": "B1"}, {"subject": "S2", "body": "B2"}], meta={"draft_ids": [4, 5], "value_prop": "x"})
    m, url, auth, body = seen[0]
    assert m == "POST" and "/campaigns/cam_9/leads/omar@proseware.example" in url and auth.startswith("Basic ")
    b = json.loads(body)
    assert b["firstName"] == "Omar" and b["gtm_body_2"] == "B2" and b["gtm_draft_ids"] == "4,5"
    r = s.stop("omar@proseware.example", "replied")
    assert r["ok"] and seen[1][0] == "DELETE"
    assert LemlistSequencer("k", None, client=_client(h)).stop("a@b.example")["manual"]


def test_lemlist_webhook_names_map():
    assert engagement.normalize_event("emailsOpened") == "open"
    assert engagement.normalize_event("emailsInterested") == "reply_positive"
    assert engagement.normalize_event("EMAIL_LINK_CLICK") == "click"


def test_bounce_and_unsubscribe_suppress_locally(ctx_for):
    st = ctx_for("icp-outbound").store
    st.upsert("contacts", {"id": "c1", "email": "a@b.example", "account_id": "b.example"})
    r = engagement.record(st, "a@b.example", "emailsBounced", "2026-10-20T10:00:00Z")
    assert r["suppressed"] == "email_invalid" and st.get("contacts", "c1")["email_invalid"] is True
    from gtm_core import suppression
    assert suppression.is_suppressed(st, "a@b.example", st.get("contacts", "c1"))


def test_clay_rows_merge_without_blanking(ctx_for, tmp_path):
    st = ctx_for("enrichment").store
    st.upsert_account({"id": "proseware.example", "name": "Proseware", "domain": "proseware.example", "industry": "Software"})
    f = tmp_path / "clay.csv"
    f.write_text("Company Domain,Company Name,Industry,Employee Count,Annual Revenue,Technologies,Work Email,Full Name,Job Title\n"
                 "https://www.proseware.example/,Proseware,,201-500,$40M,\"Salesforce, Gong\",omar@proseware.example,Omar Haddad,VP Sales\n"
                 ",,,,,,,,\n")
    res = clay.import_csv(st, f)
    assert res == {"accounts": 1, "contacts": 1, "skipped_no_domain": 1}
    a = st.account("proseware.example")
    assert a["industry"] == "Software" and a["employees"] == 350 and a["revenue"] == 40e6 and a["tech"] == ["salesforce", "gong"]
    c = st.contact_by_email("omar@proseware.example")
    assert c["name"] == "Omar Haddad" and c["title"] == "VP Sales" and c["account_id"] == "proseware.example"


def test_clay_push_tool(ctx_for):
    ctx = ctx_for("enrichment")
    ctx.store.upsert_account({"id": "a.example", "name": "A", "domain": "a.example"})
    sent = []
    ctx.clay = clay.ClayTable("https://clay.example/hook", "s", client=_client(lambda r: sent.append(json.loads(r.content)) or httpx.Response(200)))
    out = load_module(ctx.manifest, "tools").push_to_clay(ctx)
    assert out["sent"] == 1 and sent[0]["domain"] == "a.example"


def test_gong_pull_joins_speakers():
    def h(req):
        if req.url.path.endswith("/extensive"):
            return httpx.Response(200, json={"calls": [{"metaData": {"id": "77", "title": "Disco", "started": "2026-10-22T15:00:00Z"},
                                                         "parties": [{"speakerId": "s1", "name": "Sam Rivera", "emailAddress": "sam@beacon.example"},
                                                                     {"speakerId": "s2", "name": "Dana Cole"}]}], "records": {}})
        return httpx.Response(200, json={"callTranscripts": [{"callId": "77", "transcript": [
            {"speakerId": "s1", "sentences": [{"text": "Thanks for joining."}, {"text": "What changed?"}]},
            {"speakerId": "s2", "sentences": [{"text": "Our forecast slipped."}]}]}]})
    [m] = notetakers.Gong("k", "s", client=_client(h)).pull(NOW)
    assert m["id"] == "gong:77" and m["transcript"] == "Sam Rivera: Thanks for joining. What changed?\nDana Cole: Our forecast slipped."


def test_fireflies_and_fathom_pull_and_store(ctx_for):
    ff = notetakers.Fireflies("k", client=_client(lambda r: httpx.Response(200, json={"data": {"transcripts": [
        {"id": "f1", "title": "Demo", "dateString": "2026-10-22T16:00:00Z", "participants": ["dana@northwind.example"],
         "sentences": [{"speaker_name": "Dana", "text": "Pricing?"}]}]}})))
    pages = iter([{"items": [{"recording_id": 5, "title": "Call", "created_at": "2026-10-22T17:00:00Z",
                              "calendar_invitees": [{"email": "omar@proseware.example"}],
                              "transcript": [{"speaker": {"display_name": "Omar"}, "text": "Hi", "timestamp": "00:00:01"}]}],
                   "next_cursor": "c2"}, {"items": [], "next_cursor": None}])
    fa = notetakers.Fathom("k", client=_client(lambda r: httpx.Response(200, json=next(pages))))
    ctx = ctx_for("meeting-intelligence")
    out = load_module(ctx.manifest, "jobs").pull_transcripts(ctx, NOW, pullers=[ff, fa])
    assert out == {"fireflies": {"added": 1, "updated": 0, "unchanged": 0, "empty": 0},
                   "fathom": {"added": 1, "updated": 0, "unchanged": 0, "empty": 0}}
    assert ctx.store.get("meetings", "fathom:5")["transcript"] == "Omar: Hi"
    assert ctx.store.get_state("notetaker_last_pull:fathom") == NOW.isoformat()
    again = notetakers.store_meetings(ctx.store, [{"id": "fathom:5", "transcript": "Omar: Hi"}])
    assert again["unchanged"] == 1


def test_pull_transcripts_without_keys(ctx_for, monkeypatch):
    for k in ("GONG_ACCESS_KEY", "FIREFLIES_API_KEY", "FATHOM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    ctx = ctx_for("meeting-intelligence")
    assert "skipped" in load_module(ctx.manifest, "jobs").pull_transcripts(ctx, NOW)
