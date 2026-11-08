"""Leadership command center: every metric by team, last N weeks, heat-mapped against target or pace,
with week-over-week change. Output is one self-contained HTML page plus a compact emoji heat strip for Slack.

Week values: metrics dated by events (bookings, created pipeline, MQLs, retention) are recomputed for each past
week from the same rows, so the page is full on day one. Metrics that depend on live deal state (commit,
coverage, stalled, slipped, renewal risk) come from stored daily snapshots and fill in as runs accumulate.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY_KEY = "exec_brief:history"
KEEP_DAYS = 400
BACKFILL = {"bookings_qtd", "pipeline_created_qtd", "win_rate_qtd", "mqls_mtd", "mql_to_sql_90d",
            "marketing_pipeline_qtd", "marketing_share_qtd", "speed_to_lead", "partner_pipeline_qtd",
            "partner_bookings_qtd", "deal_regs_7d", "active_partners_90d", "grr_qtd", "nrr_qtd"}
SQUARE = {"good": ":large_green_square:", "watch": ":large_yellow_square:", "bad": ":large_red_square:",
          None: ":white_large_square:"}


def week_ends(now: datetime, weeks: int) -> list[datetime]:
    """Rolling 7-day weeks ending on the run day, oldest first, so each column compares the same weekday."""
    return [now - timedelta(days=7 * i) for i in range(weeks)][::-1]


def _period_reset(eng, key: str, a: datetime, b: datetime) -> bool:
    """QTD and MTD metrics restart at a quarter or month boundary: no week-over-week change across one."""
    if key.endswith("_qtd"):
        return eng.quarter_bounds(a)[0] != eng.quarter_bounds(b)[0]
    if key.endswith("_mtd"):
        return eng.month_bounds(a)[0] != eng.month_bounds(b)[0]
    return False


def record(store, computed: dict) -> None:
    """Add today's metric values, scores and status to the rolling daily history."""
    h = store.get_state(HISTORY_KEY) or {}
    day = computed["as_of"][:10]
    h[day] = {k: {"value": m["value"], "score": m["score"], "status": m["status"]}
              for k, m in computed["metrics"].items()}
    cutoff = (datetime.fromisoformat(computed["as_of"]) - timedelta(days=KEEP_DAYS)).date().isoformat()
    store.set_state(HISTORY_KEY, {d: v for d, v in sorted(h.items()) if d >= cutoff})


def grid(eng, rows: dict, cfg: dict, history: dict, now: datetime, weeks: int = 8, today: dict | None = None) -> dict:
    """`today` is this run's computed metrics (live deal state and yesterday's snapshot) for the last column.
    {weeks: [iso], metrics: {key: {label, dept, kind, better, cells: [{value, display, status, score, wow}]}}}"""
    ends = week_ends(now, weeks)
    cols, prev_vals = [], None
    # one extra week before the window so the first column has a week-over-week change
    for end in [ends[0] - timedelta(days=7), *ends]:
        c = eng.compute(rows, cfg, {"metrics": prev_vals or {}}, end)["metrics"]
        snap = _snapshot_on_or_before(history, end, max_age_days=6)
        for k, m in c.items():
            if k not in BACKFILL and end != ends[-1]:
                s = (snap or {}).get(k)
                c[k] = {**m, "value": s["value"], "score": s["score"], "status": s["status"],
                        "display": eng.fmt(s["value"], m["kind"])} if s else {**m, "value": None, "score": None,
                                                                              "status": None, "display": ""}
        if today is not None and end == ends[-1]:
            c = today["metrics"]
        cols.append((end, c))
        prev_vals = {k: m["value"] for k, m in c.items()}
    out = {"weeks": [e.date().isoformat() for e, _ in cols[1:]], "metrics": {}}
    for k, m0 in cols[-1][1].items():
        cells = []
        for i in range(1, len(cols)):
            m, p = cols[i][1][k], cols[i - 1][1][k]
            wow = None if (m["value"] is None or p["value"] is None or _period_reset(eng, k, cols[i - 1][0], cols[i][0])) \
                else round(m["value"] - p["value"], 4)
            cells.append({"value": m["value"], "display": m["display"], "status": m["status"], "score": m["score"],
                          "wow": wow, "wow_good": None if not wow else (wow > 0) == (m0["better"] == "up")})
        out["metrics"][k] = {"label": m0["label"], "dept": m0["dept"], "kind": m0["kind"], "better": m0["better"],
                             "cells": cells}
    return out


def _snapshot_on_or_before(history: dict, end: datetime, max_age_days: int) -> dict | None:
    day = end.date().isoformat()
    lo = (end - timedelta(days=max_age_days)).date().isoformat()
    days = [d for d in history if lo <= d <= day]
    return history[max(days)] if days else None


def _wow_text(eng, kind: str, wow) -> str:
    if not wow or (kind == "pct" and abs(wow) < 0.005) or (kind == "x" and abs(wow) < 0.05):
        return ""
    arrow = "▲" if wow > 0 else "▼"
    if kind == "money":
        return f"{arrow} {eng.money(abs(wow))}"
    if kind == "pct":
        return f"{arrow} {abs(wow) * 100:.0f} pts"
    if kind == "x":
        return f"{arrow} {abs(wow):.1f}x"
    return f"{arrow} {abs(wow):,.0f}"


def slack_strip(g: dict, keys: list[str], weeks: int = 6) -> str:
    """Emoji heat strip for Slack: one line per metric, oldest week left, this week right."""
    lines = []
    for k in keys:
        m = g["metrics"].get(k)
        if not m:
            continue
        sq = "".join(SQUARE[c["status"]] for c in m["cells"][-weeks:])
        lines.append(f"{sq}  {m['label']}")
    return "\n".join(lines)


def _bg(status, score) -> str:
    if status is None:
        return "#f1f1ef"
    strength = min(abs(score or 0), 0.5) / 0.5  # deeper color the further from target
    if status == "good":
        return f"rgba(22,135,72,{0.18 + 0.5 * strength:.2f})"
    if status == "watch":
        return "rgba(214,160,0,0.35)"
    return f"rgba(200,40,40,{0.22 + 0.5 * strength:.2f})"


def html_page(eng, g: dict, computed: dict, extremes: list[dict], now: datetime, title: str = "Leadership command center") -> str:
    e = html.escape
    weeks = g["weeks"]
    head = "".join(f"<th>{'Today' if i == len(weeks) - 1 else e(w[5:].replace('-', '/'))}</th>" for i, w in enumerate(weeks))
    body = []
    for dept_key, dept_name in eng.DEPARTMENTS.items():
        ms = [(k, m) for k, m in g["metrics"].items() if m["dept"] == dept_key]
        if not ms:
            continue
        body.append(f'<tr class="dept"><td colspan="{len(weeks) + 1}">{e(dept_name)}</td></tr>')
        for k, m in ms:
            cells = []
            for c in m["cells"]:
                w = _wow_text(eng, m["kind"], c["wow"])
                cls = "" if c["wow_good"] is None else (" up" if c["wow_good"] else " down")
                cells.append(f'<td style="background:{_bg(c["status"], c["score"])}"><b>{e(c["display"] or "")}</b>'
                             f'<span class="wow{cls}">{e(w)}</span></td>')
            body.append(f'<tr><th class="m">{e(m["label"])}</th>{"".join(cells)}</tr>')
    tiles = []
    for r in extremes:
        b, w = r["best"], r["worst"]
        tiles.append(
            f'<div class="tile"><h3>{e(r["name"])}</h3>'
            + (f'<p class="g">Best: {e(b["label"])} <b>{e(b["display"])}</b></p>' if b else "")
            + (f'<p class="r">Worst: {e(w["label"])} <b>{e(w["display"])}</b></p>' if w else "")
            + "</div>")
    stamp = now.strftime("%a %b %d, %Y %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<style>
:root{{--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--bg:#fbfbf8}}
*{{box-sizing:border-box}} body{{margin:0;font:15px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;color:var(--ink);background:var(--bg)}}
header{{padding:20px 20px 8px}} h1{{margin:0;font-size:22px}} .sub{{color:var(--muted);font-size:13px;margin-top:4px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;padding:12px 20px}}
.tile{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.tile h3{{margin:0 0 6px;font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
.tile p{{margin:4px 0;font-size:14px}} .g b{{color:#16733f}} .r b{{color:#b42323}}
.wrap{{overflow-x:auto;padding:8px 20px 24px}}
table{{border-collapse:separate;border-spacing:3px;min-width:900px;width:100%}}
th,td{{padding:8px 10px;text-align:right;font-size:14px;border-radius:6px;white-space:nowrap}}
thead th{{color:var(--muted);font-weight:600;font-size:12px;position:sticky;top:0;background:var(--bg)}}
th.m{{text-align:left;font-weight:500;position:sticky;left:0;background:var(--bg);max-width:260px;white-space:normal}}
tr.dept td{{text-align:left;font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.05em;padding-top:16px;background:none}}
td b{{display:block;font-size:15px}} .wow{{display:block;font-size:12px;color:var(--muted)}} .wow.up{{color:#16733f}} .wow.down{{color:#b42323}}
.legend{{color:var(--muted);font-size:12px;padding:0 20px 20px}} .legend span{{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin:0 4px 0 12px}}
</style></head><body>
<header><h1>{e(title)}</h1><div class="sub">Updated {e(stamp)}. Each column is the number as of that day, one week apart; color is versus target or pace, darker means further off; arrows are the change from the week before. Quarter and month to date numbers restart at each period.</div></header>
<section class="tiles">{"".join(tiles)}</section>
<div class="wrap"><table><thead><tr><th class="m">Metric</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>
<div class="legend">Legend:<span style="background:rgba(22,135,72,.6)"></span>on or ahead of target<span style="background:rgba(214,160,0,.35)"></span>within 10%<span style="background:rgba(200,40,40,.6)"></span>behind<span style="background:#f1f1ef"></span>no target or no history yet</div>
</body></html>"""


def write(settings, page: str) -> Path:
    out = Path(settings.data_dir) / "exec_brief" / "command-center.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out
