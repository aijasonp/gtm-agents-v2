"""Token and spend budgets. When a budget is hit the agent pauses and alerts Slack."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .store import Store, now_iso

# USD per million tokens (input, output). Defaults only: set GTM_MODEL_PRICES to the
# customer's contract rates, e.g. '{"claude-sonnet-5-5": [3, 15]}'.
DEFAULT_PRICES = {"cheap": (1.0, 5.0), "frontier": (3.0, 15.0)}


class BudgetExceeded(RuntimeError):
    pass


def _prices() -> dict:
    try:
        return json.loads(os.environ.get("GTM_MODEL_PRICES", "{}"))
    except json.JSONDecodeError:
        return {}


def cost_usd(model: str, model_class: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = _prices().get(model) or DEFAULT_PRICES.get(model_class, DEFAULT_PRICES["frontier"])
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 6)


class Budgets:
    def __init__(self, store: Store, daily_tokens: int = 0, monthly_usd: float = 0.0, notify=None):
        self.store = store
        self.daily_tokens = daily_tokens
        self.monthly_usd = monthly_usd
        self.notify = notify  # callable(text) for the Slack alert

    def usage(self) -> dict:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month = today[:7]
        d = self.store.one("SELECT COALESCE(SUM(input_tokens+output_tokens),0) AS t FROM token_usage WHERE ts LIKE ?",
                           (today + "%",))
        m = self.store.one("SELECT COALESCE(SUM(usd),0) AS u FROM token_usage WHERE ts LIKE ?", (month + "%",))
        return {"tokens_today": int(d["t"]), "usd_month": float(m["u"])}

    def paused(self) -> bool:
        return bool(self.store.get_state("paused", False))

    def check(self, agent: str = "core") -> None:
        if self.paused():
            raise BudgetExceeded("agent runtime is paused (budget hit); run `gtm resume` after review")
        u = self.usage()
        reason = None
        if self.daily_tokens and u["tokens_today"] >= self.daily_tokens:
            reason = f"daily token budget reached ({u['tokens_today']:,} of {self.daily_tokens:,})"
        elif self.monthly_usd and u["usd_month"] >= self.monthly_usd:
            reason = f"monthly spend budget reached (${u['usd_month']:.2f} of ${self.monthly_usd:.2f})"
        if reason:
            self.store.set_state("paused", True)
            if self.notify:
                try:
                    self.notify(f":pause_button: GTM agents paused: {reason}. Run `gtm resume` to continue.")
                except Exception:
                    pass
            raise BudgetExceeded(reason)

    def record(self, agent: str, model: str, model_class: str, input_tokens: int, output_tokens: int) -> float:
        usd = cost_usd(model, model_class, input_tokens, output_tokens)
        self.store.insert(
            "INSERT INTO token_usage (ts, agent, model, input_tokens, output_tokens, usd) VALUES (?,?,?,?,?,?)",
            (now_iso(), agent, model, input_tokens, output_tokens, usd))
        return usd

    def resume(self) -> None:
        self.store.set_state("paused", False)
