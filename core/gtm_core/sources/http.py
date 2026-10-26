"""A polite HTTP client for public data sources.

  - Identifies itself. SEC requires a User-Agent with a name and contact email
    (GTM_SOURCES_USER_AGENT, for example "Beacon Revenue research@beacon.example").
  - Paces requests per host (SEC allows 10 per second; the default here is 4).
  - Retries 429 and 5xx with backoff, honoring Retry-After.
  - Caches responses for the run, so one filing is fetched once.
  - Never disguises itself, rotates fingerprints or works around a block. A blocked
    source is logged and skipped.

Every fetch result, success or failure, is returned to the caller with its status so
nothing fails silently; callers log failures to the audit log.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

DEFAULT_UA = "gtm-agents signal sourcing (set GTM_SOURCES_USER_AGENT to 'Company contact@email')"


@dataclass
class Fetched:
    url: str
    status: int
    text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        import json
        return json.loads(self.text)


class SourceClient:
    def __init__(self, user_agent: str | None = None, per_host_rps: float = 4.0, retries: int = 3,
                 timeout: float = 30.0, client: httpx.Client | None = None, sleep=time.sleep):
        self.ua = user_agent or os.environ.get("GTM_SOURCES_USER_AGENT") or DEFAULT_UA
        self.min_gap = 1.0 / per_host_rps if per_host_rps > 0 else 0.0
        self.retries = retries
        self.http = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.sleep = sleep
        self._last: dict[str, float] = {}
        self._cache: dict[str, Fetched] = {}
        self.log: list[dict] = []

    def _pace(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None and self.min_gap:
            wait = self.min_gap - (time.monotonic() - last)
            if wait > 0:
                self.sleep(wait)
        self._last[host] = time.monotonic()

    def get(self, url: str, params: dict | None = None, headers: dict | None = None, cache: bool = True) -> Fetched:
        key = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())) if params else "")
        if cache and key in self._cache:
            return self._cache[key]
        host = urlparse(url).netloc
        h = {"User-Agent": self.ua, "Accept-Encoding": "gzip, deflate", **(headers or {})}
        out = Fetched(url, 0, error="not attempted")
        for attempt in range(self.retries + 1):
            self._pace(host)
            try:
                r = self.http.get(url, params=params, headers=h)
            except httpx.HTTPError as e:
                out = Fetched(url, 0, error=f"{type(e).__name__}: {e}"[:300])
            else:
                out = Fetched(url, r.status_code, r.text if r.status_code < 400 else "",
                              "" if r.status_code < 400 else f"HTTP {r.status_code}")
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
                ra = r.headers.get("retry-after")
                if ra and ra.isdigit():
                    self.sleep(min(float(ra), 60.0))
                    continue
            if attempt < self.retries:
                self.sleep(min(2 ** attempt, 30))
        self.log.append({"url": key, "status": out.status, "error": out.error})
        if cache and (out.ok or out.status == 404):
            self._cache[key] = out
        return out
