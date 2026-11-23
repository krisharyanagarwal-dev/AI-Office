"""Tests for the public /dashboard HTML rendering.

The public dashboard is the human-facing landing page for dost. Its template
must survive a single ``str.format()`` pass: placeholders use single braces and
literal CSS/JS braces are doubled. If the template is escaped for two passes
instead, the served page contains literal ``{placeholder}`` text, invalid CSS,
and invalid JavaScript, so every metric renders blank and the page scripts
never run.
"""

from __future__ import annotations

import re
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

OFFICE_OS_ROOT = Path("/Users/aryanagarwal/AI-Office/packages/office-os")
sys.path.insert(0, str(OFFICE_OS_ROOT))

web_server = pytest.importorskip("core.web_server")

_PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}")


def _fake_payload() -> dict:
    return {
        "jev": {
            "tasks_created": 424242,
            "tasks_done": 424200,
            "completion_rate": 99.0,
            "error_rate": 0.25,
            "calls_today": 111222,
            "tasks_per_min": 3.5,
        },
        "provider_pools": {
            "mlx_local": {"available": True, "cooldown_remaining": 0, "tier": "A", "models": ["x/y"]},
            "pool_b": {"available": False, "cooldown_remaining": 12, "tier": "B", "models": []},
        },
        "free_ceiling": {"headroom_pct": 77},
    }


@pytest.fixture()
def public_dashboard_html(monkeypatch):
    monkeypatch.setattr(
        web_server.OfficeHandler,
        "_build_metrics_payload",
        lambda self: _fake_payload(),
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.OfficeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/dashboard"
        with urllib.request.urlopen(url, timeout=30) as resp:
            assert resp.status == 200
            return resp.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_public_dashboard_has_no_unsubstituted_placeholders(public_dashboard_html):
    leftovers = sorted(set(_PLACEHOLDER_RE.findall(public_dashboard_html)))
    assert leftovers == [], f"unsubstituted placeholders served: {leftovers}"


def test_public_dashboard_has_no_doubled_braces(public_dashboard_html):
    assert "{{" not in public_dashboard_html
    assert "}}" not in public_dashboard_html


def test_public_dashboard_renders_metric_values(public_dashboard_html):
    assert "424242" in public_dashboard_html
    assert "111222" in public_dashboard_html
    assert "0.25" in public_dashboard_html
