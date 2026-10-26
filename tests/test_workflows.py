import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

from gtm_core.store import Store
from gtm_core.workflows import Waits, get_waits


def _store():
    st = Store("sqlite:///:memory:")
    st.init()
    return st


def test_ladder_fires_once_per_level_and_catches_up():
    w = Waits(_store())
    t0 = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
    ladder = [{"after_hours": 0, "notify": "owner"}, {"after_hours": 8, "notify": "manager"}]
    w.open("approval", "a1", t0, ladder, owner="Sam")
    assert w.open("approval", "a1", t0 + timedelta(days=1), ladder)["deadline_at"] == t0.isoformat()  # idempotent
    assert w.due(t0 - timedelta(minutes=1)) == []
    assert [x["notify"] for x in w.due(t0)] == ["owner"]
    assert w.due(t0 + timedelta(hours=1)) == []
    assert [x["notify"] for x in w.due(t0 + timedelta(hours=9))] == ["manager"]
    assert w.get("approval", "a1")["status"] == "exhausted" and w.due(t0 + timedelta(days=3)) == []
    # a scheduler that was down all day sends every overdue level in one tick, once each
    w.open("touch", "b1", t0, ladder)
    assert [x["notify"] for x in w.due(t0 + timedelta(days=1))] == ["owner", "manager"]


def test_resolve_and_cancel_stop_escalation():
    w = Waits(_store())
    t0 = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
    w.open("approval", "x", t0)
    w.open("approval", "y", t0)
    assert w.resolve("approval", "x", "approved", by="Sam") and not w.resolve("approval", "x")
    assert w.cancel("approval", "y", "deal closed")
    assert w.due(t0 + timedelta(days=2)) == []
    assert w.get("approval", "x")["resolved_by"] == "Sam"


def test_two_runners_never_claim_the_same_level():
    st = _store()
    a, b = Waits(st), Waits(st)
    t0 = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
    a.open("approval", "z", t0, [{"after_hours": 0, "notify": "owner"}])
    got = a.due(t0) + b.due(t0)
    assert len(got) == 1


def test_dbos_backend_falls_back_when_missing(monkeypatch):
    monkeypatch.setenv("GTM_WORKFLOW_BACKEND", "dbos")
    monkeypatch.setitem(sys.modules, "dbos", None)  # simulate not installed
    w = get_waits(_store())
    assert w.backend == "builtin"


def test_dbos_backend_escalates_on_time(tmp_path):
    pytest.importorskip("dbos")
    script = textwrap.dedent(f"""
        import os, sys, time
        from datetime import datetime, timedelta, timezone
        sys.path.insert(0, "core")
        os.environ["GTM_WORKFLOW_BACKEND"] = "dbos"
        from dbos import DBOS
        DBOS(config={{"name": "gtm-test", "system_database_url": "sqlite:///{tmp_path}/dbos.sqlite"}})
        from gtm_core.store import Store
        from gtm_core import workflows as W
        st = Store("sqlite:///{tmp_path}/gtm.db"); st.init()
        hits = []
        W.on_escalation("approval")(lambda w: hits.append((w["subject"], w["notify"])))
        waits = W.get_waits(st)
        DBOS.launch()
        now = datetime.now(timezone.utc)
        waits.open("approval", "a1", now + timedelta(seconds=1),
                   [{{"after_hours": 0, "notify": "owner"}}, {{"after_hours": 1 / 3600, "notify": "manager"}}])
        waits.open("approval", "a2", now + timedelta(seconds=2), [{{"after_hours": 0, "notify": "owner"}}])
        time.sleep(0.5); waits.resolve("approval", "a2", "approved", by="Sam")
        time.sleep(4)
        print(type(waits).__name__, sorted(hits), sorted((w["subject"], w["status"]) for w in waits.list(status=None)))
        DBOS.destroy()
    """)
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    line = r.stdout.strip().splitlines()[-1]
    assert line == "DbosWaits [('a1', 'manager'), ('a1', 'owner')] [('a1', 'exhausted'), ('a2', 'done')]", line
