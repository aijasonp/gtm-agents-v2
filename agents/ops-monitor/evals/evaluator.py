"""Ops Monitor evaluator: every check status on a seeded runtime, alert dedupe and recovery."""
from __future__ import annotations

import json
from datetime import datetime

from gtm_core.agents import Manifest, load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    st = ctx.store
    for i, (agent, job, at, status, err) in enumerate(spec["runs"]):
        st.execute("INSERT INTO runs (id, agent, job, started_at, finished_at, status, stats) VALUES (?,?,?,?,?,?,?)",
                   (f"r{i}", agent, job, at, None if status == "running" else at, status, json.dumps({"error": err} if err else {})))
    for agent, action, status, req, dec in spec["approvals"]:
        st.insert("INSERT INTO approvals (agent, action, payload, status, requested_at, decided_at) VALUES (?,?,?,?,?,?)",
                  (agent, action, "{}", status, req, dec))
    for frm, to, kind, status, at, err in spec["handoffs"]:
        st.insert("INSERT INTO handoffs (from_agent, to_agent, kind, ref, payload, status, created_at) VALUES (?,?,?,?,?,?,?)",
                  (frm, to, kind, "x", json.dumps({"_error": err} if err else {}), status, at))
    for a in spec["paused"]:
        st.set_state(f"paused:{a}", True)
    for agent, ts, tokens in spec["token_usage"]:
        st.insert("INSERT INTO token_usage (ts, agent, model, input_tokens, output_tokens, usd) VALUES (?,?,?,?,?,?)",
                  (ts, agent, "m", tokens, 0, 1.0))
    for agent, passed in spec["drafts"]:
        st.insert("INSERT INTO drafts (agent, kind, body, gate_passed, status, created_at) VALUES (?,?,?,?,?,?)",
                  (agent, "x", "b", passed, "draft", "2026-11-01T10:00:00+00:00"))
    eng = load_module(m, "engine")
    ms = {a: Manifest.load(m.root.parent / a) for a in spec["agents"]}
    now = datetime.fromisoformat(spec["now"])
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:300]})

    rep = eng.report(ctx, now, ms, spec["discovery_errors"])
    got = {c["id"]: c["status"] for c in rep["checks"]}
    add("overall status is the worst check", rep["status"] == ex["overall"], rep["status"])
    for cid, s in ex["statuses"].items():
        add(f"{cid} = {s}", got.get(cid) == s, f"got {got.get(cid)}: " + next((c["detail"] for c in rep["checks"] if c["id"] == cid), ""))
    add("problem count", len(rep["problems"]) == ex["problems"], [p["id"] for p in rep["problems"]])
    ranks = [eng.RANK[p["status"]] for p in rep["problems"]]
    add("problems sorted worst first", ranks == sorted(ranks, reverse=True), ranks)
    add("failure detail carries the error", "401 Unauthorized" in next(c["detail"] for c in rep["checks"]
                                                                      if c["id"] == "job:signal-scout:sync_accounts:failures"), "")
    add("approval backlog grouped by agent", next(c for c in rep["checks"] if c["id"] == "approvals:backlog")["by_agent"]
        == ex["backlog_by_agent"], "")
    first = eng.changes(ctx, rep)
    add("first check alerts every problem", len(first["new"]) == ex["problems"] and not first["recovered"], len(first["new"]))
    again = eng.changes(ctx, eng.report(ctx, now, ms, spec["discovery_errors"]))
    add("unchanged problems do not alert again", again == {"new": [], "recovered": []}, again)
    st.execute("UPDATE approvals SET status='executed' WHERE status='executing'")
    fixed = eng.changes(ctx, eng.report(ctx, now, ms, spec["discovery_errors"]))
    add("recovery reported once", fixed["recovered"] == ["approvals:executing"] and not fixed["new"], fixed)
    js = eng.job_status(ctx, "lead-triage", now, ms)
    tri = next(j for j in js["jobs"] if j["job"] == "triage_inbox")
    add("job status shows failures and next run", tri["consecutive_failures"] == 3 and tri["next_run"].startswith("2026-11-02T10:15"), tri)
    add("unknown agent in job status", "error" in eng.job_status(ctx, "nope", now, ms), "")
    return out
