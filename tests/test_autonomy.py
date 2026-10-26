import shutil
from pathlib import Path

import pytest
import yaml

from gtm_core import autonomy
from gtm_core.api import Api
from gtm_core.approvals import Approvals, executor
from gtm_core.store import Store

RAN = []


@executor("autonomy_test_write")
def _write(payload):
    RAN.append(payload.get("n"))
    return {"ok": True}


def cfg(tmp_path, monkeypatch, **over):
    for f in ("approvals.yaml", "company.yaml"):
        shutil.copy(Path("config") / f, tmp_path / f)
    rules = yaml.safe_load(open("config/autonomy.yaml"))
    rules["stop"]["file"] = str(tmp_path / "STOP")
    rules.update(over)
    (tmp_path / "autonomy.yaml").write_text(yaml.safe_dump(rules))
    monkeypatch.setenv("GTM_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("GTM_STOP", raising=False)
    return autonomy.current()


def store():
    st = Store("sqlite:///:memory:")
    st.init()
    return st


def test_levels_most_specific_wins_and_sends_are_never_auto(tmp_path, monkeypatch):
    au = cfg(tmp_path, monkeypatch, motions={"outbound": "approve", "crm": "auto", "social": "off"},
             actions={"crm_note": "approve"}, agents={"crm-hygiene": "off"},
             auto_allowed=["crm_task", "crm_note", "autonomy_test_write"])
    assert au.level("crm_task", "signal-scout") == ("auto", "motions.crm")
    assert au.level("crm_note", "signal-scout") == ("approve", "actions.crm_note")
    assert au.level("crm_task", "crm-hygiene") == ("off", "agents.crm-hygiene")
    assert au.level("social_post", "social-signals")[0] == "off"
    assert au.level("crm_update", "signal-scout")[0] == "approve"  # auto, but crm_update is not in auto_allowed
    assert au.level("sequence_stop", "social-signals") == ("approve", "safety action (only reduces contact)")
    assert au.level("sequence_enroll", "icp-outbound", {"motion": "crm"})[0] == "approve"  # a send, never auto
    with pytest.raises(autonomy.AutonomyError):
        cfg(tmp_path, monkeypatch, actions={"pipeline_email": "auto"})
    with pytest.raises(autonomy.AutonomyError):
        cfg(tmp_path, monkeypatch, auto_allowed=["sequence_enroll"])
    with pytest.raises(autonomy.AutonomyError):
        cfg(tmp_path, monkeypatch, motions={"outbound": "yolo"})


def test_request_off_closes_and_auto_approves(tmp_path, monkeypatch):
    cfg(tmp_path, monkeypatch, motions={"crm": "auto", "social": "off"}, auto_allowed=["autonomy_test_write"])
    st = store()
    off = Approvals(st, "social-signals").request("social_post", {"text": "x"})
    auto = Approvals(st, "crm-hygiene").request("autonomy_test_write", {"n": 1})
    person = Approvals(st, "icp-outbound").request("sequence_enroll", {"contact": {"email": "a@b.example"}})
    rows = {r["id"]: r for r in st.query("SELECT id, status, decided_by FROM approvals")}
    assert (rows[off]["status"], rows[off]["decided_by"]) == ("rejected", "autonomy:off")
    assert (rows[auto]["status"], rows[auto]["decided_by"]) == ("approved", "autonomy:auto")
    assert rows[person]["status"] == "pending"


def test_stop_holds_executes_until_resume(tmp_path, monkeypatch):
    cfg(tmp_path, monkeypatch)
    st = store()
    ap = Approvals(st, "crm-hygiene")
    rid = ap.request("autonomy_test_write", {"n": 7})
    ap.decide(rid, True, by="Sam Rivera")
    autonomy.stop(st, "Sam Rivera", "bad list uploaded")
    RAN.clear()
    res = ap.execute_approved()
    assert res[0]["held"].startswith("STOP is on (gtm stop: bad list uploaded") and RAN == []
    assert ap.execute_one(rid)["held"] and st.one("SELECT status FROM approvals WHERE id=?", (rid,))["status"] == "approved"
    assert autonomy.resume(st, "Sam Rivera") == {"resumed": True, "still_stopped_by": None}
    assert ap.execute_approved()[0]["result"] == {"ok": True} and RAN == [7]


def test_stop_scopes_env_file_and_safety(tmp_path, monkeypatch):
    au = cfg(tmp_path, monkeypatch)
    st = store()
    monkeypatch.setenv("GTM_STOP", "outbound")
    assert au.stopped(st, "sequence_enroll", "icp-outbound")
    assert au.stopped(st, "pipeline_email", "follow-through") is None
    assert au.stopped(st, "sequence_stop", "icp-outbound") is None  # opt-outs still stop sequences
    monkeypatch.setenv("GTM_STOP", "0")
    assert au.stop_state(st) is None
    (tmp_path / "STOP").write_text("# incident 42\n")
    assert au.stop_state(st)["scopes"] == ["all"] and au.stopped(st, "crm_task", "crm-hygiene")
    autonomy.stop(st, "x")
    assert autonomy.resume(st, "x")["still_stopped_by"].startswith("file")


def test_scheduler_skips_jobs_during_stop(tmp_path, monkeypatch, settings):
    from gtm_core.agents import discover
    from gtm_core.scheduler import run_job
    cfg(tmp_path, monkeypatch)
    monkeypatch.setenv("GTM_STOP", "1")
    ms = discover("agents")
    st = store()
    assert run_job(settings, ms["signal-sourcing"], "poll_posthog", store=st)["skipped"].startswith("STOP is on")
    assert not run_job(settings, ms["ops-monitor"], "export_traces", store=st).get("skipped", "").startswith("STOP")
    assert run_job(settings, ms["signal-sourcing"], "poll_posthog", force=True, store=st)["skipped"].startswith("POSTHOG")


def test_api_stop_needs_an_approver_and_cannot_resume(tmp_path, monkeypatch, settings):
    cfg(tmp_path, monkeypatch)
    settings.agents_dir = "agents"
    st = store()
    api = Api(settings, "secret", store=st, approver_token="appr")
    assert api.route("POST", "/v1/stop", {}, {}, "intake")[0] == 403
    code, out = api.route("POST", "/v1/stop", {}, {"reason": "wrong segment", "scopes": ["outbound"]}, "approver:Sam Rivera")
    assert code == 201 and out["stop"]["by"] == "Sam Rivera" and out["stop"]["scopes"] == ["outbound"]
    assert api.route("GET", "/v1/stop", {}, None, "approver")[1]["stop"]["reason"] == "wrong segment"
    assert api.route("POST", "/v1/stop", {}, {"scopes": "all"}, "approver")[0] == 400
    assert api.route("DELETE", "/v1/stop", {}, None, "approver")[0] == 404
