"""Tests for the dashboard's per-agent cost panel day bucketing.

The dispatcher stamps workspace P&L entries with local wall-clock time, so the
panel's day keys must be local too. A UTC key reads the previous local day's
spend as today's for part of every local day.
"""

from __future__ import annotations

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


def _entry(created_at: str, cost_units: int, agent_id: str = "a1", **extra) -> dict:
    entry = {
        "created_at": created_at,
        "cost_units": cost_units,
        "agent_id": agent_id,
        "metric_type": "task",
        "status": "done",
    }
    entry.update(extra)
    return entry


def test_workspace_costs_bucket_the_local_day_as_today(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server, "datetime", _FixedClock)
    pnl_dir = tmp_path / "pnl"
    pnl_dir.mkdir()
    (pnl_dir / "a.json").write_text(json.dumps(_entry(f"{LOCAL_DAY}T00:00:00Z", 9999)))
    (pnl_dir / "b.json").write_text(json.dumps(_entry(f"{UTC_DAY}T21:05:00Z", 4000, agent_id="a2")))

    stats = web_server._workspace_pnl_costs(pnl_dir)

    assert stats["cost_units_today"] == 9999
    assert stats["cost_per_agent"] == {"a1": 9999}
    assert stats["cost_yesterday"] == 4000


def test_workspace_costs_count_debates_and_voice_dispatches(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server, "datetime", _FixedClock)
    pnl_dir = tmp_path / "pnl"
    pnl_dir.mkdir()
    (pnl_dir / "a.json").write_text(
        json.dumps(_entry(f"{LOCAL_DAY}T01:00:00Z", 10, source="debate", metadata={"voice_dispatch": True}))
    )

    stats = web_server._workspace_pnl_costs(pnl_dir)

    assert stats["debate_calls_today"] == 1
    assert stats["voice_dispatches_today"] == 1
    assert stats["tasks_completed_today"] == 1
