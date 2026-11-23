"""Tests for the office-os /metrics payload build.

The metrics payload used to scan the whole hive task directory on every
request. With ~13k task files that scan took 26s under load, so the request
path blew past the server's own 8s budget and past the doctor's 4s timeout,
and the provider pool status — the part the doctor actually reads — was
buried under the scan.

The hive aggregate is now built off the request path: readers get the
last-known aggregate immediately, a background refresh rescans the hive
incrementally (only files whose mtime/size changed are re-read), and the
aggregate plus the per-file index is persisted so a cold start serves
last-known values instead of zeros.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

OFFICE_OS_ROOT = Path("/Users/aryanagarwal/AI-Office/packages/office-os")
sys.path.insert(0, str(OFFICE_OS_ROOT))

web_server = pytest.importorskip("core.web_server")


def _task(source: str, status: str, updated_at: str | None = None) -> dict:
    task = {"metadata": {"source": source}, "status": status}
    if updated_at:
        task["updated_at"] = updated_at
    return task


@pytest.fixture(autouse=True)
def reset_hive_metrics_state(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server, "HIVE_METRICS_STATE_FILE", str(tmp_path / "hive_metrics.json"))
    web_server._HIVE_METRICS_CACHE.clear()
    web_server._HIVE_METRICS_FILE_STATE.clear()
    web_server._HIVE_METRICS_LAST_PERSIST_TS = 0.0
    yield
    web_server._HIVE_METRICS_CACHE.clear()
    web_server._HIVE_METRICS_FILE_STATE.clear()
    web_server._HIVE_METRICS_LAST_PERSIST_TS = 0.0


@pytest.fixture
def hive(tmp_path, monkeypatch):
    hive_dir = tmp_path / "tasks"
    hive_dir.mkdir()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    files = {
        "a.json": _task("jev-cloud-orchestrator", "done", now),
        "b.json": _task("jev-cloud-orchestrator", "error", now),
        "c.json": _task("jev-cloud-orchestrator", "pending", now),
        "d.json": _task("other-source", "done", now),
    }
    for name, payload in files.items():
        (hive_dir / name).write_text(json.dumps(payload))
    monkeypatch.setattr(web_server, "HIVE_DIR", str(hive_dir))
    return hive_dir


class _HiveOpenCounter:
    """Counts opens of hive task files inside web_server."""

    def __init__(self, hive_dir, delay: float = 0.0):
        self.hive_dir = str(hive_dir)
        self.count = 0
        self.delay = delay

    def __call__(self, path, *args, **kwargs):
        if str(path).startswith(self.hive_dir):
            self.count += 1
            if self.delay:
                time.sleep(self.delay)
        return open(path, *args, **kwargs)


def _build_payload(hive_dir, monkeypatch):
    counter = _HiveOpenCounter(hive_dir)
    monkeypatch.setattr(web_server, "open", counter, raising=False)
    handler = web_server.OfficeHandler.__new__(web_server.OfficeHandler)
    payload = handler._build_metrics_payload()
    return payload, counter


def test_refresh_reads_each_hive_file_once(hive, monkeypatch):
    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)

    data = web_server._refresh_hive_metrics()

    assert counter.count == 4
    assert data["tasks_created_total"] == 3
    assert data["tasks_done_total"] == 1


def test_repeat_refresh_does_not_reread_unchanged_files(hive, monkeypatch):
    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)

    web_server._refresh_hive_metrics()
    first_count = counter.count
    web_server._refresh_hive_metrics()

    assert first_count == 4
    assert counter.count == first_count


def test_changed_file_is_reread_and_counters_update(hive, monkeypatch):
    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)

    web_server._refresh_hive_metrics()
    (hive / "b.json").write_text(
        json.dumps(_task("jev-cloud-orchestrator", "done", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    )
    data = web_server._refresh_hive_metrics()

    assert counter.count == 5
    assert data["tasks_done_total"] == 2
    assert data["errors_total"] == 0


def test_new_file_is_counted(hive, monkeypatch):
    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)

    web_server._refresh_hive_metrics()
    (hive / "e.json").write_text(
        json.dumps(_task("jev-cloud-orchestrator", "done", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    )
    data = web_server._refresh_hive_metrics()

    assert data["tasks_created_total"] == 4
    assert data["tasks_done_total"] == 2


def test_removed_file_is_dropped(hive, monkeypatch):
    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)

    web_server._refresh_hive_metrics()
    (hive / "c.json").unlink()
    data = web_server._refresh_hive_metrics()

    assert data["tasks_created_total"] == 2


def test_metrics_payload_counts_hive_tasks_and_reports_pools(hive, monkeypatch):
    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)
    web_server._refresh_hive_metrics()

    handler = web_server.OfficeHandler.__new__(web_server.OfficeHandler)
    payload = handler._build_metrics_payload()
    jev = payload["jev"]

    assert jev["tasks_created"] == 3
    assert jev["tasks_done"] == 1
    assert jev["tasks_created_total"] == 3
    assert jev["tasks_done_total"] == 1
    assert jev["error_rate_total"] == round(1 / 3 * 100, 1)
    assert "provider_pools" in payload


def test_metrics_payload_returns_while_hive_refresh_is_still_running(hive, monkeypatch):
    """A slow hive scan must not block the payload the doctor reads."""
    counter = _HiveOpenCounter(hive, delay=1.0)
    monkeypatch.setattr(web_server, "open", counter, raising=False)
    monkeypatch.setattr(web_server, "_schedule_hive_metrics_refresh", lambda: False)

    def _refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(web_server.urllib.request, "urlopen", _refuse)

    refresh_thread = threading.Thread(target=web_server._refresh_hive_metrics, daemon=True)
    refresh_thread.start()

    deadline = time.time() + 5
    while counter.count == 0 and time.time() < deadline:
        time.sleep(0.01)
    assert counter.count >= 1, "refresh never started reading the hive"

    started = time.time()
    handler = web_server.OfficeHandler.__new__(web_server.OfficeHandler)
    payload = handler._build_metrics_payload()
    elapsed = time.time() - started

    assert elapsed < 0.5, f"payload build waited on the hive scan ({elapsed:.2f}s)"
    assert "provider_pools" in payload
    assert refresh_thread.is_alive()

    refresh_thread.join(timeout=10)


def test_stale_metrics_schedule_a_background_refresh(hive, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        web_server, "_schedule_hive_metrics_refresh", lambda: scheduled.append(True) or True
    )

    handler = web_server.OfficeHandler.__new__(web_server.OfficeHandler)
    handler._build_metrics_payload()

    assert scheduled == [True]


def test_fresh_metrics_do_not_schedule_a_refresh(hive, monkeypatch):
    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)
    web_server._refresh_hive_metrics()

    scheduled = []
    monkeypatch.setattr(
        web_server, "_schedule_hive_metrics_refresh", lambda: scheduled.append(True) or True
    )

    handler = web_server.OfficeHandler.__new__(web_server.OfficeHandler)
    handler._build_metrics_payload()

    assert scheduled == []


def test_cold_start_serves_persisted_aggregate_without_reading_the_hive(tmp_path, monkeypatch):
    hive_dir = tmp_path / "tasks"
    hive_dir.mkdir()
    monkeypatch.setattr(web_server, "HIVE_DIR", str(hive_dir))

    state_file = tmp_path / "hive_metrics.json"
    state_file.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "aggregate": {
                    "tasks_created_total": 42,
                    "tasks_done_total": 40,
                    "errors_total": 1,
                    "tasks_created": 7,
                    "tasks_done": 6,
                    "errors_cycle": 1,
                    "tasks_per_min": 0,
                },
                "files": {},
            }
        )
    )

    counter = _HiveOpenCounter(hive_dir)
    monkeypatch.setattr(web_server, "open", counter, raising=False)

    handler = web_server.OfficeHandler.__new__(web_server.OfficeHandler)
    payload = handler._build_metrics_payload()

    assert payload["jev"]["tasks_created_total"] == 42
    assert payload["jev"]["tasks_done_total"] == 40
    assert counter.count == 0


def test_payload_marks_hive_data_as_ready_only_once_scanned(hive, monkeypatch):
    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)
    monkeypatch.setattr(web_server, "_schedule_hive_metrics_refresh", lambda: False)

    handler = web_server.OfficeHandler.__new__(web_server.OfficeHandler)
    cold = handler._build_metrics_payload()
    assert cold["jev"]["data_ready"] is False

    web_server._refresh_hive_metrics()
    warm = handler._build_metrics_payload()
    assert warm["jev"]["data_ready"] is True


def test_periodic_refresher_refreshes_the_aggregate_without_any_request(hive, monkeypatch):
    """The aggregate must stay current even when nobody polls /metrics.

    The doctor reads the metrics payload's own age. If the payload only
    refreshes when a request arrives, a quiet server reports a stale
    aggregate and the doctor reports a false outage.
    """
    assert hasattr(web_server, "_start_hive_metrics_refresher"), (
        "the web server has no periodic hive-metrics refresher"
    )

    counter = _HiveOpenCounter(hive)
    monkeypatch.setattr(web_server, "open", counter, raising=False)

    stop_event = web_server._start_hive_metrics_refresher(interval_sec=0.05)
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not web_server._HIVE_METRICS_CACHE.get("ready"):
            time.sleep(0.01)
        assert web_server._HIVE_METRICS_CACHE.get("ready") is True
        assert counter.count == 4
    finally:
        stop_event.set()


def test_run_starts_the_periodic_refresher(monkeypatch):
    assert hasattr(web_server, "_start_hive_metrics_refresher"), (
        "the web server has no periodic hive-metrics refresher"
    )

    started = []
    monkeypatch.setattr(
        web_server,
        "_start_hive_metrics_refresher",
        lambda *a, **k: started.append(True) or threading.Event(),
    )
    monkeypatch.setattr(web_server, "acquire_lock", lambda path: True)
    monkeypatch.setattr(web_server, "release_lock", lambda path: None)

    class _FakeServer:
        def __init__(self, *args, **kwargs):
            pass

        def serve_forever(self):
            return

        def server_close(self):
            return

    monkeypatch.setattr(web_server, "ThreadingHTTPServer", _FakeServer)
    web_server.run(port=8083)

    assert started == [True]
