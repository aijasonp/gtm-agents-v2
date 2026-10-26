import json

import httpx

from gtm_core.agents import load_module
from gtm_core.connectors.floqer import FloqerSheet, pick


class FakeFloqer:
    """In-memory Floqer sheet speaking the REST shapes."""

    def __init__(self):
        self.rows = [{"row_id": "r0", "row_status": "complete", "inputs": {"email": "old@nw.example"}}]
        self.ran = []
        self.n = 0

    def handler(self, req):
        assert req.headers["authorization"] == "Bearer fk"
        path = req.url.path.split("/sheets/s1", 1)[1]
        body = json.loads(req.content or b"{}")
        if path == "/rows/list":
            page = body["page_no"]
            return httpx.Response(200, json={"status": 200, "data": {"rows": self.rows if page == 1 else []}})
        if path == "/rows":
            ids = []
            for r in body["rows"]:
                self.n += 1
                ids.append(f"r{self.n}")
                self.rows.append({"row_id": f"r{self.n}", "row_status": "queued", "inputs": r})
            assert body["run_after_add"] == "none"
            return httpx.Response(200, json={"status": 200, "data": {"row_ids": ids}})
        if path == "/run":
            self.ran.append(body["row_ids"])
            for r in self.rows:
                if r["row_id"] in body["row_ids"]:
                    r["row_status"] = "complete"
                    r["cells"] = {"person_enrich_01lq": {"outputs": {"phone_number": "(415) 555-0199"}}}
            return httpx.Response(200, json={"status": 200})
        return httpx.Response(404)


def sheet(fake):
    return FloqerSheet("fk", "w1", "s1", httpx.Client(transport=httpx.MockTransport(fake.handler)))


def test_pick_tries_paths_in_order_across_outputs_and_cells():
    row = {"outputs": {"a": {"x": ""}}, "cells": {"b": {"outputs": {"phone_number": "1"}}}}
    assert pick(row, "a.x | b.phone_number") == "1" and pick(row, "zzz.y") is None


def test_push_is_idempotent_and_runs_only_new_rows():
    f = FakeFloqer()
    s = sheet(f)
    res = s.push([{"email": "old@nw.example"}, {"email": "dana@nw.example"}])
    assert res == {"pushed": 1, "already_in_sheet": 1, "row_ids": ["r1"], "ran": True} and f.ran == [["r1"]]
    assert s.push([{"email": "dana@nw.example"}])["pushed"] == 0
    got = s.results(["r1"], {"phone": "person_enrich_01lq.phone_number"})
    assert got == {"done": [{"email": "dana@nw.example", "status": "complete", "phone": "(415) 555-0199"}], "pending": []}


def test_enrichment_push_and_import_fill_missing_phone(ctx_for):
    ctx = ctx_for("enrichment")
    f = FakeFloqer()
    ctx.floqer = sheet(f)
    ctx.store.upsert("contacts", {"id": "c1", "name": "Dana Ruiz", "email": "dana@nw.example", "title": "VP Sales"})
    ctx.store.upsert("contacts", {"id": "c2", "name": "Opt Out", "email": "no@nw.example", "unsubscribed": True})
    eng = load_module(ctx.manifest, "engine")
    import yaml
    cfg = yaml.safe_load(open("agents/enrichment/skill/references/providers.yaml"))
    cfg["floqer"] = {"outputs": {"phone": "person_enrich_01lq.phone_number"}}
    eng.providers_cfg = lambda c, o=None: cfg
    res = eng.push_to_floqer(ctx)
    assert res["contacts"] == ["dana@nw.example"] and res["pushed"] == 1  # opted-out contacts are never sent
    out = eng.import_floqer(ctx)
    assert out == {"imported": 1, "filled": 1, "pending": 0}
    assert ctx.store.get("contacts", "c1")["phone"] == "+14155550199"
