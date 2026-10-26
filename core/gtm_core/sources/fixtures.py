"""Recorded responses for tests, evals and demos: a SourceClient that never touches the network.

routes.json maps a URL (query string ignored) to a file in the same folder. Unknown URLs return 404,
the same as a source that has nothing for that company.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from .http import SourceClient


def fixture_client(folder: str | Path) -> SourceClient:
    folder = Path(folder)
    routes = json.loads((folder / "routes.json").read_text())

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url).split("?", 1)[0]
        name = routes.get(url)
        if not name:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=(folder / name).read_text())

    return SourceClient(user_agent="gtm-agents tests test@beacon.example", per_host_rps=0,
                        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
