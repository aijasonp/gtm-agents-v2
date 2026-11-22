"""Opportunity Analyst scheduled job: keep the store in step with the CRM (read only)."""
from __future__ import annotations

from gtm_core.sync import sync_all


def sync_opportunities(ctx) -> dict:
    """Incremental pull of accounts, contacts, opportunities and stage history."""
    return sync_all(ctx)


def weekly_full_sync(ctx) -> dict:
    """Full re-pull, so deletes and merges in the CRM never leave stale rows counted."""
    return sync_all(ctx, full=True)
