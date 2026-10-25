"""Agent manifests and the runtime context every job and tool receives."""
from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import yaml

from .approvals import Approvals
from .audit import Audit
from .budgets import Budgets
from .config import Settings
from .connectors import CRM, Dialer, Sequencer, Slack, get_crm, get_dialer, get_sequencer
from .gateway import Gateway
from .handoffs import Handoffs
from .store import Store

REQUIRED = {"id", "name", "version", "tier", "editions", "skill"}


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    tier: str
    editions: list[str]
    skill: str
    description: str = ""
    references: list[str] = field(default_factory=list)
    library: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    connectors_required: list[str] = field(default_factory=list)
    connectors_optional: list[str] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    budgets: dict = field(default_factory=dict)
    evals: str | None = None
    config: dict = field(default_factory=dict)
    root: Path = Path(".")

    @classmethod
    def load(cls, agent_dir: str | Path) -> "Manifest":
        root = Path(agent_dir)
        data = yaml.safe_load((root / "agent.yaml").read_text())
        missing = REQUIRED - set(data)
        if missing:
            raise ValueError(f"{root}/agent.yaml missing: {', '.join(sorted(missing))}")
        known = set(cls.__dataclass_fields__) - {"root"}
        m = cls(**{k: v for k, v in data.items() if k in known})
        m.root = root
        for rel in [m.skill, *m.references]:
            if not (root / rel).exists():
                raise FileNotFoundError(f"{m.id}: {rel} not found")
        return m

    def path(self, rel: str) -> Path:
        return self.root / rel


DISCOVERY_ERRORS: dict[str, str] = {}


def discover(agents_dir: str | Path, strict: bool = False) -> dict[str, Manifest]:
    """Load every agents/<id>/agent.yaml. A broken agent is skipped with a warning so the rest keep
    running; strict=True raises instead (used by the release tests)."""
    out = {}
    DISCOVERY_ERRORS.clear()
    for p in sorted(Path(agents_dir).glob("*/agent.yaml")):
        try:
            m = Manifest.load(p.parent)
        except Exception as e:
            if strict:
                raise
            DISCOVERY_ERRORS[p.parent.name] = str(e)
            print(f"warning: skipping agent {p.parent.name}: {e}", file=sys.stderr)
            continue
        out[m.id] = m
    return out


def load_module(m: Manifest, name: str) -> ModuleType | None:
    """Import agents/<id>/<name>.py (jobs.py, tools.py) as a module."""
    f = m.root / f"{name}.py"
    if not f.exists():
        return None
    mod_name = f"gtm_agent_{m.id.replace('-', '_')}_{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, f)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Context:
    settings: Settings
    store: Store
    manifest: Manifest
    slack: Slack
    crm: CRM
    budgets: Budgets
    gateway: Gateway
    approvals: Approvals
    audit: Audit
    handoffs: Handoffs = None
    sequencer: Sequencer = None
    dialer: Dialer = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # Actions that only ever reduce contact with a person run at once (still logged in the queue).
    AUTO_SAFE = ("sequence_stop",)

    def request_approval(self, action: str, payload: dict, summary: str = "", auto_safe: bool = False) -> int:
        """Queue a write for human approval and tell the approval channel about it.
        auto_safe=True executes now for actions in AUTO_SAFE (stopping a sequence after an opt-out)."""
        rid = self.approvals.request(action, payload)
        if auto_safe and action in self.AUTO_SAFE:
            from .executors import register_core_executors
            register_core_executors(self)
            self.approvals.decide(rid, True, by="auto:safety")
            self.approvals.execute_one(rid)
            return rid
        if summary:
            try:
                self.slack.post(f":inbox_tray: Approval #{rid} ({self.manifest.name}): {summary}\n"
                                f"Review: `gtm approvals {self.manifest.id} list`")
            except Exception as e:  # approval is queued either way
                self.audit.log("slack.error", error=str(e)[:200])
        return rid

    @classmethod
    def build(cls, settings: Settings, manifest: Manifest, store: Store | None = None,
              crm: CRM | None = None, slack: Slack | None = None, sequencer: Sequencer | None = None,
              dialer: Dialer | None = None) -> "Context":
        store = store or Store(settings.database_url)
        store.init()
        slack = slack or Slack(settings)
        b = manifest.budgets or {}
        budgets = Budgets(store, int(b.get("daily_tokens", settings.daily_token_budget)),
                          float(b.get("monthly_usd", settings.monthly_usd_budget)), notify=slack.post,
                          agent=manifest.id)
        return cls(settings, store, manifest, slack, crm or get_crm(settings), budgets,
                   Gateway(settings, budgets, manifest.id), Approvals(store, manifest.id), Audit(store, manifest.id),
                   Handoffs(store, manifest.id), sequencer or get_sequencer(), dialer or get_dialer())
