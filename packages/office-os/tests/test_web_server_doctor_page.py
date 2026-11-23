"""Tests for the web doctor page's error-rate label and cost-day bucket.

The page is human-facing, so it has to report the same truth as the CLI:
the current 24h error rate (not the lifetime rate) and the ledger's local
day (the ledger stamps entries with local wall-clock time).
"""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

OFFICE_OS_ROOT = Path("/Users/aryanagarwal/AI-Office/packages/office-os")
sys.path.insert(0, str(OFFICE_OS_ROOT))

web_server = pytest.importorskip("core.web_server")

LOCAL_DAY = "2026-11-23"
UTC_DAY = "2026-11-22"


class _FixedClock(datetime):
    """A datetime whose local and UTC days differ."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls(2026, 11, 23, 2, 35, 0)
        return cls(2026, 11, 22, 21, 5, 0, tzinfo=timezone.utc)


METRICS_PAYLOAD = {
    "jev": {
        "tasks_done": 10,
        "tasks_created": 12,
        "completion_rate": 83.3,
        "error_rate": 10.9,
        "error_rate_total": 2.3,
        "calls_today": 40,
    },
    "provider_pools": {"mlx_local": {"available": True, "tier": "pro"}},
    "free_ceiling": {"headroom_pct": 99.1},
}


def _render_doctor_page(monkeypatch):
    handler = web_server.OfficeHandler.__new__(web_server.OfficeHandler)
    monkeypatch.setattr(handler, "_build_metrics_payload", lambda: METRICS_PAYLOAD)
    monkeypatch.setattr(handler, "send_response", lambda code: None)
    monkeypatch.setattr(handler, "send_header", lambda *args: None)
    monkeypatch.setattr(handler, "end_headers", lambda: None)
    handler.wfile = io.BytesIO()
    handler._serve_doctor_page()
    return handler.wfile.getvalue().decode("utf-8")


def test_doctor_page_reports_the_current_24h_error_rate(monkeypatch):
    html = _render_doctor_page(monkeypatch)

    assert "10.9%" in html
    assert "all-time 2.3%" in html


def test_doctor_page_does_not_label_the_lifetime_rate_as_the_error_rate(monkeypatch):
    html = _render_doctor_page(monkeypatch)

    assert "Error rate: 2.3%" not in html


def test_daily_ledger_cost_counts_the_local_day(tmp_path, monkeypatch):
    """The ledger is stamped with local wall-clock time, so UTC buckets read
    the previous local day's spend as today's."""
    monkeypatch.setattr(web_server, "datetime", _FixedClock)
    ledger = tmp_path / "office_pnl.json"
    ledger.write_text(json.dumps([
        {"created_at": f"{LOCAL_DAY}T00:00:00Z", "cost_units": 9999},
        {"created_at": f"{UTC_DAY}T21:05:00Z", "cost_units": 4000},
    ]))

    assert web_server._daily_ledger_cost(ledger) == 9999
