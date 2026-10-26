"""Daily Book MCP tools. Books are local work lists; first touches wait for the AE's approval."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def my_book(ctx, owner: str) -> dict:
    """Today's book for one AE: warm and cold people, ranked, each with the reason and the next action."""
    eng = _eng(ctx)
    eng.ensure_schema(ctx)
    from datetime import date
    rows = ctx.store.query("SELECT rank, pool, source, name, title, company, email, reason, action, status, approval_id "
                           "FROM daily_book WHERE owner=? AND book_date=? ORDER BY rank", (owner, date.today().isoformat()))
    if not rows:
        b = eng.build(ctx, owner)
        return {k: v for k, v in b.items() if k != "held_out"}
    return {"owner": owner, "count": len(rows), "rows": rows}


def build_books(ctx, owner: str = "") -> dict:
    """Build today's books now (one AE, or everyone on the team) and draft cold first touches for approval."""
    eng = _eng(ctx)
    names = [owner] if owner else [o["name"] for o in eng.owners(ctx)]
    out = []
    for n in names:
        b = eng.build(ctx, n)
        b["predraft"] = eng.predraft(ctx, b)
        out.append({k: b[k] for k in ("owner", "slots", "filled", "warm", "cold", "shortfall", "backfill", "predraft")})
    return {"books": out}


def book_status(ctx) -> dict:
    """Every AE's book today: filled against slots, shortfalls, and how many rows are done."""
    _eng(ctx).ensure_schema(ctx)
    from datetime import date
    rows = ctx.store.query("SELECT owner, COUNT(*) AS rows, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done "
                           "FROM daily_book WHERE book_date=? GROUP BY owner", (date.today().isoformat(),))
    return {"books": rows}


def mark_done(ctx, owner: str, email: str, outcome: str = "contacted") -> dict:
    """Mark a book row worked (contacted, meeting_booked, not_a_fit, wrong_person)."""
    _eng(ctx).ensure_schema(ctx)
    from datetime import date
    n = ctx.store.execute("UPDATE daily_book SET status='done', reason=reason || ? WHERE owner=? AND email=? AND book_date=?",
                          (f" | {outcome}", owner, (email or "").lower(), date.today().isoformat()))
    return {"updated": n}


TOOLS = {f.__name__: f for f in [my_book, build_books, book_status, mark_done]}
