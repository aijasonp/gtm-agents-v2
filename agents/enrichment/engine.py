"""Enrichment engine: provider-agnostic waterfall with cache, spend caps, verification and provenance.

Deterministic throughout. No model calls. Providers are data (providers.yaml); the HTTP adapter is
generic and never ships a working vendor endpoint by default.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml

from gtm_core import pipeline, suppression
from gtm_core.store import now_iso

PERSON_FIELDS = ["email", "phone", "title", "linkedin"]
ACCOUNT_FIELDS = ["employees", "industry", "revenue", "country"]
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
COUNTRY_CODES = {"US": "1", "CA": "1", "GB": "44", "UK": "44", "DE": "49", "FR": "33", "AU": "61", "IN": "91",
                 "NL": "31", "ES": "34", "IT": "39", "IE": "353", "SG": "65", "BR": "55", "MX": "52", "JP": "81",
                 "SE": "46", "CH": "41", "IL": "972", "NZ": "64"}
COUNTRY_NAMES = {"united states": "US", "united states of america": "US", "usa": "US", "u.s.": "US", "us": "US",
                 "canada": "CA", "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
                 "germany": "DE", "deutschland": "DE", "france": "FR", "spain": "ES", "italy": "IT",
                 "netherlands": "NL", "the netherlands": "NL", "ireland": "IE", "australia": "AU", "india": "IN",
                 "brazil": "BR", "mexico": "MX", "japan": "JP", "singapore": "SG", "sweden": "SE",
                 "switzerland": "CH", "israel": "IL", "new zealand": "NZ"}


def calling_code(country: str | None) -> str:
    """ISO2 code or common country name -> calling code. Unknown -> +1 (configure default_country)."""
    c = (country or "US").strip()
    iso = c.upper() if len(c) <= 3 and c.upper() in COUNTRY_CODES else COUNTRY_NAMES.get(c.lower(), c.upper())
    return COUNTRY_CODES.get(iso, "1")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS enrichment_cache (key TEXT PRIMARY KEY, person TEXT, field TEXT, value TEXT,
       provider TEXT, confidence DOUBLE PRECISION, cost DOUBLE PRECISION, fetched_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS enrichment_calls (id TEXT PRIMARY KEY, ts TEXT, provider TEXT, field TEXT,
       person TEXT, hit INTEGER, cost DOUBLE PRECISION, note TEXT)""",
]

# test hooks: tests inject an httpx client and a sleeper
HTTP_CLIENT: httpx.Client | None = None
SLEEP = time.sleep
_RATE: dict[str, list[float]] = {}


class ProviderSkipped(Exception):
    pass


def ensure_schema(ctx) -> None:
    if not getattr(ctx.store, "_enrichment_schema", False):
        for s in SCHEMA:
            ctx.store.execute(s)
        ctx.store._enrichment_schema = True


def _now(now):
    return now or datetime.now(timezone.utc)


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def providers_cfg(ctx, override: dict | None = None) -> dict:
    if override is not None:
        return override
    if isinstance(ctx.manifest.config.get("providers_inline"), dict):  # tests and evals
        return ctx.manifest.config["providers_inline"]
    return _yaml(str(ctx.manifest.path(ctx.manifest.config.get("providers", "skill/references/providers.yaml"))))


# ---------------------------------------------------------------- normalization
def normalize_email(v) -> str | None:
    v = str(v or "").strip().lower().strip("<>").strip()
    return v if EMAIL_RE.match(v) else None


def normalize_phone(raw, country: str = "US") -> str | None:
    """To E.164 (+15551234567). None when it cannot be a valid number."""
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    s = re.split(r"\s*(?:x|ext\.?|extension|#)\s*\d+\s*$", s, flags=re.I)[0]
    s = re.sub(r"\(\s*0\s*\)", "", s)  # "+44 (0)20 ..." : the (0) trunk prefix is never dialed internationally
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if s.startswith("+"):
        d = digits
    elif digits.startswith("00"):
        d = digits[2:]
    else:
        cc = calling_code(country)
        if cc == "1":
            if len(digits) == 10:
                d = "1" + digits
            elif len(digits) == 11 and digits.startswith("1"):
                d = digits
            else:
                return None
        else:
            national = digits[1:] if digits.startswith("0") else digits
            d = digits if digits.startswith(cc) and len(digits) >= len(cc) + 8 else cc + national
    if not (8 <= len(d) <= 15) or d.startswith("0"):
        return None
    if d.startswith("1") and len(d) != 11:
        return None
    return "+" + d


def validate(field: str, value, country: str = "US"):
    if value in (None, "", [], {}):
        return None
    if field == "email":
        return normalize_email(value)
    if field == "phone":
        return normalize_phone(value, country)
    if field in ("employees",):
        try:
            return int(float(str(value).replace(",", "")))
        except ValueError:
            return None
    if field == "revenue":
        try:
            return float(str(value).replace(",", "").replace("$", ""))
        except ValueError:
            return None
    if field == "linkedin":
        v = str(value).strip()
        return v if v.startswith("http") else None
    v = str(value).strip()
    return v or None


def person_key(p: dict) -> str | None:
    if normalize_email(p.get("email")):
        return normalize_email(p["email"])
    if p.get("linkedin"):
        return str(p["linkedin"]).strip().lower().rstrip("/")
    if p.get("name") and p.get("domain"):
        return f"name:{p['name'].strip().lower()}@{p['domain'].strip().lower()}"
    return None


def person_from_contact(ctx, c: dict) -> dict:
    acct = ctx.store.account(c["account_id"]) if c.get("account_id") else None
    email = normalize_email(c.get("email")) if not c.get("email_invalid") else None
    domain = (email.split("@", 1)[1] if email else None) or (acct or {}).get("domain") or c.get("domain")
    name = c.get("name") or ""
    parts = name.split()
    return {"contact_id": c.get("id"), "email": email, "name": name, "first": parts[0] if parts else "",
            "last": parts[-1] if len(parts) > 1 else "", "domain": domain, "linkedin": c.get("linkedin"),
            "company": (acct or {}).get("name") or c.get("company"), "title": c.get("title"),
            "phone": c.get("phone"), "account_id": c.get("account_id") or (acct or {}).get("id"),
            "country": c.get("country") or (acct or {}).get("country"),
            "invalid_emails": [c["email"]] if c.get("email_invalid") and c.get("email") else []}


# ---------------------------------------------------------------- providers
def _dig(data, path: str):
    cur = data
    for part in re.findall(r"[^.\[\]]+", path or ""):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _env(s: str) -> str:
    def rep(m):
        v = os.environ.get(m.group(1))
        if not v:
            raise ProviderSkipped(f"missing environment variable {m.group(1)}")
        return v
    return re.sub(r"\$\{([A-Z0-9_]+)\}", rep, s)


def _fill(template: str, p: dict, url: bool = False) -> str:
    def rep(m):
        v = str(p.get(m.group(1)) or "")
        return quote(v, safe="") if url else v
    return re.sub(r"\{(email|domain|name|first|last|linkedin|company|title|phone)\}", rep, template)


def _render(obj, p: dict):
    # ${ENV} is resolved in the template first; contact data is filled in after, so a value such as a lead
    # named "${ANTHROPIC_API_KEY}" is sent as literal text and never expanded.
    if isinstance(obj, str):
        return _fill(_env(obj), p)
    if isinstance(obj, dict):
        return {k: _render(v, p) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_render(v, p) for v in obj]
    return obj


class Provider:
    def __init__(self, name: str, cfg: dict, root: Path):
        self.name, self.cfg, self.root = name, cfg, root
        self.cost = float(cfg.get("cost_per_call", 0) or 0)
        self.confidence = float(cfg.get("confidence", 0.8))

    def lookup(self, p: dict) -> dict:
        raise NotImplementedError


class CsvProvider(Provider):
    _cache: dict[str, list[dict]] = {}

    def rows(self) -> list[dict]:
        path = Path(self.cfg["path"])
        path = path if path.is_absolute() else (self.root / path)
        key = str(path)
        if key not in self._cache:
            if not path.exists():
                raise ProviderSkipped(f"csv file not found: {path.name}")
            with path.open(newline="") as f:
                self._cache[key] = list(csv.DictReader(f))
        return self._cache[key]

    def lookup(self, p: dict) -> dict:
        rows = self.rows()
        for how in self.cfg.get("match_on", ["email"]):
            for r in rows:
                if how == "email" and p.get("email") and (r.get("email") or "").lower() == p["email"].lower():
                    return self._out(r)
                if how == "linkedin" and p.get("linkedin") and (r.get("linkedin") or "").rstrip("/").lower() == \
                        str(p["linkedin"]).rstrip("/").lower():
                    return self._out(r)
                if how == "name_domain" and p.get("name") and p.get("domain") and \
                        (r.get("name") or "").lower() == p["name"].lower() and (r.get("domain") or "").lower() == p["domain"].lower():
                    return self._out(r)
                if how == "domain" and p.get("domain") and (r.get("domain") or "").lower() == p["domain"].lower():
                    return self._out(r)
        return {}

    def _out(self, row: dict) -> dict:
        return {f: row.get(col) for f, col in self.cfg.get("outputs", {}).items() if row.get(col) not in (None, "")}


class HttpProvider(Provider):
    def lookup(self, p: dict) -> dict:
        c = self.cfg
        url = _fill(_env(c["url"]), p, url=True)
        headers = _render(c.get("headers") or {}, p)
        body = _render(c.get("json"), p) if c.get("json") is not None else None
        limit = int(c.get("rate_limit_per_minute") or 0)
        if limit:
            now = time.monotonic()
            hist = [t for t in _RATE.get(self.name, []) if now - t < 60]
            if len(hist) >= limit:
                SLEEP(max(0.0, 60 - (now - hist[0])))
            _RATE[self.name] = hist + [time.monotonic()]
        client = HTTP_CLIENT or httpx.Client(timeout=float(c.get("timeout", 20)))
        r = client.request(c.get("method", "GET").upper(), url, headers=headers, json=body)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        data = r.json() if r.content else {}
        return {f: v for f, path in c.get("outputs", {}).items() if (v := _dig(data, path)) not in (None, "")}


class ManualProvider(Provider):
    def lookup(self, p: dict) -> dict:
        return {}


TYPES = {"csv": CsvProvider, "http": HttpProvider, "manual": ManualProvider}


def build(ctx, cfg: dict) -> dict[str, Provider]:
    root = ctx.manifest.root
    out = {}
    for name, pc in (cfg.get("providers") or {}).items():
        t = TYPES.get((pc or {}).get("type"))
        if t:
            out[name] = t(name, pc, root)
    return out


# ---------------------------------------------------------------- cache, calls, spend
def cache_get(ctx, key: str, field: str, ttl_days: int, now: datetime) -> dict | None:
    r = ctx.store.one("SELECT * FROM enrichment_cache WHERE key=?", (f"{key}|{field}",))
    if not r:
        return None
    at = pipeline.parse_dt(r["fetched_at"])
    if at and (now - at).days >= ttl_days:
        return None
    return r


def cache_put(ctx, key: str, field: str, value, provider: str, confidence: float, cost: float, now: datetime) -> None:
    ctx.store.execute(
        "INSERT INTO enrichment_cache (key, person, field, value, provider, confidence, cost, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, provider=excluded.provider, "
        "confidence=excluded.confidence, cost=excluded.cost, fetched_at=excluded.fetched_at",
        (f"{key}|{field}", key, field, json.dumps(value), provider, confidence, cost, now.replace(microsecond=0).isoformat()))


def redact(text: str) -> str:
    """Strip query strings from URLs and any secret values referenced as ${ENV} anywhere in the environment."""
    t = re.sub(r"(https?://[^\s?#'\"]+)[?#][^\s'\"]*", r"\1?[redacted]", str(text or ""))
    for k, v in os.environ.items():
        if v and len(v) >= 6 and re.search(r"KEY|TOKEN|SECRET|PASSWORD|AUTH", k, re.I) and v in t:
            t = t.replace(v, "[redacted]")
    return t


def record_call(ctx, provider: str, field: str, key: str, hit: bool, cost: float, note: str, now: datetime) -> None:
    note = redact(note)
    ctx.store.execute("INSERT INTO enrichment_calls (id, ts, provider, field, person, hit, cost, note) VALUES (?,?,?,?,?,?,?,?)",
                      (uuid.uuid4().hex, now.replace(microsecond=0).isoformat(), provider, field, key, int(hit), cost, note[:300]))


def month_spend(ctx, now: datetime) -> float:
    r = ctx.store.one("SELECT COALESCE(SUM(cost),0) AS c FROM enrichment_calls WHERE ts LIKE ?", (now.strftime("%Y-%m") + "%",))
    return float(r["c"] or 0)


def new_run() -> dict:
    return {"spent": 0.0, "capped": None, "calls": 0, "alerted": False}


def _cap_reason(ctx, cfg: dict, run: dict, cost: float, now: datetime) -> str | None:
    caps = cfg.get("caps") or {}
    per_run, monthly = float(caps.get("per_run_usd") or 0), float(caps.get("monthly_usd") or 0)
    if per_run and run["spent"] + cost > per_run:
        return f"per-run cap ${per_run:.2f} reached"
    if monthly and month_spend(ctx, now) + cost > monthly:
        return f"monthly cap ${monthly:.2f} reached"
    return None


def _alert_cap(ctx, run: dict) -> None:
    if run["capped"] and not run["alerted"]:
        run["alerted"] = True
        try:
            ctx.slack.post(f":pause_button: *Enrichment* stopped: {run['capped']}. Remaining lookups wait for the next run "
                           "or a higher cap in providers.yaml.")
        except Exception as e:
            ctx.audit.log("slack.error", error=str(e)[:200])


# ---------------------------------------------------------------- waterfall
def _verify_email(ctx, cfg: dict, provs: dict, p: dict, email: str, run: dict, key: str, now: datetime) -> tuple[bool | None, float]:
    vname = cfg.get("verifier")
    if not vname or vname not in provs:
        return None, 0.0
    v = provs[vname]
    reason = _cap_reason(ctx, cfg, run, v.cost, now)
    if reason:
        run["capped"] = reason
        return None, 0.0
    try:
        out = v.lookup({**p, "email": email})
    except ProviderSkipped as e:
        record_call(ctx, vname, "verify", key, False, 0.0, f"skipped: {e}", now)
        return None, 0.0
    except Exception as e:
        record_call(ctx, vname, "verify", key, False, v.cost, f"error: {type(e).__name__}", now)
        run["spent"] += v.cost
        return None, v.cost
    run["spent"] += v.cost
    ok = str(out.get("status", "")).lower() in [s.lower() for s in v.cfg.get("accepted", ["valid"])]
    record_call(ctx, vname, "verify", key, ok, v.cost, f"status {out.get('status')}", now)
    return ok, v.cost


def _bad_email(ctx, email: str, p: dict) -> bool:
    e = (email or "").lower()
    if e and e in {x.lower() for x in (p.get("invalid_emails") or [])}:
        return True
    c = ctx.store.contact_by_email(e)
    if c and c.get("email_invalid"):
        return True
    why = suppression.reason(ctx.store, e) or ""
    return "bounce" in why or "email_invalid" in why


def waterfall(ctx, p: dict, fields: list[str], run: dict, cfg: dict | None = None, now: datetime | None = None,
              order_key: str = "order", key: str | None = None) -> dict:
    """Find each field. Returns {field: {value, provider, confidence, at, cost, source} | {status: ...}}."""
    ensure_schema(ctx)
    now = _now(now)
    cfg = cfg or providers_cfg(ctx)
    provs = build(ctx, cfg)
    key = key or person_key(p)
    country = p.get("country") or cfg.get("default_country", "US")
    ttl = int(cfg.get("ttl_days", 90))
    miss_ttl = int(cfg.get("miss_ttl_days", ctx.manifest.config.get("miss_ttl_days", 14)))
    if not key:
        return {f: {"status": "no identifier (need email, LinkedIn URL, or name plus domain)"} for f in fields}
    results: dict = {}
    pending: dict = {}  # values returned by an earlier provider for a later field, already validated
    for field in fields:
        hit = cache_get(ctx, key, field, ttl, now)
        if hit and json.loads(hit["value"]) is None:  # a cached miss: do not pay again until miss_ttl_days pass
            if hit["fetched_at"] and (now - pipeline.parse_dt(hit["fetched_at"])).days < miss_ttl:
                results[field] = {"status": "not found (cached)", "tried": [hit["provider"]]}
                continue
            hit = None
        if hit:
            results[field] = {"value": json.loads(hit["value"]), "provider": hit["provider"], "confidence": hit["confidence"],
                              "at": hit["fetched_at"], "cost": 0.0, "source": "cache"}
            continue
        if field in pending:
            results[field] = pending[field]
            continue
        tried = []
        for pname in (cfg.get(order_key) or {}).get(field, []):
            prov = provs.get(pname)
            if prov is None:
                continue
            if isinstance(prov, ManualProvider):
                results[field] = {"status": "needs manual research", "tried": tried}
                break
            reason = _cap_reason(ctx, cfg, run, prov.cost, now)
            if reason:
                run["capped"] = reason
                results[field] = {"status": f"stopped: {reason}", "tried": tried}
                _alert_cap(ctx, run)
                break
            tried.append(pname)
            try:
                raw = prov.lookup({**p, "country": country})
            except ProviderSkipped as e:
                record_call(ctx, pname, field, key, False, 0.0, f"skipped: {e}", now)
                continue
            except Exception as e:
                run["spent"] += prov.cost
                run["calls"] += 1
                record_call(ctx, pname, field, key, False, prov.cost, f"error: {type(e).__name__}: {str(e)[:120]}", now)
                continue
            run["spent"] += prov.cost
            run["calls"] += 1
            stamp = now.replace(microsecond=0).isoformat()
            good = {f: v for f, raw_v in raw.items() if (v := validate(f, raw_v, country)) is not None}
            if "email" in good and _bad_email(ctx, good["email"], p):
                good.pop("email")  # never bring back an address that bounced
            conf = prov.confidence
            if field == "email" and "email" in good:
                ok, _ = _verify_email(ctx, cfg, provs, p, good["email"], run, key, now)
                if ok is False:
                    good.pop("email")
                elif ok:
                    conf = max(conf, 0.95)
            record_call(ctx, pname, field, key, field in good, prov.cost,
                        f"returned {sorted(raw)}; valid {sorted(good)}", now)
            for f, v in good.items():
                if f == "email" and f != field and cfg.get("verifier"):
                    continue  # an extra email is only kept once the verifier has passed it
                cache_put(ctx, key, f, v, pname, conf if f == field else prov.confidence, prov.cost if f == field else 0.0, now)
                if f != field and f in fields and f not in results:
                    pending[f] = {"value": v, "provider": pname, "confidence": prov.confidence, "at": stamp, "cost": 0.0,
                                  "source": "provider"}
            if field in good:
                results[field] = {"value": good[field], "provider": pname, "confidence": conf, "at": stamp,
                                  "cost": prov.cost, "source": "provider"}
                break
        else:
            results.setdefault(field, {"status": "not found", "tried": tried})
            if tried and not run["capped"]:
                cache_put(ctx, key, field, None, ",".join(tried)[:80], 0.0, 0.0, now)
        if run["capped"]:
            for f in fields:
                results.setdefault(f, {"status": f"stopped: {run['capped']}"})
            break
    return results


# ---------------------------------------------------------------- apply to contact / account
def apply_to_contact(ctx, contact: dict, results: dict, force: bool = False, now: datetime | None = None) -> dict:
    """Fill empty fields only. A value from the CRM or marked manual is never overwritten. With force, only a
    value that came from an earlier enrichment run may be replaced."""
    now = _now(now)
    prov = dict(contact.get("enrichment") or {})
    manual = set(contact.get("manual_fields") or [])
    changed = {}
    for f, r in results.items():
        if "value" not in r or f in manual:
            continue
        cur = contact.get(f)
        if f == "email" and contact.get("email_invalid"):
            cur = None
        from_enrichment = f in prov and prov[f].get("provider") not in (None, "manual")
        if cur in (None, "") or (force and from_enrichment and cur != r["value"]):
            changed[f] = r["value"]
            prov[f] = {k: r[k] for k in ("value", "provider", "confidence", "at", "cost")}
    if not changed:
        return {"changed": {}, "approvals": []}
    upd = {"id": contact["id"], **changed, "enrichment": prov}
    if "email" in changed:
        upd["email_invalid"] = None
    ctx.store.upsert("contacts", upd)
    approvals = []
    fmap = ctx.manifest.config.get("crm_fields", {})
    if contact.get("crm_id"):
        approvals.append(ctx.request_approval("contact_update", {
            "crm_id": contact["crm_id"], "fields": {fmap.get(f, f): v for f, v in changed.items()},
            "meta": {"agent": ctx.manifest.id, "providers": {f: prov[f]["provider"] for f in changed}}}))
    else:
        acct = ctx.store.account(contact["account_id"]) if contact.get("account_id") else None
        merged = {**contact, **changed}
        if merged.get("email"):
            approvals.append(ctx.request_approval("crm_contact", {
                "fields": {k: merged.get(k) for k in ("name", "email", "title", "phone") if merged.get(k)},
                "account_crm_id": (acct or {}).get("crm_id")}))
    if "phone" in changed and ctx.manifest.config.get("push_new_phones_to_dialer") and \
            not suppression.is_suppressed(ctx.store, (changed.get("email") or contact.get("email")), contact):
        owner = contact.get("owner") or ((ctx.store.account(contact["account_id"]) or {}).get("owner") if contact.get("account_id") else None)
        approvals.append(ctx.request_approval("dialer_enqueue", {
            "contact": {"name": contact.get("name"), "phone": changed["phone"], "email": contact.get("email"),
                        "company": contact.get("company")}, "owner": owner, "meta": {"source": "enrichment"}},
            summary=f"new mobile for {contact.get('name')}: add to {owner or 'owner'}'s call list"))
    return {"changed": changed, "approvals": approvals}


def enrich_contact(ctx, contact: dict, fields: list[str] | None = None, run: dict | None = None,
                   cfg: dict | None = None, force: bool = False, now: datetime | None = None) -> dict:
    run = run if run is not None else new_run()
    if contact.get("do_not_contact") or contact.get("unsubscribed") or contact.get("opted_out"):
        return {"contact": contact.get("id"), "skipped": "do not contact"}
    p = person_from_contact(ctx, contact)
    want = [f for f in (fields or PERSON_FIELDS) if force or not contact.get(f) or (f == "email" and contact.get("email_invalid"))]
    if not want:
        return {"contact": contact["id"], "results": {}, "changed": {}, "approvals": [], "note": "nothing missing"}
    res = waterfall(ctx, p, want, run, cfg, now)
    applied = apply_to_contact(ctx, ctx.store.get("contacts", contact["id"]) or contact, res, force, now)
    return {"contact": contact["id"], "name": contact.get("name"), "results": res, **applied}


def enrich_account(ctx, acct: dict, run: dict | None = None, cfg: dict | None = None, now: datetime | None = None) -> dict:
    run = run if run is not None else new_run()
    cfg = cfg or providers_cfg(ctx)
    want = [f for f in ACCOUNT_FIELDS if acct.get(f) in (None, "")]
    out = {"account": acct["id"], "changed": {}, "approvals": [], "contacts": []}
    if want and acct.get("domain"):
        res = waterfall(ctx, {"domain": acct["domain"], "company": acct.get("name")}, want, run, cfg, now,
                        order_key="account_order", key=f"domain:{acct['domain'].lower()}")
        changed = {f: r["value"] for f, r in res.items() if "value" in r}
        out["results"] = res
        if changed:
            ctx.store.upsert_account({**acct, **changed})
            out["changed"] = changed
            if acct.get("crm_id"):
                fmap = ctx.manifest.config.get("crm_fields_account", {})
                out["approvals"].append(ctx.request_approval("crm_update", {
                    "crm_id": acct["crm_id"], "account": acct.get("name"),
                    "fields": {fmap.get(f, f): v for f, v in changed.items()}}))
    for c in ctx.store.select("contacts", "account_id=?", (acct["id"],)):
        if run["capped"]:
            break
        r = enrich_contact(ctx, c, ["email", "phone", "title"], run, cfg, now=now)
        out["contacts"].append({k: r.get(k) for k in ("contact", "name", "changed", "skipped")})
    return out


# ---------------------------------------------------------------- targets and reports
def target_accounts(ctx) -> set[str]:
    tiers = set(ctx.manifest.config.get("target_tiers", ["A", "B"]))
    rows = ctx.store.query("SELECT account_id, tier, id FROM scores ORDER BY id DESC")
    latest: dict[str, str] = {}
    for r in rows:
        latest.setdefault(r["account_id"], r["tier"])
    return {a for a, t in latest.items() if t in tiers}


def target_contacts(ctx) -> list[dict]:
    accts = target_accounts(ctx)
    out, seen = [], set()
    for a in accts:
        for c in ctx.store.select("contacts", "account_id=?", (a,)):
            if c["id"] not in seen and not c.get("do_not_contact"):
                seen.add(c["id"])
                out.append(c)
    for lead in ctx.store.select("leads", "status=?", ("routed",)):
        c = ctx.store.contact_by_email(lead.get("email") or "")
        if c is None and lead.get("email"):
            ctx.store.upsert("contacts", {"id": lead["email"].lower(), "email": lead["email"].lower(), "name": lead.get("name"),
                                          "title": lead.get("title"), "account_id": lead.get("account_id"),
                                          "owner": lead.get("owner"), "company": lead.get("company")})
            c = ctx.store.get("contacts", lead["email"].lower())
        if c and c["id"] not in seen and not c.get("do_not_contact"):
            seen.add(c["id"])
            out.append(c)
    return out


def missing(c: dict) -> list[str]:
    m = []
    if not normalize_email(c.get("email")) or c.get("email_invalid"):
        m.append("email")
    if not c.get("phone"):
        m.append("phone")
    return m


def waterfall_report(ctx, days: int = 30, now: datetime | None = None) -> dict:
    ensure_schema(ctx)
    now = _now(now)
    since = (now - timedelta(days=days)).replace(microsecond=0).isoformat()
    rows = ctx.store.query("SELECT provider, field, hit, cost, note FROM enrichment_calls WHERE ts>=?", (since,))
    by: dict = {}
    fills: dict = {}
    for r in rows:
        if r["field"] == "verify":
            b = by.setdefault(r["provider"], {"calls": 0, "hits": 0, "cost": 0.0, "fields": {}, "role": "verifier"})
        else:
            b = by.setdefault(r["provider"], {"calls": 0, "hits": 0, "cost": 0.0, "fields": {}, "role": "source"})
        if str(r.get("note") or "").startswith("skipped"):
            b["skipped"] = b.get("skipped", 0) + 1
            continue
        b["calls"] += 1
        b["hits"] += int(r["hit"] or 0)
        b["cost"] += float(r["cost"] or 0)
        f = b["fields"].setdefault(r["field"], {"calls": 0, "hits": 0})
        f["calls"] += 1
        f["hits"] += int(r["hit"] or 0)
        if r["hit"] and r["field"] != "verify":
            fills[r["field"]] = fills.get(r["field"], 0) + 1
    providers = []
    for name, b in sorted(by.items()):
        rate = round(b["hits"] / b["calls"], 3) if b["calls"] else 0.0
        cph = round(b["cost"] / b["hits"], 4) if b["hits"] else None
        providers.append({"provider": name, "role": b["role"], "calls": b["calls"], "hits": b["hits"], "hit_rate": rate,
                          "cost": round(b["cost"], 2), "cost_per_hit": cph, "skipped": b.get("skipped", 0), "fields": b["fields"]})
    recs = []
    total_fills = sum(fills.values())
    for field in sorted({f for b in by.values() for f in b["fields"] if f != "verify"}):
        cands = [(p, p["fields"][field]) for p in providers if field in p["fields"] and p["fields"][field]["hits"]]
        if cands:
            best = min(cands, key=lambda x: ((x[0]["cost_per_hit"] or 0), -x[1]["hits"] / max(1, x[1]["calls"])))
            recs.append(f"{field}: keep {best[0]['provider']} (hit rate {best[1]['hits']}/{best[1]['calls']}, "
                        f"cost per hit ${best[0]['cost_per_hit'] or 0:.2f})")
    for p in providers:
        if p["role"] != "source" or not p["calls"]:
            continue
        share = p["hits"] / total_fills if total_fills else 0
        if share < 0.10:
            recs.append(f"cut candidate: {p['provider']} filled {p['hits']} of {total_fills} values ({share:.0%}) "
                        f"for ${p['cost']:.2f}")
    return {"days": days, "since": since, "calls": sum(p["calls"] for p in providers),
            "spend": round(sum(p["cost"] for p in providers), 2), "fills_by_field": fills, "providers": providers,
            "recommendations": recs}


def coverage_report(ctx) -> dict:
    cs = target_contacts(ctx)
    n = len(cs)
    em = sum(1 for c in cs if normalize_email(c.get("email")) and not c.get("email_invalid"))
    ph = sum(1 for c in cs if normalize_phone(c.get("phone"), c.get("country") or "US"))
    both = sum(1 for c in cs if not missing(c))
    pct = (lambda x: round(100 * x / n, 1) if n else 0.0)
    return {"target_contacts": n, "verified_email": em, "verified_email_pct": pct(em), "valid_phone": ph,
            "valid_phone_pct": pct(ph), "both_pct": pct(both),
            "missing": [{"contact": c["id"], "name": c.get("name"), "missing": missing(c)} for c in cs if missing(c)][:50]}


def format_run(stats: dict) -> str:
    lines = [f"*Enrichment*: {stats['contacts']} contacts checked, {stats['filled']} values found "
             f"({', '.join(f'{k} {v}' for k, v in sorted(stats['by_field'].items())) or 'none'}), "
             f"{stats['calls']} provider calls, ${stats['spent']:.2f} spent."]
    if stats.get("manual"):
        lines.append(f"_Needs manual research: {stats['manual']}._")
    if stats.get("capped"):
        lines.append(f":pause_button: Stopped early: {stats['capped']}.")
    if stats.get("approvals"):
        lines.append(f"CRM updates queued for approval: {stats['approvals']}. Review: `gtm approvals enrichment list`.")
    return "\n".join(lines)
