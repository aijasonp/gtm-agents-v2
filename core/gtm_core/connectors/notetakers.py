"""Pull call transcripts from Gong, Fireflies or Fathom into the meetings table.

Each puller returns meetings as {id, title, started_at, attendees, transcript, source, url}, with the
transcript as "Speaker: text" lines that gtm_core.transcripts parses. Meeting Intelligence picks up
anything with processed_at empty. Set one of:

  GONG_ACCESS_KEY + GONG_ACCESS_SECRET (+ GONG_BASE_URL, default https://api.gong.io)
  FIREFLIES_API_KEY
  FATHOM_API_KEY

Every puller takes an httpx client for tests. Nothing here writes to a CRM.
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx


def _lines(turns: list[tuple[str, str]]) -> str:
    out, last = [], None
    for spk, text in turns:
        text = (text or "").strip()
        if not text:
            continue
        spk = (spk or "Unknown").strip()
        if spk == last and out:
            out[-1] += " " + text
        else:
            out.append(f"{spk}: {text}")
            last = spk
    return "\n".join(out)


class Gong:
    source = "gong"

    def __init__(self, key: str, secret: str, base: str = "https://api.gong.io", client: httpx.Client | None = None):
        self.auth = (key, secret)
        self.base = base.rstrip("/")
        self.http = client or httpx.Client(timeout=60)

    def pull(self, since: datetime, until: datetime | None = None) -> list[dict]:
        flt = {"fromDateTime": since.isoformat()}
        if until:
            flt["toDateTime"] = until.isoformat()
        calls, cursor = {}, None
        while True:
            body = {"filter": flt, "contentSelector": {"exposedFields": {"parties": True}}}
            if cursor:
                body["cursor"] = cursor
            r = self.http.post(f"{self.base}/v2/calls/extensive", json=body, auth=self.auth)
            r.raise_for_status()
            d = r.json()
            for c in d.get("calls", []):
                meta = c.get("metaData", {})
                parties = {p.get("speakerId"): p for p in c.get("parties", []) if p.get("speakerId")}
                calls[meta.get("id")] = {"meta": meta, "parties": parties,
                                         "attendees": [p.get("emailAddress") or p.get("name") for p in c.get("parties", [])
                                                       if p.get("emailAddress") or p.get("name")]}
            cursor = (d.get("records") or {}).get("cursor")
            if not cursor:
                break
        if not calls:
            return []
        r = self.http.post(f"{self.base}/v2/calls/transcript", json={"filter": {**flt, "callIds": list(calls)}},
                           auth=self.auth)
        r.raise_for_status()
        out = []
        for t in r.json().get("callTranscripts", []):
            c = calls.get(t.get("callId"))
            if not c:
                continue
            turns = []
            for mono in t.get("transcript", []):
                p = c["parties"].get(mono.get("speakerId"), {})
                for s in mono.get("sentences", []):
                    turns.append((p.get("name") or "Unknown", s.get("text")))
            out.append({"id": f"gong:{t['callId']}", "title": c["meta"].get("title"), "started_at": c["meta"].get("started"),
                        "attendees": c["attendees"], "transcript": _lines(turns), "source": self.source,
                        "url": c["meta"].get("url")})
        return out


class Fireflies:
    source = "fireflies"
    URL = "https://api.fireflies.ai/graphql"
    QUERY = """query($fromDate: DateTime, $limit: Int, $skip: Int) {
  transcripts(fromDate: $fromDate, limit: $limit, skip: $skip) {
    id title dateString participants transcript_url
    sentences { speaker_name text }
  }
}"""

    def __init__(self, key: str, client: httpx.Client | None = None):
        self.headers = {"authorization": f"Bearer {key}"}
        self.http = client or httpx.Client(timeout=60)

    def pull(self, since: datetime, until: datetime | None = None, page: int = 25) -> list[dict]:
        out, skip = [], 0
        while True:
            r = self.http.post(self.URL, headers=self.headers, json={
                "query": self.QUERY, "variables": {"fromDate": since.isoformat(), "limit": page, "skip": skip}})
            r.raise_for_status()
            d = r.json()
            if d.get("errors"):
                raise RuntimeError(f"Fireflies: {d['errors'][0].get('message')}")
            rows = (d.get("data") or {}).get("transcripts") or []
            for t in rows:
                out.append({"id": f"fireflies:{t['id']}", "title": t.get("title"), "started_at": t.get("dateString"),
                            "attendees": t.get("participants") or [], "source": self.source, "url": t.get("transcript_url"),
                            "transcript": _lines([(s.get("speaker_name"), s.get("text")) for s in t.get("sentences") or []])})
            if len(rows) < page:
                break
            skip += page
        return out


class Fathom:
    source = "fathom"
    URL = "https://api.fathom.ai/external/v1/meetings"

    def __init__(self, key: str, client: httpx.Client | None = None):
        self.headers = {"X-Api-Key": key}
        self.http = client or httpx.Client(timeout=60)

    def pull(self, since: datetime, until: datetime | None = None) -> list[dict]:
        params = {"include_transcript": "true", "created_after": since.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if until:
            params["created_before"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")
        out = []
        while True:
            r = self.http.get(self.URL, headers=self.headers, params=params)
            r.raise_for_status()
            d = r.json()
            for m in d.get("items", []):
                turns = [((t.get("speaker") or {}).get("display_name"), t.get("text")) for t in m.get("transcript") or []]
                rid = m.get("recording_id") or m.get("url")
                out.append({"id": f"fathom:{rid}", "title": m.get("title") or m.get("meeting_title"),
                            "started_at": m.get("recording_start_time") or m.get("created_at"),
                            "attendees": [i.get("email") or i.get("name") for i in m.get("calendar_invitees") or []
                                          if i.get("email") or i.get("name")],
                            "transcript": _lines(turns), "source": self.source, "url": m.get("share_url") or m.get("url")})
            if not d.get("next_cursor"):
                break
            params["cursor"] = d["next_cursor"]
        return out


def from_env() -> list:
    out = []
    if os.environ.get("GONG_ACCESS_KEY") and os.environ.get("GONG_ACCESS_SECRET"):
        out.append(Gong(os.environ["GONG_ACCESS_KEY"], os.environ["GONG_ACCESS_SECRET"],
                        os.environ.get("GONG_BASE_URL", "https://api.gong.io")))
    if os.environ.get("FIREFLIES_API_KEY"):
        out.append(Fireflies(os.environ["FIREFLIES_API_KEY"]))
    if os.environ.get("FATHOM_API_KEY"):
        out.append(Fathom(os.environ["FATHOM_API_KEY"]))
    return out


def store_meetings(store, meetings: list[dict]) -> dict:
    """Upsert pulled meetings. A meeting already stored with the same transcript is left alone, so
    re-pulls do not trigger re-analysis; a changed transcript clears processed_at."""
    added = updated = unchanged = empty = 0
    for m in meetings:
        if not (m.get("transcript") or "").strip():
            empty += 1
            continue
        old = store.get("meetings", m["id"])
        if old and old.get("transcript") == m["transcript"]:
            unchanged += 1
            continue
        store.upsert("meetings", {**m, "processed_at": None})
        added += 0 if old else 1
        updated += 1 if old else 0
    return {"added": added, "updated": updated, "unchanged": unchanged, "empty": empty}
