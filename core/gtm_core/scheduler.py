"""Cron scheduler for persistent-edition jobs declared in agent.yaml."""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone

from croniter import croniter

from .agents import Context, Manifest, load_module
from .budgets import BudgetExceeded
from .config import Settings


def run_job(settings: Settings, m: Manifest, job: str, **kw) -> dict:
    mod = load_module(m, "jobs")
    if mod is None or not hasattr(mod, job):
        raise KeyError(f"{m.id} has no job '{job}'")
    ctx = Context.build(settings, m, **kw)
    ctx.audit.log("job.start", job=job, run_id=ctx.run_id)
    with ctx.store.run(ctx.run_id, m.id, job) as stats:
        result = getattr(mod, job)(ctx) or {}
        stats.update(result)
    ctx.audit.log("job.done", job=job, run_id=ctx.run_id, **{k: v for k, v in result.items() if k != "ranked"})
    return result


def due_jobs(manifests: dict[str, Manifest], last: datetime, now: datetime) -> list[tuple[Manifest, str]]:
    out = []
    for m in manifests.values():
        if "persistent" not in m.editions:
            continue
        for j in m.jobs:
            it = croniter(j["cron"], last)
            if it.get_next(datetime) <= now:
                out.append((m, j["name"]))
    return out


def loop(settings: Settings, manifests: dict[str, Manifest], tick_seconds: int = 30) -> None:  # pragma: no cover
    from .workflows import launch_backend
    last = datetime.now(timezone.utc)
    backend = launch_backend(settings)
    print(f"scheduler started with {sum(len(m.jobs) for m in manifests.values())} jobs, workflows: {backend}")
    while True:
        time.sleep(tick_seconds)
        now = datetime.now(timezone.utc)
        for m, job in due_jobs(manifests, last, now):
            try:
                print(f"{now.isoformat()} running {m.id}.{job}")
                run_job(settings, m, job)
            except BudgetExceeded as e:
                print(f"paused: {e}")
            except Exception:
                traceback.print_exc()
        last = now
