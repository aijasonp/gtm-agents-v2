"""Product Marketing evaluator: seed evidence, call engine functions, compare result paths."""
from __future__ import annotations

from datetime import datetime

from gtm_core.agents import load_module


def _get(obj, path: str):
    for part in [p for p in str(path).split(".") if p != ""]:
        if isinstance(obj, (list, tuple)):
            obj = obj[int(part)]
        else:
            obj = obj[part]
    return obj


def _compare(op: str, got, want) -> bool:
    if op == "eq":
        return got == want if not isinstance(got, tuple) else list(got) == want
    if op == "contains":
        return str(want).lower() in str(got).lower()
    if op == "contains_all":
        return all(str(w).lower() in str(got).lower() for w in want)
    if op == "any_contains":
        return any(str(want).lower() in str(g).lower() for g in got)
    if op == "len_lte":
        return len(got) <= want
    if op == "truthy":
        return bool(got)
    if op == "not_has_category":
        return all(r["category"] != want for r in got)
    raise ValueError(f"unknown op {op}")


def seed(ctx, spec: dict) -> None:
    for a in spec.get("accounts", []):
        ctx.store.upsert_account(a)
    for c in spec.get("contacts", []):
        ctx.store.upsert("contacts", c)
    for d in spec.get("deals", []):
        ctx.store.upsert("deals", d)
    for i in spec.get("insights", []):
        i = dict(i)
        ctx.store.add_insight("meeting-intelligence", i.pop("kind"), i.pop("key"), evidence=i.pop("evidence", ""),
                              observed_at=i.pop("observed_at"), **i)


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    seed(ctx, spec)
    eng = load_module(m, "engine")
    now = datetime.fromisoformat(spec["now"])
    out = []
    for c in spec["checks"]:
        try:
            res = getattr(eng, c["call"])(ctx, **c.get("args", {}), now=now) if c["call"] != "launch_brief" \
                else eng.launch_brief(ctx, **c.get("args", {}))
            got = _get(res, c["path"])
            ok = _compare(c["op"], got, c.get("value"))
            detail = f"got {got!r}"[:300]
        except Exception as e:  # a crash is a failed case, not a crashed run
            ok, detail = False, f"error: {type(e).__name__}: {e}"
        out.append({"case": c["name"], "passed": ok, "detail": detail})
    return out
