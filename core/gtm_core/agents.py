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
from .connectors import CRM, Slack, get_crm
from .gateway import Gateway
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


def discover(agents_dir: str | Path) -> dict[str, Manifest]:
    out = {}
    for p in sorted(Path(agents_dir).glob("*/agent.yaml")):
        m = Manifest.load(p.parent)
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
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @classmethod
    def build(cls, settings: Settings, manifest: Manifest, store: Store | None = None,
              crm: CRM | None = None, slack: Slack | None = None) -> "Context":
        store = store or Store(settings.database_url)
        store.init()
        slack = slack or Slack(settings)
        b = manifest.budgets or {}
        budgets = Budgets(store, int(b.get("daily_tokens", settings.daily_token_budget)),
                          float(b.get("monthly_usd", settings.monthly_usd_budget)), notify=slack.post)
        return cls(settings, store, manifest, slack, crm or get_crm(settings), budgets,
                   Gateway(settings, budgets, manifest.id), Approvals(store, manifest.id), Audit(store, manifest.id))
