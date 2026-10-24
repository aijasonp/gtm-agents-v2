"""Runtime settings, read from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, no overrides of existing env vars."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///gtm.db"))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("GTM_DATA_DIR", "data")))
    agents_dir: Path = field(default_factory=lambda: Path(os.environ.get("GTM_AGENTS_DIR", "agents")))

    # model gateway
    anthropic_api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY"))
    openai_base_url: str = field(default_factory=lambda: os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    model_cheap: str = field(default_factory=lambda: os.environ.get("GTM_MODEL_CHEAP", "claude-haiku-5-5"))
    model_frontier: str = field(default_factory=lambda: os.environ.get("GTM_MODEL_FRONTIER", "claude-sonnet-5-5"))

    # budgets (0 = unlimited)
    daily_token_budget: int = field(default_factory=lambda: _int("GTM_DAILY_TOKEN_BUDGET", 2_000_000))
    monthly_usd_budget: float = field(default_factory=lambda: _float("GTM_MONTHLY_USD_BUDGET", 150.0))

    # connectors
    crm: str = field(default_factory=lambda: os.environ.get("GTM_CRM", "hubspot"))
    hubspot_token: str | None = field(default_factory=lambda: os.environ.get("HUBSPOT_TOKEN"))
    salesforce_instance_url: str | None = field(default_factory=lambda: os.environ.get("SALESFORCE_INSTANCE_URL"))
    salesforce_token: str | None = field(default_factory=lambda: os.environ.get("SALESFORCE_ACCESS_TOKEN"))
    slack_webhook_url: str | None = field(default_factory=lambda: os.environ.get("SLACK_WEBHOOK_URL"))
    slack_bot_token: str | None = field(default_factory=lambda: os.environ.get("SLACK_BOT_TOKEN"))
    slack_channel: str = field(default_factory=lambda: os.environ.get("SLACK_CHANNEL", "#gtm-signals"))

    # licensing
    license_path: Path = field(default_factory=lambda: Path(os.environ.get("GTM_LICENSE_PATH", "license.json")))

    # guardrails
    max_loop_steps: int = field(default_factory=lambda: _int("GTM_MAX_LOOP_STEPS", 25))


def get_settings() -> Settings:
    load_dotenv()
    return Settings()
