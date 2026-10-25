"""Rep Feedback engine: file feedback, route it to the controlling file, draft a patch, open a PR after approval.

Deterministic routing. No model calls. Never targets library/ (third-party playbooks).
"""
from __future__ import annotations

import base64
import difflib
import json
import re
import uuid
from pathlib import Path

import httpx

from gtm_core.store import now_iso

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS rep_feedback (id TEXT PRIMARY KEY, agent TEXT, draft_id INTEGER, rep TEXT, text TEXT,
       target TEXT, status TEXT, proposal_id TEXT, created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS rep_feedback_proposals (id TEXT PRIMARY KEY, target TEXT, rules TEXT, patch TEXT,
       feedback_ids TEXT, status TEXT, approval_id INTEGER, pr_url TEXT, created_at TEXT)""",
]

HTTP_CLIENT: httpx.Client | None = None  # tests inject a mock transport


def ensure_schema(ctx) -> None:
    if not getattr(ctx.store, "_rep_feedback_schema", False):
        for s in SCHEMA:
            ctx.store.execute(s)
        ctx.store._rep_feedback_schema = True


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def repo_root(ctx) -> Path:
    return ctx.manifest.path(cfg(ctx, "repo_root", "../..")).resolve()


def agent_exists(ctx, agent: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", agent or "")) and (repo_root(ctx) / "agents" / agent / "agent.yaml").exists()


def _has(text: str, words: list[str]) -> str | None:
    low = (text or "").lower()
    for w in words:
        if re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", low):
            return w
    return None


def classify(ctx, agent: str, text: str) -> dict:
    """targeting words -> config/icp.yaml; value prop, pain or proof words -> config/company.yaml;
    tone, length, wording and anything else -> the agent's SKILL.md Rules section."""
    w = _has(text, cfg(ctx, "icp_words", []))
    if w:
        return {"target": "config/icp.yaml", "why": f"mentions '{w}' (targeting)"}
    w = _has(text, cfg(ctx, "company_words", []))
    if w:
        return {"target": "config/company.yaml", "why": f"mentions '{w}' (what we sell)"}
    return {"target": f"agents/{agent}/skill/SKILL.md", "why": "tone, length, wording or behavior of this agent"}


def safe_target(path: str) -> bool:
    p = Path(path)
    return not p.is_absolute() and ".." not in p.parts and p.parts[0] != "library" and (
        path in ("config/icp.yaml", "config/company.yaml") or re.fullmatch(r"agents/[a-z0-9-]+/skill/SKILL\.md", path) is not None)


def sanitize(text: str, limit: int = 200) -> str:
    t = (text or "").replace("\u2014", ", ").replace("\u2013", "-").replace(" -- ", ", ")
    t = re.sub(r"[\r\n\t`]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip().strip("\"'")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return t[:1].upper() + t[1:]


def submit(ctx, agent: str, text: str, draft_id: int | None = None, rep: str = "") -> dict:
    ensure_schema(ctx)
    if not agent_exists(ctx, agent):
        return {"error": f"unknown agent '{agent}'"}
    if not (text or "").strip():
        return {"error": "feedback text required"}
    c = classify(ctx, agent, text)
    fid = uuid.uuid4().hex[:10]
    ctx.store.execute("INSERT INTO rep_feedback (id, agent, draft_id, rep, text, target, status, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?)", (fid, agent, draft_id, rep, text.strip(), c["target"], "open", now_iso()))
    return {"feedback_id": fid, **c}


def feedback(ctx, status: str = "") -> list[dict]:
    ensure_schema(ctx)
    if status:
        return ctx.store.query("SELECT * FROM rep_feedback WHERE status=? ORDER BY created_at, id", (status,))
    return ctx.store.query("SELECT * FROM rep_feedback ORDER BY created_at, id")


def apply_rules(content: str, target: str, lines: list[str]) -> str:
    """Insert rule lines: at the end of the '## Rules' section of a SKILL.md, or as review comments at the end of YAML."""
    if target.endswith(".yaml"):
        add = "".join(f"# Rep feedback, encode then remove: {l}\n" for l in lines)
        return content.rstrip("\n") + "\n" + add
    add = [f"- {l}" for l in lines]
    rows = content.rstrip("\n").split("\n")
    start = next((i for i, r in enumerate(rows) if re.match(r"^##\s+Rules\s*$", r)), None)
    if start is None:
        return "\n".join(rows + ["", "## Rules", ""] + add) + "\n"
    end = next((i for i in range(start + 1, len(rows)) if rows[i].startswith("## ")), len(rows))
    last = end
    while last > start + 1 and not rows[last - 1].strip():
        last -= 1
    return "\n".join(rows[:last] + add + rows[last:]) + "\n"


def propose(ctx, feedback_ids: list[str]) -> dict:
    ensure_schema(ctx)
    ids = [str(i) for i in feedback_ids or []]
    if not ids:
        return {"error": "feedback_ids required"}
    rows = [ctx.store.one("SELECT * FROM rep_feedback WHERE id=?", (i,)) for i in ids]
    if any(r is None for r in rows):
        return {"error": f"feedback not found: {[i for i, r in zip(ids, rows) if r is None]}"}
    targets = sorted({r["target"] for r in rows})
    if len(targets) > 1:
        return {"error": "feedback points at different files; propose each group separately", "targets": targets}
    target = targets[0]
    if not safe_target(target):
        return {"error": f"refused: {target} is not an editable file (library/ playbooks are third-party and never edited)"}
    path = repo_root(ctx) / target
    if not path.exists():
        return {"error": f"{target} not found"}
    limit = int(cfg(ctx, "max_rule_chars", 200))
    lines = [sanitize(r["text"], limit) for r in rows]
    old = path.read_text()
    new = apply_rules(old, target, lines)
    patch = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{target}", f"b/{target}"))
    pid = uuid.uuid4().hex[:10]
    ctx.store.execute("INSERT INTO rep_feedback_proposals (id, target, rules, patch, feedback_ids, status, created_at) "
                      "VALUES (?,?,?,?,?,?,?)", (pid, target, json.dumps(lines), patch, json.dumps(ids), "proposed", now_iso()))
    for i in ids:
        ctx.store.execute("UPDATE rep_feedback SET status=?, proposal_id=? WHERE id=?", ("proposed", pid, i))
    return {"proposal_id": pid, "target": target, "rules": lines, "patch": patch}


def open_pr(ctx, proposal_id: str) -> dict:
    ensure_schema(ctx)
    p = ctx.store.one("SELECT * FROM rep_feedback_proposals WHERE id=?", (proposal_id,))
    if not p:
        return {"error": f"proposal '{proposal_id}' not found"}
    if p["status"] not in ("proposed",):
        return {"error": f"proposal is {p['status']}"}
    rules = json.loads(p["rules"])
    payload = {"proposal_id": p["id"], "target": p["target"], "rules": rules,
               "branch": f"{cfg(ctx, 'branch_prefix', 'rep-feedback/')}{p['id']}",
               "title": f"Rep feedback: {p['target']}",
               "body": "Rules proposed from rep feedback:\n\n" + "\n".join(f"- {r}" for r in rules)
                       + f"\n\nFeedback ids: {', '.join(json.loads(p['feedback_ids']))}\n\n```diff\n{p['patch']}```"}
    rid = ctx.request_approval("github_pr", payload, summary=f"open a PR changing {p['target']} ({len(rules)} rule(s))")
    ctx.store.execute("UPDATE rep_feedback_proposals SET status=?, approval_id=? WHERE id=?", ("queued", rid, p["id"]))
    return {"queued_for_approval": rid, "target": p["target"], "branch": payload["branch"]}


def github_pr(ctx, payload: dict, token: str | None, repo: str | None, base: str | None = None) -> dict:
    """Create a branch, commit the rule insertion against the file as it is on GitHub, open a PR."""
    if not token or not repo:
        raise ValueError("set GITHUB_TOKEN and GTM_FEEDBACK_REPO to open pull requests")
    if not safe_target(payload["target"]):
        raise ValueError(f"refused: {payload['target']} is not an editable file")
    http = HTTP_CLIENT or httpx.Client(timeout=30)
    api = f"https://api.github.com/repos/{repo}"
    h = {"authorization": f"Bearer {token}", "accept": "application/vnd.github+json"}

    def call(method, url, **kw):
        r = http.request(method, url, headers=h, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}
    base = base or call("GET", api)["default_branch"]
    sha = call("GET", f"{api}/git/ref/heads/{base}")["object"]["sha"]
    call("POST", f"{api}/git/refs", json={"ref": f"refs/heads/{payload['branch']}", "sha": sha})
    f = call("GET", f"{api}/contents/{payload['target']}", params={"ref": base})
    old = base64.b64decode(f["content"]).decode()
    new = apply_rules(old, payload["target"], payload["rules"])
    call("PUT", f"{api}/contents/{payload['target']}", json={
        "message": payload["title"], "content": base64.b64encode(new.encode()).decode(), "sha": f["sha"],
        "branch": payload["branch"]})
    pr = call("POST", f"{api}/pulls", json={"title": payload["title"], "head": payload["branch"], "base": base,
                                            "body": payload["body"]})
    ensure_schema(ctx)
    ctx.store.execute("UPDATE rep_feedback_proposals SET status=?, pr_url=? WHERE id=?",
                      ("pr_opened", pr.get("html_url"), payload["proposal_id"]))
    ctx.store.execute("UPDATE rep_feedback SET status=? WHERE proposal_id=?", ("pr_opened", payload["proposal_id"]))
    return {"ok": True, "pr": pr.get("html_url"), "number": pr.get("number")}


def digest(ctx) -> dict:
    rows = feedback(ctx)
    by_status, by_target = {}, {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r["status"] == "open":
            by_target[r["target"]] = by_target.get(r["target"], 0) + 1
    return {"total": len(rows), "by_status": by_status, "open_by_target": dict(sorted(by_target.items()))}
