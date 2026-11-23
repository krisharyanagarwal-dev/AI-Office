"""Tests for the request paths that render recent dost tasks.

The dashboard, the tasks API and the results page all read recent ``dost``
tasks. They used to open and parse every task file in the hive on each
request, so a hive with thousands of tasks made those endpoints hang whenever
the disk was busy. The background refresher already visits every task file, so
the per-file index it keeps is now the source for these panels: the request
path must not read hive task files at all.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

OFFICE_OS_ROOT = Path("/Users/aryanagarwal/AI-Office/packages/office-os")
sys.path.insert(0, str(OFFICE_OS_ROOT))

web_server = pytest.importorskip("core.web_server")

DOST_TASK_COUNT = 10
JEV_TASK_COUNT = 290


def _task(task_id: str, source: str, updated_at: str) -> dict:
    return {
        "id": task_id,
        "status": "done",
        "agent_id": "agent-a",
        "title": f"title {task_id}",
        "created_at": updated_at,
        "updated_at": updated_at,
        "metadata": {"source": source},
        "result": f"result {task_id}",
    }


@pytest.fixture()
def hive(tmp_path, monkeypatch):
    """A hive with a few dost tasks among many jev tasks, plus a primed index."""
    hive_dir = tmp_path / "tasks"
    hive_dir.mkdir()

    dost_ids = []
    for i in range(1, DOST_TASK_COUNT + 1):
        task_id = f"dost-{i:02d}"
        dost_ids.append(task_id)
        stamp = f"2026-11-{i:02d}T10:00:00Z"
        path = hive_dir / f"{task_id}.json"
        path.write_text(json.dumps(_task(task_id, "dost", stamp)))

    for i in range(JEV_TASK_COUNT):
        task_id = f"jev-{i:03d}"
        stamp = f"2026-12-{i % 28 + 1:02d}T10:00:00Z"
        path = hive_dir / f"{task_id}.json"
        path.write_text(json.dumps(_task(task_id, "jev-cloud-orchestrator", stamp)))

    # The newest task file is the oldest dost task, so an implementation that
    # orders by file mtime cannot pass the ordering assertion.
    for index, path in enumerate(sorted(hive_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)):
        path.touch()

    monkeypatch.setattr(web_server, "HIVE_DIR", str(hive_dir))
    monkeypatch.setattr(
        web_server, "HIVE_METRICS_STATE_FILE", str(tmp_path / "state" / "hive_metrics.json")
    )
    monkeypatch.setattr(web_server, "_HIVE_METRICS_FILE_STATE", {})
    monkeypatch.setattr(web_server, "_HIVE_METRICS_STATE_LOADED_PATH", None)

    web_server._refresh_hive_metrics()

    return {"dir": hive_dir, "dost_ids": dost_ids}


@pytest.fixture()
def hive_read_counter(hive, monkeypatch):
    """Count reads of hive task files performed after the index is primed."""
    hive_dir = str(hive["dir"])
    counter = {"n": 0}
    real_open = builtins.open
    real_io_open = io.open

    def _is_hive_path(file) -> bool:
        try:
            path = Path(os.fspath(file))
        except TypeError:
            return False
        if path.suffix != ".json":
            return False
        return path.parent.name == "tasks"

    def counting_open(file, *args, **kwargs):
        if _is_hive_path(file):
            counter["n"] += 1
        return real_open(file, *args, **kwargs)

    def counting_io_open(file, *args, **kwargs):
        if _is_hive_path(file):
            counter["n"] += 1
        return real_io_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    monkeypatch.setattr(io, "open", counting_io_open)
    return counter


@pytest.fixture()
def server(monkeypatch):
    monkeypatch.setattr(
        web_server.OfficeHandler,
        "_build_metrics_payload",
        lambda self: {
            "jev": {
                "tasks_created": 1,
                "tasks_done": 1,
                "completion_rate": 100.0,
                "error_rate": 0.0,
                "calls_today": 1,
                "tasks_per_min": 0.0,
            },
            "provider_pools": {},
            "free_ceiling": {"headroom_pct": 100},
        },
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.OfficeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as resp:
        assert resp.status == 200
        return resp.read().decode("utf-8")


def test_dashboard_renders_dost_tasks_without_reading_the_hive(server, hive, hive_read_counter):
    html = _get(f"{server}/dashboard")

    assert hive_read_counter["n"] == 0
    for task_id in hive["dost_ids"]:
        assert task_id in html
    assert "jev-001" not in html
    assert html.index("dost-10") < html.index("dost-01")


def test_tasks_api_serves_dost_tasks_without_reading_the_hive(server, hive, hive_read_counter):
    payload = json.loads(_get(f"{server}/api/tasks"))

    assert hive_read_counter["n"] == 0
    assert payload["total"] == DOST_TASK_COUNT
    assert [t["id"] for t in payload["tasks"]] == list(reversed(hive["dost_ids"]))


def test_results_page_renders_dost_tasks_without_reading_the_hive(server, hive, hive_read_counter):
    html = _get(f"{server}/results")

    assert hive_read_counter["n"] == 0
    for task_id in hive["dost_ids"]:
        assert task_id in html
    assert "jev-001" not in html


def test_dost_task_index_survives_a_restart(hive, tmp_path, monkeypatch):
    monkeypatch.setattr(web_server, "_HIVE_METRICS_FILE_STATE", {})
    monkeypatch.setattr(web_server, "_HIVE_METRICS_STATE_LOADED_PATH", None)

    tasks = web_server._recent_dost_tasks(DOST_TASK_COUNT)

    assert [t["id"] for t in tasks] == list(reversed(hive["dost_ids"]))
