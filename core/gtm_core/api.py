"""Small HTTP API for the persistent edition (stdlib only, runs inside the customer's network).

Lets the customer's existing tools push work in and lets approvers act without a shell:

  POST /v1/leads                      JSON lead or list of leads (web form, event app, Clay, Zapier)
  POST /v1/meetings                   JSON {id, transcript, account_id?, deal_id?, title?, started_at?, owner?}
  POST /v1/signals                    JSON signal or list (account_id, signal_type, observed_at, url?, title?)
  POST /v1/replies                    JSON reply or list (from_email, subject, body, received_at...) -> Reply Desk
  POST /v1/engagement                 JSON engagement row or list (platform, post_url, engager_name...) -> Social Signals
  GET  /v1/approvals?status=pending   approval queue across agents
  POST /v1/approvals/<id>/approve     body {"by": "name"} optional
  POST /v1/approvals/<id>/reject
  POST /v1/approvals/execute          run every approved action
  GET  /v1/health

Two tokens, two roles:
  GTM_API_TOKEN           intake only (leads, meetings, signals, health). Safe to give web forms,
                          event apps, Clay or Zapier.
  GTM_API_APPROVER_TOKEN  approval queue. Unset = approvals over HTTP are off. Decisions are recorded
                          under GTM_API_APPROVER_NAME, never a name sent in the request.
  GTM_API_ALLOW_EXECUTE=1 additionally lets the approver token run approved actions over HTTP.
Without GTM_API_TOKEN the API refuses to start. Bind it to an internal interface or put it behind
the customer's proxy.
"""
from __future__ import annotations

import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agents import Context, discover
from .config import Settings
from .importers import lead_id
from .scoring import signal_id
from .store import Store, now_iso

MAX_BODY = 5 * 1024 * 1024


class BadRequest(ValueError):
    pass


def _rows(body) -> list[dict]:
    rows = body if isinstance(body, list) else [body]
    if not rows or not all(isinstance(r, dict) for r in rows):
        raise BadRequest("body must be a JSON object or a list of objects")
    for r in rows:
        for k, v in r.items():
            if not isinstance(k, str) or (v is not None and not isinstance(v, (str, int, float, bool, list))):
                raise BadRequest(f"field {k!r} has an unsupported type")
    return rows


def _str(v) -> str:
    return v.strip() if isinstance(v, str) else ""


class Api:
    def __init__(self, settings: Settings, token: str, store: Store | None = None, approver_token: str | None = None,
                 approver_name: str = "api-approver", allow_execute: bool = False):
        if not token:
            raise RuntimeError("set GTM_API_TOKEN before starting the API")
        if approver_token and hmac.compare_digest(approver_token, token):
            raise RuntimeError("GTM_API_APPROVER_TOKEN must differ from GTM_API_TOKEN")
        self.s = settings
        self.token = token
        self.approver_token = approver_token or None
        self.approver_name = approver_name
        self.allow_execute = allow_execute
        self.store = store or Store(settings.database_url)
        self.store.init()
        self.manifests = discover(settings.agents_dir)

    def ctx(self, agent_id: str) -> Context:
        m = self.manifests.get(agent_id) or next(iter(self.manifests.values()))
        return Context.build(self.s, m, store=self.store)

    # ---- handlers return (status, body) ----
    def leads(self, body) -> tuple[int, dict]:
        rows = _rows(body)
        added, dupes, errors = [], 0, []
        for r in rows:
            email = _str(r.get("email")).lower()
            if "@" not in email:
                errors.append({"lead": r.get("name"), "error": "email required"})
                continue
            row = {**{k: v for k, v in r.items() if v not in (None, "")}, "email": email,
                   "domain": email.split("@", 1)[1], "received_at": r.get("received_at") or now_iso(), "status": "new"}
            row["id"] = r.get("id") or lead_id(row)
            if self.store.get("leads", row["id"]):
                dupes += 1
                continue
            self.store.upsert("leads", row)
            added.append(row["id"])
        triaged = []
        if added and os.environ.get("GTM_API_TRIAGE_NOW", "1") == "1" and "lead-triage" in self.manifests:
            from .agents import load_module
            ctx = self.ctx("lead-triage")
            eng = load_module(ctx.manifest, "engine")
            for lid in added:
                r = eng.process(ctx, self.store.get("leads", lid))
                if not r.get("skipped"):
                    triaged.append({"lead_id": lid, "tier": r["tier"], "owner": r["owner"], "approvals": r["approvals"]})
        return 201 if added else 200, {"added": added, "duplicates": dupes, "errors": errors, "triaged": triaged}

    def meetings(self, body) -> tuple[int, dict]:
        rows = _rows(body)
        n = 0
        for r in rows:
            if not _str(r.get("id")) or not _str(r.get("transcript")):
                continue
            if isinstance(r.get("attendees"), str):
                r["attendees"] = [a.strip() for a in r["attendees"].replace(";", ",").split(",") if a.strip()]
            # processed_at=None clears it, so a re-sent transcript is analyzed again
            self.store.upsert("meetings", {**r, "source": r.get("source", "api"), "processed_at": None})
            n += 1
        return (201 if n else 400), {"meetings": n}

    def signals(self, body) -> tuple[int, dict]:
        rows = _rows(body)
        if "signal-scout" not in self.manifests:
            return 400, {"error": "signal-scout agent not installed"}
        from .agents import load_module
        ctx = self.ctx("signal-scout")
        tax = load_module(ctx.manifest, "engine").taxonomy(ctx)
        added = dupes = unknown = 0
        for r in rows:
            st = r.get("signal_type")
            if st not in tax.types or not r.get("account_id") or not self.store.account(str(r["account_id"])):
                unknown += 1
                continue
            obs = r.get("observed_at") or now_iso()
            sig = {"id": signal_id(r["account_id"], st, r.get("url") or r.get("title") or "", obs),
                   "account_id": r["account_id"], "signal_type": st, "category": tax.types[st].category,
                   "source": r.get("source", "api"), "url": r.get("url"), "observed_at": obs,
                   "strength": r.get("strength"), "payload": {"title": r.get("title", "")}}
            try:
                ok = self.store.add_signal(sig)
            except ValueError:
                unknown += 1
                continue
            added, dupes = (added + 1, dupes) if ok else (added, dupes + 1)
        return 200, {"added": added, "duplicates": dupes, "rejected": unknown}

    def to_inbox(self, agent: str, key: str, body, required: tuple[str, ...]) -> tuple[int, dict]:
        """Drop rows into an agent's inbox folder; its scheduled job ingests and archives them."""
        import uuid
        from pathlib import Path
        if agent not in self.manifests:
            return 400, {"error": f"{agent} agent not installed"}
        rows = _rows(body)
        def flat(v):
            if isinstance(v, list):
                return ", ".join(str(x) for x in v)
            return v if v is None or isinstance(v, (str, int, float, bool)) else str(v)
        good = [{k: flat(v) for k, v in r.items()} for r in rows if all(_str(r.get(k)) for k in required)]
        if not good:
            return 400, {"error": f"each row needs {', '.join(required)}"}
        inbox = Path(self.manifests[agent].config.get(key, f"data/{agent}/inbox"))
        inbox.mkdir(parents=True, exist_ok=True)
        name = f"api-{uuid.uuid4().hex}"
        f, tmp = inbox / f"{name}.json", inbox / f".{name}.tmp"  # unique per request, safe across threads
        tmp.write_text(json.dumps(good, default=str))
        tmp.rename(f)  # atomic: the job never reads a half-written file
        return 202, {"queued": len(good), "rejected": len(rows) - len(good), "agent": agent}

    def approvals(self, status: str | None) -> tuple[int, dict]:
        from .approvals import Approvals
        rows = Approvals(self.store, "core").list(status or None, all_agents=True)
        return 200, {"approvals": rows}

    def decide(self, rid: int, approve: bool) -> tuple[int, dict]:
        from .approvals import Approvals
        try:
            Approvals(self.store, "core").decide(rid, approve, by=self.approver_name)
        except KeyError as e:
            return 404, {"error": str(e)}
        except ValueError as e:
            return 409, {"error": str(e)}
        return 200, {"id": rid, "status": "approved" if approve else "rejected"}

    def execute(self) -> tuple[int, dict]:
        from .agents import load_module
        from .executors import register_core_executors
        ctx = self.ctx("signal-scout" if "signal-scout" in self.manifests else next(iter(self.manifests)))
        register_core_executors(ctx)
        for m in self.manifests.values():
            jobs = load_module(m, "jobs")
            if jobs is not None and hasattr(jobs, "register_executors"):
                jobs.register_executors(Context.build(self.s, m, store=self.store))
        register_core_executors(ctx)  # core executors win for shared action names
        return 200, {"results": ctx.approvals.execute_approved()}

    def role(self, auth: str) -> str | None:
        if self.approver_token and hmac.compare_digest(auth, f"Bearer {self.approver_token}"):
            return "approver"
        if hmac.compare_digest(auth, f"Bearer {self.token}"):
            return "intake"
        return None

    def route(self, method: str, path: str, query: dict, body, role: str = "intake") -> tuple[int, dict]:
        if method == "GET" and path == "/v1/health":
            return 200, {"ok": True, "agents": sorted(self.manifests)}
        intake = {"/v1/leads": self.leads, "/v1/meetings": self.meetings, "/v1/signals": self.signals,
                  "/v1/replies": lambda b: self.to_inbox("reply-desk", "reply_inbox", b, ("from_email", "body")),
                  "/v1/engagement": lambda b: self.to_inbox("social-signals", "engagement_inbox", b,
                                                            ("engager_name", "engagement_type"))}
        if method == "POST" and path in intake:
            if body is None:
                return 400, {"error": "JSON body required"}
            try:
                return intake[path](body)
            except BadRequest as e:
                return 400, {"error": str(e)}
        if path.startswith("/v1/approvals"):
            if role != "approver":
                return 403, {"error": "approvals need the approver token (GTM_API_APPROVER_TOKEN)"}
            if method == "GET" and path == "/v1/approvals":
                return self.approvals(query.get("status", "pending"))
            if method == "POST" and path == "/v1/approvals/execute":
                if not self.allow_execute:
                    return 403, {"error": "execute over HTTP is off; set GTM_API_ALLOW_EXECUTE=1 or use `gtm approvals`"}
                return self.execute()
            m = re.match(r"^/v1/approvals/(\d+)/(approve|reject)$", path)
            if method == "POST" and m:
                return self.decide(int(m.group(1)), m.group(2) == "approve")
        return 404, {"error": "not found"}


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict):
            data = json.dumps(body, default=str).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str):
            role = api.role(self.headers.get("authorization", ""))
            if role is None:
                return self._send(401, {"error": "unauthorized"})
            path, _, qs = self.path.partition("?")
            query = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            body = None
            try:
                n = int(self.headers.get("content-length") or 0)
            except ValueError:
                return self._send(400, {"error": "bad content-length"})
            if n < 0:
                return self._send(400, {"error": "bad content-length"})
            if n > MAX_BODY:
                return self._send(413, {"error": "body too large"})
            if n:
                try:
                    body = json.loads(self.rfile.read(n))
                except json.JSONDecodeError:
                    return self._send(400, {"error": "invalid JSON"})
            try:
                status, out = api.route(method, path, query, body, role)
            except Exception as e:  # never leak a traceback to the caller
                status, out = 500, {"error": type(e).__name__}
            self._send(status, out)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def log_message(self, fmt, *args):  # keep request logs out of stdout noise
            pass

    return Handler


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8787) -> None:  # pragma: no cover
    api = Api(settings, os.environ.get("GTM_API_TOKEN", ""), approver_token=os.environ.get("GTM_API_APPROVER_TOKEN"),
              approver_name=os.environ.get("GTM_API_APPROVER_NAME", "api-approver"),
              allow_execute=os.environ.get("GTM_API_ALLOW_EXECUTE") == "1")
    print(f"gtm api listening on {host}:{port}")
    ThreadingHTTPServer((host, port), make_handler(api)).serve_forever()
