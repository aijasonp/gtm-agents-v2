"""Shared customer configuration: who we sell to (config/icp.yaml) and what we sell (config/company.yaml).

Agents point at these through agent.yaml config keys `company` and `icp`, so the customer
edits one file and every agent picks it up.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml


@lru_cache(maxsize=16)
def _load(path: str) -> dict:
    p = Path(path)
    return yaml.safe_load(p.read_text()) or {} if p.exists() else {}


def company(ctx) -> dict:
    return _load(str(ctx.manifest.path(ctx.manifest.config.get("company", "../../config/company.yaml"))))


def icp_path(ctx) -> Path:
    return ctx.manifest.path(ctx.manifest.config.get("icp", "../../config/icp.yaml"))


def competitors(ctx) -> list[str]:
    return [c["name"] if isinstance(c, dict) else str(c) for c in company(ctx).get("competitors", [])]


def rep_names(ctx) -> list[str]:
    return company(ctx).get("team", {}).get("rep_names", [])


def sender(ctx) -> dict:
    return company(ctx).get("sender", {})
