"""Approval policy: named approvers for sends, owners confirming their own pipeline emails.

config/approvals.yaml sets the rules and config/company.yaml names the people (team.owners, team.manager).
Approvers are resolved to a person by name, email or Slack id (`slack:U123` matches an owner's `slack_id`).
Anything that does not resolve to a person (operator, system, a shared API token's name) cannot approve a send.

check() runs when a decision is made; send_guard() runs again right before a send executes, so a row approved
outside the queue (a hand-edited database, an old client) still does not reach a buyer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULTS = {
    "named_approver": "required",
    "send_actions": ["sequence_enroll", "sequence_step", "pipeline_email", "dialer_enqueue", "proposal_send",
                     "social_post"],
    "owner_confirms": ["pipeline_email", "sequence_step"],
    "managers_can_confirm": True,
    "delegates": {},
    "extra_approvers": [],
    "sequence_release": "all",
    "step_gap_business_days": 3,
}
SAFETY = "auto:safety"


class ApprovalRefused(ValueError):
    """The approver may not approve this action. Nothing changed."""


def config_dir() -> Path:
    return Path(os.environ.get("GTM_CONFIG_DIR", "config"))


@dataclass
class Policy:
    rules: dict = field(default_factory=lambda: dict(DEFAULTS))
    people: dict[str, dict] = field(default_factory=dict)   # canonical name -> person
    manager: str | None = None

    @classmethod
    def load(cls, base: str | Path | None = None) -> "Policy":
        base = Path(base) if base else config_dir()
        rules = dict(DEFAULTS)
        try:
            rules.update(yaml.safe_load((base / "approvals.yaml").read_text()) or {})
        except FileNotFoundError:
            pass
        team = {}
        try:
            team = (yaml.safe_load((base / "company.yaml").read_text()) or {}).get("team", {}) or {}
        except FileNotFoundError:
            pass
        people = {o["name"]: dict(o) for o in team.get("owners", []) if o.get("name")}
        mgr = team.get("manager")
        mname = (mgr.get("name") if isinstance(mgr, dict) else mgr) or None
        if mname:
            people.setdefault(mname, mgr if isinstance(mgr, dict) else {"name": mname})
        for n in rules.get("extra_approvers") or []:
            if isinstance(n, dict) and n.get("name"):
                people.setdefault(n["name"], n)
            elif isinstance(n, str):
                people.setdefault(n, {"name": n})
        return cls(rules, people, mname)

    @property
    def mode(self) -> str:
        return str(self.rules.get("named_approver", "required")).lower()

    def is_send(self, action: str) -> bool:
        return action in set(self.rules.get("send_actions") or [])

    def person(self, by: str | None) -> str | None:
        """The canonical team member behind an approver string, or None."""
        b = (by or "").strip()
        if not b:
            return None
        low = b.lower()
        slack = low[6:] if low.startswith("slack:") else None
        for name, p in self.people.items():
            if low == name.lower() or low == (p.get("email") or "").lower():
                return name
            if slack and slack == str(p.get("slack_id") or "").lower():
                return name
        return None

    def check(self, action: str, payload: dict, by: str) -> tuple[str | None, str]:
        """(refusal reason or None, the name to record). Rejections are always allowed."""
        if by == SAFETY or not self.is_send(action) or self.mode == "off":
            return None, by
        who = self.person(by)
        if not who:
            why = (f"{action} sends to a buyer and needs a named approver from the team; {by!r} is not one "
                   f"(approve with --by \"<your name>\", a personal API token, or a Slack id on your team entry)")
            return (why if self.mode == "required" else None), by
        if action in set(self.rules.get("owner_confirms") or []):
            owner = self.person(payload.get("approver") or payload.get("owner"))
            if owner and who != owner:
                ok = who in ((self.rules.get("delegates") or {}).get(owner) or []) or \
                    (self.rules.get("managers_can_confirm", True) and who == self.manager)
                if not ok:
                    why = f"{action} is {owner}'s to confirm; {who} is not a delegate or the manager"
                    return (why if self.mode == "required" else None), who
        return None, who

    def send_guard(self, action: str, decided_by: str | None, payload: dict | None = None) -> str | None:
        """Refusal reason at send time, or None. The recorded approver must still resolve to a person, and with
        the payload the full check (owner, delegate or manager) runs again."""
        if not self.is_send(action) or self.mode != "required":
            return None
        if not self.person(decided_by):
            return f"send refused: {action} has no named approver on record (decided_by={decided_by!r})"
        if payload is not None:
            why, _ = self.check(action, payload, decided_by)
            if why:
                return f"send refused: {why}"
        return None
