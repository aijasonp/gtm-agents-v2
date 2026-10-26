"""SEC EDGAR: annual and quarterly filings, 8-K officer changes, and full-text search for discovery.

Uses only the SEC's public endpoints:
  company_tickers.json       ticker and name to CIK
  data.sec.gov/submissions   a company's recent filings (form, date, document, 8-K items)
  Archives/edgar/data        the filing document itself
  efts.sec.gov full-text     which companies' filings mention a phrase (discovery)

Matching an account to a CIK uses, in order: an explicit `cik` or `ticker` on the account, then an
exact normalized company-name match. There is no first-word or fuzzy guess: a wrong CIK would
attach another company's filing to the account.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import text as tx
from .http import SourceClient
from .model import Finding

SEC = "https://www.sec.gov"
DATA = "https://data.sec.gov"
EFTS = "https://efts.sec.gov/LATEST/search-index"

SUFFIXES = r"\b(incorporated|inc|corporation|corp|company|co|holdings?|group|plc|ltd|limited|llc|lp|sa|nv|ag|the)\b"
DEFAULT_BOILERPLATE = ["forward-looking statements", "forward looking statements", "safe harbor",
                       "private securities litigation reform act", "undue reliance", "table of contents",
                       "incorporated by reference"]


def norm_name(name: str) -> str:
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(SUFFIXES, " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class FilingRules:
    """What to look for in filings. Built from the agent's config."""
    topics: list[dict]                       # [{id, terms, weight, required}]
    specificity: list[str] = field(default_factory=list)
    boilerplate: list[str] = field(default_factory=lambda: list(DEFAULT_BOILERPLATE))
    section_boost: dict = field(default_factory=lambda: {"risk_factors": 5, "mda": 3, "business": 2, "other": 0})
    high_needs: list[str] = field(default_factory=list)  # topic ids that must all appear for High confidence

    def compiled(self):
        return [(t["id"], tx.term_re(t.get("terms", [])), float(t.get("weight", 1)), bool(t.get("required")))
                for t in self.topics], tx.term_re(self.specificity), [b.lower() for b in self.boilerplate]


class Edgar:
    def __init__(self, client: SourceClient):
        self.c = client
        self._tickers: dict | None = None

    # ---------- company lookup ----------
    def tickers(self) -> dict:
        if self._tickers is None:
            r = self.c.get(f"{SEC}/files/company_tickers.json")
            rows = list(r.json().values()) if r.ok else []
            by_t, by_n = {}, {}
            for x in rows:
                cik = str(x.get("cik_str", "")).zfill(10)
                by_t[str(x.get("ticker", "")).upper()] = (cik, x.get("title"))
                by_n.setdefault(norm_name(x.get("title", "")), (cik, x.get("title")))
            self._tickers = {"ticker": by_t, "name": by_n, "ok": r.ok, "status": r.status}
        return self._tickers

    def cik_for(self, acct: dict) -> tuple[str | None, str]:
        """(cik, how) where how is cik | ticker | name | not found."""
        if acct.get("cik"):
            return str(acct["cik"]).lstrip("CIK").zfill(10), "cik"
        t = self.tickers()
        if acct.get("ticker") and str(acct["ticker"]).upper() in t["ticker"]:
            return t["ticker"][str(acct["ticker"]).upper()][0], "ticker"
        n = norm_name(acct.get("legal_name") or acct.get("name", ""))
        if n and n in t["name"]:
            return t["name"][n][0], "name"
        return None, "not found"

    def recent_filings(self, cik: str) -> list[dict]:
        r = self.c.get(f"{DATA}/submissions/CIK{cik}.json")
        if not r.ok:
            return []
        rec = (r.json().get("filings") or {}).get("recent") or {}
        keys = ["accessionNumber", "filingDate", "form", "primaryDocument", "items", "primaryDocDescription"]
        n = len(rec.get("accessionNumber", []))
        return [{k: (rec.get(k) or [None] * n)[i] for k in keys} for i in range(n)]

    @staticmethod
    def doc_url(cik: str, f: dict) -> str:
        return f"{SEC}/Archives/edgar/data/{int(cik)}/{f['accessionNumber'].replace('-', '')}/{f['primaryDocument']}"

    def document_text(self, url: str) -> str | None:
        r = self.c.get(url)
        return tx.html_to_text(r.text) if r.ok else None

    # ---------- annual and quarterly filings ----------
    def filing_signal(self, acct: dict, rules: FilingRules, today: date, max_age_days: int = 400,
                      forms: tuple = ("10-K", "10-Q")) -> tuple[Finding | None, str]:
        cik, how = self.cik_for(acct)
        if not cik:
            return None, "no CIK match (add cik or ticker to the account)"
        cutoff = (today - timedelta(days=max_age_days)).isoformat()
        filings = [f for f in self.recent_filings(cik) if f["form"] in forms and (f["filingDate"] or "") >= cutoff]
        if not filings:
            return None, f"no {'/'.join(forms)} filed since {cutoff}"
        f = filings[0]  # newest first
        url = self.doc_url(cik, f)
        body = self.document_text(url)
        if body is None:
            return None, f"could not fetch {url}"
        best = best_quotes(body, rules, f["form"])
        if not best:
            return None, f"{f['form']} {f['filingDate']} has no sentence matching the required topics"
        top = best[0]
        return Finding(account_id=acct["id"], source="filing", signal_type="filing_priority_mention",
                       detail=top["sentence"], url=url, observed_at=f["filingDate"],
                       confidence="High" if top["high"] else "Medium", topics=top["topics"],
                       meta={"filing": f["form"], "section": top["section"], "cik": cik, "cik_match": how,
                             "topic": top["topics"][0].replace("_", " ") if top["topics"] else "",
                             "other_quotes": [b["sentence"] for b in best[1:3]]}), "ok"

    # ---------- 8-K item 5.02: officer appointments and departures ----------
    def officer_changes(self, acct: dict, buyer_roles: list[str], csuite_roles: list[str], today: date,
                        max_age_days: int = 180) -> list[Finding]:
        cik, how = self.cik_for(acct)
        if not cik:
            return []
        cutoff = (today - timedelta(days=max_age_days)).isoformat()
        out = []
        buyer, csuite = tx.term_re(buyer_roles), tx.term_re(csuite_roles)
        for f in self.recent_filings(cik):
            if f["form"] != "8-K" or (f["filingDate"] or "") < cutoff or "5.02" not in str(f.get("items") or ""):
                continue
            url = self.doc_url(cik, f)
            body = self.document_text(url) or ""
            for s in tx.sentences(body):
                low = s.lower()
                appointed = re.search(r"\b(appoint|appointed|named|elected|promoted|hired|will join|to serve as)\b", low)
                departed = re.search(r"\b(resign|resigned|retire|retired|retirement|depart|departure|step down|terminated)\b", low)
                if not (appointed or departed):
                    continue
                role = (tx.hits(buyer, s) or tx.hits(csuite, s))
                if not role:
                    continue
                in_buyer = bool(tx.hits(buyer, s))
                if appointed:
                    st = "new_exec_in_buyer_function" if in_buyer else "new_exec_c_suite"
                elif in_buyer:
                    st = "buyer_departed"
                else:
                    continue
                person = _person(s)
                out.append(Finding(account_id=acct["id"], source="exec_change", signal_type=st,
                                   detail=tx.truncate(s), url=url, observed_at=f["filingDate"],
                                   confidence="High" if in_buyer else "Medium", topics=role,
                                   meta={"filing": "8-K", "item": "5.02", "role": role[0], "person": person, "cik": cik}))
                break  # one finding per 8-K
        return out

    # ---------- discovery ----------
    def full_text_search(self, phrase: str, forms: str, start: date, end: date, limit: int = 100) -> list[dict]:
        """Companies whose filings mention `phrase`. Returns [{cik, name, ticker, form, file_date, url}]."""
        r = self.c.get(EFTS, params={"q": f'"{phrase}"', "forms": forms, "dateRange": "custom",
                                     "startdt": start.isoformat(), "enddt": end.isoformat()})
        if not r.ok:
            return []
        out, seen = [], set()
        for h in (r.json().get("hits") or {}).get("hits", [])[:limit]:
            s = h.get("_source") or {}
            ciks, names = s.get("ciks") or [], s.get("display_names") or []
            if not ciks:
                continue
            cik = str(ciks[0]).zfill(10)
            if cik in seen:
                continue
            seen.add(cik)
            raw = names[0] if names else ""
            m = re.match(r"\s*(.*?)\s*(?:\(([A-Z0-9.\-, ]+)\))?\s*\(CIK", raw)
            name = (m.group(1) if m else raw).strip()
            ticker = (m.group(2) or "").split(",")[0].strip() if m and m.group(2) else ""
            adsh, _, fname = (h.get("_id") or "").partition(":")
            url = f"{SEC}/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{fname}" if adsh and fname else ""
            out.append({"cik": cik, "name": name, "ticker": ticker, "form": s.get("form") or s.get("file_type"),
                        "file_date": s.get("file_date"), "url": url, "phrase": phrase})
        return out


def _person(sentence: str) -> str:
    """The name right after the appointment verb ("appointed Dana Cole as ..."), else empty."""
    m = re.search(r"\b(?:appointed|named|elected|promoted|hired)\s+(?:(?:Mr|Ms|Mrs|Dr)\.?\s+)?"
                  r"([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-zA-Z'\-]+)", sentence)
    return m.group(1) if m else ""


ITEM = re.compile(r"^\s*(?:part\s+[iv]+[,.\s]+)?item\s+(\d{1,2}[a-c]?)\s*[.:\-]?\s*(.{0,90})$", re.I)


def sections(body: str, form: str) -> list[tuple[str, str]]:
    """[(label, text)] for risk_factors, mda and business. The table of contents also lists every item,
    so for each label the longest span wins. Unlabeled documents come back as [("other", body)]."""
    lines = body.split("\n")
    heads = []
    for i, line in enumerate(lines):
        if len(line) > 120:
            continue
        m = ITEM.match(line)
        if m:
            heads.append((i, m.group(1).lower(), m.group(2).lower()))
    best: dict[str, str] = {}
    for k, (i, num, title) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        span = "\n".join(lines[i + 1:end])
        if "risk factor" in title or num == "1a":
            label = "risk_factors"
        elif ("management" in title and "discussion" in title) or (num == "7" and form.startswith("10-K")) \
                or (num == "2" and form.startswith("10-Q") and "discussion" in title):
            label = "mda"
        elif num == "1" and form.startswith("10-K") and ("business" in title or not title):
            label = "business"
        else:
            continue
        if len(span) > len(best.get(label, "")):
            best[label] = span
    return list(best.items()) or [("other", body)]


def best_quotes(body: str, rules: FilingRules, form: str = "10-K", top: int = 3) -> list[dict]:
    topics, spec, boiler = rules.compiled()
    required = [t for t in topics if t[3]] or topics
    scored = []
    for label, span in sections(body, form):
        boost = float(rules.section_boost.get(label, 0))
        for s in tx.sentences(span):
            if not 40 <= len(s) <= 900:
                continue
            low = s.lower()
            if any(b in low for b in boiler):
                continue
            if not any(tx.hits(p, s) for _, p, _, _ in required):
                continue
            score, matched = boost, []
            for tid, p, w, _ in topics:
                h = tx.hits(p, s)
                if h:
                    matched.append(tid)
                    score += w * len(h)
            score += len(tx.hits(spec, s))
            high = bool(rules.high_needs) and all(t in matched for t in rules.high_needs)
            scored.append({"sentence": tx.truncate(s), "score": round(score, 2), "topics": matched,
                           "section": label, "high": high})
    scored.sort(key=lambda d: -d["score"])
    seen, out = set(), []
    for d in scored:
        if d["sentence"] in seen:
            continue
        seen.add(d["sentence"])
        out.append(d)
        if len(out) >= top:
            break
    return out
