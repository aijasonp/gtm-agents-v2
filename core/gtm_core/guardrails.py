"""Hard limits on agent loops."""
from __future__ import annotations


class LoopLimitExceeded(RuntimeError):
    pass


class StepCounter:
    """Count steps inside one agent task and stop hard at the limit.

    with StepCounter(limit=25) as steps:
        for item in work:
            steps.tick()
    """

    def __init__(self, limit: int = 25):
        self.limit = limit
        self.n = 0

    def tick(self, label: str = "") -> int:
        self.n += 1
        if self.n > self.limit:
            raise LoopLimitExceeded(f"step limit {self.limit} exceeded{': ' + label if label else ''}")
        return self.n

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
