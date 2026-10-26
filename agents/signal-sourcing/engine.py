"""Signal Sourcing engine: find dated, sourced buying signals and feed them to Signal Scout.

Four tiers, in priority order (config/signals.yaml):
  1. filings     latest 10-K or 10-Q names a matching priority or risk (Risk Factors, MD&A, Business)
  2. news        initiative, funding or appointment from the company newsroom or trusted press
  3. hiring      buyer-team roles on the company's public job board in the last 30 days
  4. exec_change officer appointments and departures from 8-K item 5.02

Every finding is written to the shared signals table (deduplicated by account, type, URL and day), so
Signal Scout decays, stacks, judges and ranks it with everything else. No signal = no send: the dispatch
batch holds only accounts with at least one valid sourced signal, every required field filled.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from gtm_core import profile
from gtm_core.scoring import IcpProfile, icp_fit, load_taxonomy, signal_id
from gtm_core.sources import edgar as ed
from gtm_core.sources import jobs as jb
from gtm_core.sources import news as nw
from gtm_core.sources import quality as q
from gtm_core.sources.http import SourceClient
from gtm_core.store import now_iso

SOURCE_PREFIX = "sourcing:"
TIER = {"filing": 1, "initiative": 2, "funding": 2, "hiring": 3, "exec_change": 4}
LABEL = {"filing": "10-K/10-Q", "initiative": "initiative", "funding": "funding", "hiring": "hiring",
         "exec_change": "exec_change"}


@lru_cache(maxsize=8)
def _yaml(path: str, mtime: float) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def rules(ctx) -> dict:
    p = ctx.manifest.path(ctx.manifest.config.get("signals", "../../config/signals.yaml"))
    return _yaml(str(p), p.stat().st_mtime) if p.exists() else {}


@lru_cache(maxsize=4)
def _tax(path: str):
    return load_taxonomy(path)


def taxonomy(ctx):
    return _tax(str(ctx.manifest.path(ctx.manifest.config.get(
        "taxonomy", "../signal-scout/skill/references/signal-taxonomy.yaml"))))


def client(ctx) -> SourceClient | None:
    """The injected client (tests, evals), else a live one unless the runtime is offline."""
    c = getattr(ctx, "sources_client", None)
    if c is not None:
        return c
    if getattr(ctx.settings, "offline", False):
        return None
    return SourceClient(per_host_rps=float(ctx.manifest.config.get("per_host_rps", 4)))


def _today(now: datetime | None) -> date:
    return (now or datetime.now(timezone.utc)).date()


def filing_rules(r: dict) -> ed.FilingRules:
    f = r.get("filings") or {}
    return ed.FilingRules(topics=f.get("topics") or [], specificity=f.get("specificity") or [],
                          high_needs=f.get("high_needs") or [])


def _topic_say(r: dict, topic_ids: list[str]) -> str:
    by = {t["id"]: t.get("say") or t["id"].replace("_", " ") for t in (r.get("filings") or {}).get("topics", [])}
    return by.get(topic_ids[0], topic_ids[0].replace("_", " ")) if topic_ids else ""


# ---------------------------------------------------------------- scanning
def scan_account(ctx, acct: dict, now: datetime | None = None, persist: bool = True) -> dict:
    """Run every enabled tier for one account. Returns findings, what each tier said, and what was stored."""
    r = rules(ctx)
    why = q.account_rejection(acct, r.get("exclusions") or {})
    if why:
        return {"account": acct["id"], "rejected": why, "findings": []}
    c = client(ctx)
    if c is None:
        return {"account": acct["id"], "skipped": "offline: no network sources", "findings": []}
    today = _today(now)
    findings, tiers = [], {}
    sec = ed.Edgar(c)
    fcfg = r.get("filings") or {}
    if fcfg.get("enabled", True) and fcfg.get("topics"):
        f, note = sec.filing_signal(acct, filing_rules(r), today, int(fcfg.get("max_age_days", 400)),
                                    tuple(fcfg.get("forms") or ("10-K", "10-Q")))
        tiers["filing"] = note
        if f:
            f.meta["topic"] = _topic_say(r, f.topics)
            findings.append(f)
    xcfg = r.get("exec_change") or {}
    if xcfg.get("enabled", True):
        got = sec.officer_changes(acct, xcfg.get("buyer_roles") or [], xcfg.get("csuite_roles") or [], today,
                                  int(xcfg.get("max_age_days", 180)))
        tiers["exec_change_8k"] = f"{len(got)} found"
        findings += got
    ncfg = r.get("news") or {}
    if ncfg.get("enabled", True):
        nrules = {**ncfg, "buyer_roles": xcfg.get("buyer_roles") or [], "csuite_roles": xcfg.get("csuite_roles") or [],
                  "exec_days": xcfg.get("max_age_days", ncfg.get("exec_days", 180))}
        provider = getattr(ctx, "news_provider", None)
        if provider is None and not getattr(ctx, "sources_client", None):
            provider = nw.ContextDevNews.from_env()
        got, info = nw.news_signals(c, acct, nrules, today, provider)
        tiers["news"] = info
        findings += got
    hcfg = r.get("hiring") or {}
    if hcfg.get("enabled", True) and hcfg.get("buyer_roles"):
        f, info = jb.hiring_signal(c, acct, hcfg["buyer_roles"], today, int(hcfg.get("max_age_days", 30)))
        tiers["hiring"] = info
        if f:
            findings.append(f)
            if info.get("provider") and not acct.get("ats") and persist:
                keep = {k: v for k, v in acct.items() if k != "updated_at"}
                ctx.store.upsert_account({**keep, "ats": {info["provider"]: info["token"]}})
    # an 8-K and a newsroom post about the same appointment: keep the earlier-dated one, once
    seen, uniq = set(), []
    for f in sorted(findings, key=lambda x: (TIER[x.source], x.observed_at)):
        k = (f.signal_type, (f.meta.get("role") or f.url).lower()) if f.source == "exec_change" else (f.signal_type, f.url)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)
    stored = _persist(ctx, uniq, now) if persist else []
    if persist:
        ctx.store.set_state(f"sourcing_last_scan:{acct['id']}", (now or datetime.now(timezone.utc)).isoformat())
        for e in c.log:
            if e["status"] == 0 or e["status"] >= 500:
                ctx.audit.log("sourcing.fetch_failed", url=e["url"][:300], status=e["status"], error=e["error"])
        c.log.clear()
    return {"account": acct["id"], "name": acct.get("name"), "findings": [f.as_dict() for f in uniq],
            "stored": stored, "tiers": tiers}


def _persist(ctx, findings, now) -> list[str]:
    tax = taxonomy(ctx)
    added = []
    for f in findings:
        st = tax.types.get(f.signal_type)
        if not st or not f.url or not f.observed_at:
            continue
        sig = {"id": signal_id(f.account_id, f.signal_type, f.url, f.observed_at), "account_id": f.account_id,
               "signal_type": f.signal_type, "category": st.category, "source": SOURCE_PREFIX + f.source,
               "url": f.url, "observed_at": f.observed_at, "strength": f.strength,
               "payload": {"title": f.detail, "topic": f.meta.get("topic") or "", "filing": f.meta.get("filing"),
                           "confidence": f.confidence, "amount": f.amount, "topics": f.topics,
                           "person": f.meta.get("person"), "role": f.meta.get("role"),
                           "section": f.meta.get("section"), "tier": TIER[f.source]}}
        try:
            if ctx.store.add_signal(sig):
                added.append(sig["id"])
        except ValueError as e:
            ctx.audit.log("sourcing.bad_signal", account=f.account_id, error=str(e)[:200])
    return added


def due_accounts(ctx, now: datetime | None = None, limit: int | None = None) -> list[dict]:
    """Accounts not scanned within rescan_days, best Signal Scout tier first, then never-scanned first."""
    r = rules(ctx)
    days = int((r.get("dispatch") or {}).get("rescan_days", 7))
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
    tiers = {}
    for row in ctx.store.query("SELECT account_id, tier, score FROM scores ORDER BY id"):
        tiers[row["account_id"]] = (row["tier"], row["score"])
    rank = {"A": 0, "B": 1, "C": 2, "D": 3, None: 4, "X": 9}
    out = []
    for a in ctx.store.accounts():
        last = ctx.store.get_state(f"sourcing_last_scan:{a['id']}")
        if last and last >= cutoff:
            continue
        t = tiers.get(a["id"], (None, 0))
        if t[0] == "X":
            continue
        out.append((rank.get(t[0], 4), last or "", -(t[1] or 0), a))
    out.sort(key=lambda x: x[:3])
    rows = [x[3] for x in out]
    return rows[: int(limit)] if limit else rows


def scan_due(ctx, now: datetime | None = None, limit: int | None = None) -> dict:
    limit = int(limit or ctx.manifest.config.get("scan_limit", 50))
    results = [scan_account(ctx, a, now) for a in due_accounts(ctx, now, limit)]
    return {"scanned": len(results), "with_signals": sum(1 for x in results if x["findings"]),
            "stored": sum(len(x.get("stored", [])) for x in results),
            "rejected": [{"account": x["account"], "why": x["rejected"]} for x in results if x.get("rejected")],
            "results": results}


# ---------------------------------------------------------------- dispatch
def dispatch(ctx, now: datetime | None = None, limit: int | None = None) -> dict:
    """The send-ready batch: accounts with a valid sourced signal, every required field filled, ranked by
    confidence, Signal Scout score, then recency. Excluded accounts come back with the reason."""
    r = rules(ctx)
    d = r.get("dispatch") or {}
    limit = int(limit or d.get("max_accounts", 25))
    personas = ", ".join(d.get("target_personas") or [])
    icp = IcpProfile.from_yaml(profile.icp_path(ctx))
    floor = float(ctx.manifest.config.get("icp_floor", 30))
    windows = {"filing": int((r.get("filings") or {}).get("max_age_days", 400)),
               "initiative": int((r.get("news") or {}).get("initiative_days", 180)),
               "funding": int((r.get("news") or {}).get("funding_days", 180)),
               "hiring": int((r.get("hiring") or {}).get("max_age_days", 30)),
               "exec_change": int((r.get("exec_change") or {}).get("max_age_days", 180))}
    today = _today(now)
    scores = {row["account_id"]: row for row in ctx.store.query("SELECT * FROM scores ORDER BY id")}
    batch, excluded = [], []
    for a in ctx.store.accounts():
        sigs = [s for s in ctx.store.signals_for(a["id"]) if (s.get("source") or "").startswith(SOURCE_PREFIX)]
        if not sigs:
            continue
        why = q.account_rejection(a, r.get("exclusions") or {})
        fit, reasons = icp_fit(a, icp)
        if not why and (reasons and reasons[0].startswith("excluded industry") or fit < floor):
            why = f"below ICP floor ({fit:.0f})" if fit < floor else reasons[0]
        sc = scores.get(a["id"])
        if not why and sc and sc["tier"] == "X":
            why = "out of ICP (Signal Scout tier X)"
        live = []
        for s in sigs:
            src = s["source"][len(SOURCE_PREFIX):]
            if src in windows and s["observed_at"][:10] >= (today - timedelta(days=windows[src])).isoformat():
                live.append((src, s))
        if not why and not live:
            why = "sourced signals are older than their window"
        if why:
            excluded.append({"account_id": a["id"], "company": a.get("name"), "reason": why})
            continue
        # best signal: High first, then the higher tier, then the newest
        live.sort(key=lambda x: (0 if x[1]["payload"].get("confidence") == "High" else 1, TIER.get(x[0], 9),
                                 -int(x[1]["observed_at"][:10].replace("-", ""))))
        best_src, best = live[0]
        newest = max(live, key=lambda x: x[1]["observed_at"])[1]
        row = {"account_id": a["id"], "domain": q.clean_domain(a.get("domain") or a["id"]), "company": a.get("name"),
               "industry": a.get("industry"), "signal_source": LABEL[best_src],
               "signal_detail": best["payload"].get("title"), "signal_url": best["url"],
               "signal_date": best["observed_at"][:10], "signal_amount": best["payload"].get("amount") or "",
               "signal_score": "High" if any(s["payload"].get("confidence") == "High" for _, s in live) else "Medium",
               "target_personas": personas, "signal_count": len(live), "sources": sorted({x[0] for x in live}),
               "scout_tier": sc["tier"] if sc else None, "scout_score": float(sc["score"]) if sc else None,
               "newest_signal": newest["observed_at"][:10]}
        bad = q.row_rejection(row)
        if bad:
            excluded.append({"account_id": a["id"], "company": a.get("name"), "reason": bad})
            continue
        batch.append(row)
    batch = sorted(batch, key=lambda x: (x["signal_score"] != "High", -(x["scout_score"] or 0),
                                          -int(x["newest_signal"].replace("-", ""))))
    return {"count": len(batch[:limit]), "batch": batch[:limit], "held_back": len(batch[limit:]),
            "excluded": excluded}


def format_dispatch(res: dict) -> str:
    lines = [f"*Signal Sourcing: {res['count']} accounts ready*"
             + (f" ({res['held_back']} more held for tomorrow)" if res["held_back"] else "")]
    for i, b in enumerate(res["batch"][:15], 1):
        lines.append(f"{i}. *{b['company']}* | {b['signal_score']} | {b['signal_source']} {b['signal_date']}: "
                     f"{b['signal_detail'][:140]}")
    if res["excluded"]:
        lines.append(f"_Held out: {len(res['excluded'])} accounts (no corporate domain, excluded type, ICP or "
                     f"incomplete signal). Ask for the list._")
    return "\n".join(lines)


# ---------------------------------------------------------------- discovery
def discover(ctx, now: datetime | None = None) -> dict:
    """New companies whose recent filings use the configured phrases and are not accounts yet.
    Candidates have no domain (EDGAR does not publish one): add them with add_company, or push them to
    Clay to fill domain and firmographics."""
    r = rules(ctx)
    dc = r.get("discovery") or {}
    c = client(ctx)
    if c is None or not dc.get("enabled", True):
        return {"skipped": "offline or discovery disabled", "candidates": []}
    today = _today(now)
    known_ciks = {str(a.get("cik")).zfill(10) for a in ctx.store.accounts() if a.get("cik")}
    known_names = {ed.norm_name(a.get("name", "")) for a in ctx.store.accounts()}
    excl = (r.get("exclusions") or {})
    sec = ed.Edgar(c)
    found: dict[str, dict] = {}
    for phrase in dc.get("phrases") or []:
        for h in sec.full_text_search(phrase, dc.get("forms", "10-K,10-Q"),
                                      today - timedelta(days=int(dc.get("lookback_days", 120))), today,
                                      int(dc.get("max_per_phrase", 50))):
            if h["cik"] in known_ciks or ed.norm_name(h["name"]) in known_names:
                continue
            why = q.account_rejection({"domain": "placeholder.example", "name": h["name"], "ticker": h["ticker"]}, excl)
            if why:
                continue
            e = found.setdefault(h["cik"], {**h, "phrases": []})
            e["phrases"].append(phrase)
    cands = sorted(found.values(), key=lambda x: (-len(x["phrases"]), x["name"]))
    ctx.store.set_state("sourcing_candidates", cands)
    return {"candidates": cands, "count": len(cands)}


def add_company(ctx, name: str, domain: str, cik: str = "", ticker: str = "", industry: str = "",
                employees: int | None = None, newsroom_rss: str = "") -> dict:
    """Create or update an account for sourcing. Local store only; nothing is written to the CRM."""
    dom = q.clean_domain(domain)
    acct = {"id": dom, "name": name, "domain": dom, "industry": industry or None, "employees": employees}
    if cik:
        acct["cik"] = str(cik).zfill(10)
    if ticker:
        acct["ticker"] = ticker.upper()
    if newsroom_rss:
        acct["newsroom_rss"] = newsroom_rss
    why = q.account_rejection(acct, rules(ctx).get("exclusions") or {})
    if why:
        return {"error": f"not added: {why}"}
    old = ctx.store.account(dom) or {}
    old.pop("updated_at", None)
    ctx.store.upsert_account({**old, **{k: v for k, v in acct.items() if v not in (None, "")}})
    return {"added": not old, "updated": bool(old), "account": dom, "added_at": now_iso()}
