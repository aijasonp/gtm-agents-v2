"""Autonomy levels per motion and the STOP switch. Plain code, read on every request and every execute.

`level(action, agent, payload)` says how a new approval request is handled (config/autonomy.yaml):
off (closed at once), approve (a person decides, the default) or auto (approved by autonomy:auto, only for
actions in `auto_allowed`, never for a send to a buyer).

`stopped(store, ...)` says whether STOP holds an action, an agent's job or everything. STOP comes from the
STOP file, the GTM_STOP environment variable, or the store (`gtm stop`, POST /v1/stop). Executors check it
right before running, so approved rows simply wait. The scheduler checks it before every job.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import yaml

from .approval_policy import Policy, config_dir
from .store import Store, now_iso

LEVELS = ("off", "approve", "auto")
STATE_KEY = "autonomy:stop"
DEFAULTS = {"default": "approve", "motions": {}, "actions": {}, "agents": {}, "agent_motion": {}, "action_motion": {},
            "auto_allowed": [], "stop": {"file": "data/STOP", "always_allowed": ["sequence_stop"],
                                         "jobs_allowed": ["ops-monitor.*"]}}


class AutonomyError(ValueError):
    pass


class Autonomy:
    def __init__(self, rules: dict, send_actions: set[str], base: Path):
        self.rules, self.send_actions, self.base = rules, send_actions, base
        for where in ("motions", "actions", "agents"):
            for k, v in (rules.get(where) or {}).items():
                if v not in LEVELS:
                    raise AutonomyError(f"autonomy.yaml {where}.{k}: {v!r} is not one of {LEVELS}")
                if v == "auto" and where == "actions" and k in send_actions:
                    raise AutonomyError(f"autonomy.yaml actions.{k}: sends to a buyer can never be auto")
        if rules.get("default") not in LEVELS:
            raise AutonomyError(f"autonomy.yaml default: {rules.get('default')!r} is not one of {LEVELS}")
        bad = set(rules.get("auto_allowed") or []) & send_actions
        if bad:
            raise AutonomyError(f"autonomy.yaml auto_allowed lists sends to a buyer: {sorted(bad)}")

    @classmethod
    def load(cls, base: str | Path | None = None) -> "Autonomy":
        base = Path(base) if base else config_dir()
        rules = {**DEFAULTS}
        try:
            rules.update(yaml.safe_load((base / "autonomy.yaml").read_text()) or {})
        except FileNotFoundError:
            pass
        rules["stop"] = {**DEFAULTS["stop"], **(rules.get("stop") or {})}
        pol = Policy.load(base)
        return cls(rules, set(pol.rules.get("send_actions") or []), base)

    def motion(self, action: str, agent: str, payload: dict | None = None) -> str:
        """Payload `motion` when it names a configured motion, else the action's motion, else the agent's."""
        m = (payload or {}).get("motion")
        if m and m in (self.rules.get("motions") or {}):
            return str(m)
        return str((self.rules.get("action_motion") or {}).get(action)
                   or (self.rules.get("agent_motion") or {}).get(agent) or "other")

    def level(self, action: str, agent: str, payload: dict | None = None) -> tuple[str, str]:
        """(level, where it came from). An `auto` that is not allowed for this action falls back to approve."""
        r = self.rules
        if action in set(r["stop"].get("always_allowed") or []):
            return "approve", "safety action (only reduces contact)"
        motion = self.motion(action, agent, payload)
        for where, key in (("agents", agent), ("actions", action), ("motions", motion)):
            v = (r.get(where) or {}).get(key)
            if v:
                found = (v, f"{where}.{key}")
                break
        else:
            found = (r.get("default", "approve"), "default")
        if found[0] == "auto" and (action in self.send_actions or action not in set(r.get("auto_allowed") or [])):
            return "approve", found[1] + " (auto not allowed for this action)"
        return found

    # ---------- STOP ----------
    def _file(self) -> Path:
        p = Path(self.rules["stop"].get("file") or "data/STOP")
        return p if p.is_absolute() else Path(os.environ.get("GTM_ROOT", ".")) / p

    def stop_state(self, store: Store | None) -> dict | None:
        """{scopes: [...] or ["all"], source, reason, by, at} when STOP is on, else None."""
        env = (os.environ.get("GTM_STOP") or "").strip()
        if env and env.lower() not in ("0", "false", "off", "no"):
            scopes = ["all"] if env.lower() in ("1", "true", "yes", "all", "on") else _split(env)
            return {"scopes": scopes, "source": "env GTM_STOP"}
        f = self._file()
        if f.exists():
            lines = [ln.strip() for ln in f.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
            return {"scopes": _split(",".join(lines)) or ["all"], "source": f"file {f}"}
        if store is not None:
            try:
                st = store.get_state(STATE_KEY)
            except Exception:
                st = None
            if st and st.get("on"):
                return {"scopes": st.get("scopes") or ["all"], "source": "gtm stop", "reason": st.get("reason"),
                        "by": st.get("by"), "at": st.get("at")}
        return None

    def stopped(self, store: Store | None, action: str | None = None, agent: str | None = None,
                payload: dict | None = None, job: str | None = None) -> str | None:
        """Why STOP holds this action or job, or None."""
        st = self.stop_state(store)
        if not st:
            return None
        if action and action in set(self.rules["stop"].get("always_allowed") or []):
            return None
        scopes = set(st["scopes"])
        if job and agent:
            if any(fnmatch.fnmatch(f"{agent}.{job}", pat) for pat in self.rules["stop"].get("jobs_allowed") or []):
                return None
        hit = "all" in scopes or bool(scopes & {action, agent, self.motion(action or "", agent or "", payload)} - {None})
        if not hit:
            return None
        why = f"STOP is on ({st['source']}" + (f": {st['reason']}" if st.get("reason") else "") + ")"
        return why


def _split(text: str) -> list[str]:
    return [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]


def stop(store: Store, by: str, reason: str = "", scopes: list[str] | None = None) -> dict:
    st = {"on": True, "scopes": scopes or ["all"], "reason": reason, "by": by, "at": now_iso()}
    store.set_state(STATE_KEY, st)
    from .audit import Audit
    Audit(store, "core").log("autonomy.stop", by=by, reason=reason, scopes=st["scopes"])
    return st


def resume(store: Store, by: str) -> dict:
    prev = store.get_state(STATE_KEY) or {}
    store.set_state(STATE_KEY, {"on": False, "resumed_by": by, "at": now_iso()})
    from .audit import Audit
    Audit(store, "core").log("autonomy.resume", by=by)
    still = Autonomy.load().stop_state(None)  # the file or env var still on means STOP holds regardless
    return {"resumed": bool(prev.get("on")), "still_stopped_by": still["source"] if still else None}


_cached: dict = {}


def current() -> Autonomy:
    """Loaded once per config directory and file mtime, so edits apply without a restart."""
    base = config_dir()
    p = base / "autonomy.yaml"
    key = (str(base), p.stat().st_mtime if p.exists() else 0,
           (base / "approvals.yaml").stat().st_mtime if (base / "approvals.yaml").exists() else 0)
    if _cached.get("key") != key:
        _cached.update(key=key, value=Autonomy.load(base))
    return _cached["value"]
