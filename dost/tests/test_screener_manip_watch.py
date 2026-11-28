"""Tests for dost ops screener manipulation watch.

Covers manipulation scoring, signal filtering, pipeline health, and the
self-healing triggers (stuck tasks, pool saturation, full cycle) with a
fake healing backend so no network or hive writes happen.
"""

from __future__ import annotations

import asyncio
import csv
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ops.screener_manip_watch import (
    ScreenerManipWatch,
    SCREENER_MANIP_CONFIG,
    ManipSignal,
)

SCREENER_HEADER = [
    "symbol",
    "leverage_flag",
    "momentum_flag",
    "pct_from_52w_high",
    "pe_ttm",
    "debt_to_equity",
    "current_ratio",
]


class FakeMemory:
    """In-memory stand-in for the unified memory layer."""

    def __init__(self) -> None:
        self.prefs: dict = {}
        self.messages: list = []

    def get_preference(self, key: str, default=None):
        return self.prefs.get(key, default)

    def set_preference(self, key: str, value) -> None:
        self.prefs[key] = value

    def add_message(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))


class FakeHealing:
    """Stand-in for FleetSelfHealing: records calls, never touches network/hive."""

    def __init__(self) -> None:
        self.calls: list = []
        self.full_cycle_calls = 0

    def fetch_fleet_metrics(self):
        return {}

    def check_stuck_tasks(self, metrics):
        self.calls.append(("stuck_tasks", metrics))
        return [
            SimpleNamespace(
                id="heal-stuck-1",
                action_type="stuck_task_redispatch",
                target="task-abc",
                reason="stuck task re-dispatched",
                timestamp=now_iso(),
                success=True,
                details={"task_id": "task-abc"},
            )
        ]

    def check_pool_saturation(self, metrics):
        self.calls.append(("pool_saturation", metrics))
        return [
            SimpleNamespace(
                id="heal-pool-1",
                action_type="pool_failover",
                target="pool-x",
                reason="pool saturated",
                timestamp=now_iso(),
                success=True,
                details={"pool": "pool-x"},
            )
        ]

    async def run_once(self):
        self.calls.append(("full_cycle", None))
        self.full_cycle_calls += 1
        return {
            "ok": True,
            "actions": [
                {
                    "type": "circuit_break",
                    "target": "fleet_dispatch",
                    "reason": "error spike",
                    "success": True,
                }
            ],
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_watch(monkeypatch, config=None, healing=None, memory=None):
    mem = memory or FakeMemory()
    monkeypatch.setattr("ops.screener_manip_watch.get_unified_memory", lambda: mem)
    heal = healing or FakeHealing()
    watch = ScreenerManipWatch(config, healing=heal)
    return watch, mem, heal


def _signal_row(symbol: str) -> dict:
    """Row that scores 100 (Extreme leverage + Parabolic momentum + near 52w high)."""
    return {
        "symbol": symbol,
        "leverage_flag": "Extreme",
        "momentum_flag": "Parabolic",
        "pct_from_52w_high": "95",
        "pe_ttm": "18",
        "debt_to_equity": "40",
        "current_ratio": "2.0",
    }


def _clean_row(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "leverage_flag": "Low",
        "momentum_flag": "Normal",
        "pct_from_52w_high": "-20",
        "pe_ttm": "18",
        "debt_to_equity": "40",
        "current_ratio": "2.0",
    }


def _write_csv(path, rows):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCREENER_HEADER)
        writer.writeheader()
        writer.writerows(rows)


# ----------------------- Config -----------------------

def test_partial_config_keeps_default_thresholds(monkeypatch):
    """Orchestrator passes partial config; default thresholds must survive."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.screener_manip_watch.get_unified_memory", lambda: fake)
    watch = ScreenerManipWatch({"enabled": True, "check_interval_sec": 60})
    assert watch.config["thresholds"] == SCREENER_MANIP_CONFIG["thresholds"]
    assert watch.config["enabled"] is True
    assert watch.config["check_interval_sec"] == 60


# ----------------------- Manipulation scoring -----------------------

def test_manipulation_score_caps_at_100(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch)
    assert watch._manipulation_score(_signal_row("STOCKX")) == 100.0


def test_manipulation_score_high_leverage_elevated(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch)
    row = _clean_row("STOCKY")
    row.update(leverage_flag="High", momentum_flag="Elevated", pct_from_52w_high="-60", pe_ttm="200", debt_to_equity="150", current_ratio="0.8")
    assert watch._manipulation_score(row) == 90.0


def test_manipulation_score_clean_row_zero(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch)
    assert watch._manipulation_score(_clean_row("STOCKZ")) == 0.0


def test_to_float_rejects_junk(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch)
    assert watch._to_float(None) is None
    assert watch._to_float("") is None
    assert watch._to_float("nan") is None
    assert watch._to_float("inf") is None
    assert watch._to_float("abc") is None
    assert watch._to_float("12.5") == 12.5


def _ev_boost_row(symbol: str) -> dict:
    """Row scoring 75 (Extreme leverage + Parabolic), below the 80 threshold."""
    return {
        "symbol": symbol,
        "leverage_flag": "Extreme",
        "momentum_flag": "Parabolic",
        "pct_from_52w_high": "-20",
        "pe_ttm": "18",
        "debt_to_equity": "40",
        "current_ratio": "2.0",
    }


# ----------------------- EV/new-age score booster -----------------------

def test_ev_new_age_boost_adds_ten_points(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"ev_new_age_enabled": True}})
    assert watch._manipulation_score(_ev_boost_row("EVBOOST")) == 75.0
    boosted = dict(_ev_boost_row("EVBOOST"), ev_new_age=True)
    assert watch._manipulation_score(boosted) == 85.0


def test_ev_new_age_boost_off_by_default(monkeypatch):
    """Controlled rollout: EV boost is opt-in and defaults to off."""
    watch, _, _ = _make_watch(monkeypatch)
    assert watch.config["thresholds"]["ev_new_age_enabled"] is False
    assert watch._manipulation_score(dict(_ev_boost_row("GATED"), ev_new_age=True)) == 75.0


def test_ev_new_age_boost_caps_at_100(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"ev_new_age_enabled": True}})
    assert watch._manipulation_score(dict(_signal_row("CAP"), ev_new_age=True)) == 100.0


def test_ev_new_age_absent_means_no_boost(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch)
    assert watch._manipulation_score(_ev_boost_row("PLAIN")) == 75.0


def _news_boost_row(symbol: str, signal: str = "negative") -> dict:
    """Row scoring 75 (Extreme leverage + Parabolic), below the 80 threshold."""
    return {
        "symbol": symbol,
        "leverage_flag": "Extreme",
        "momentum_flag": "Parabolic",
        "pct_from_52w_high": "-20",
        "pe_ttm": "18",
        "debt_to_equity": "40",
        "current_ratio": "2.0",
        "news_sentiment": {"signal": signal, "score": -0.8, "sources": 2},
    }


def _social_boost_row(symbol: str, signal: str = "negative") -> dict:
    """Row scoring 75 (Extreme leverage + Parabolic), below the 80 threshold."""
    return {
        "symbol": symbol,
        "leverage_flag": "Extreme",
        "momentum_flag": "Parabolic",
        "pct_from_52w_high": "-20",
        "pe_ttm": "18",
        "debt_to_equity": "40",
        "current_ratio": "2.0",
        "social_sentiment": {"signal": signal, "score": -0.8, "sources": 2},
    }


# ----------------------- News sentiment score booster -----------------------

def test_news_sentiment_boost_adds_five_points(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"news_sentiment_enabled": True}})
    assert watch._manipulation_score(_news_boost_row("NEWSUP")) == 80.0


def test_news_sentiment_boost_off_by_default(monkeypatch):
    """Controlled rollout: news sentiment boost is opt-in and defaults to off."""
    watch, _, _ = _make_watch(monkeypatch)
    assert watch.config["thresholds"]["news_sentiment_enabled"] is False
    assert watch._manipulation_score(dict(_news_boost_row("GATED"))) == 75.0


def test_news_sentiment_boost_only_on_negative(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"news_sentiment_enabled": True}})
    assert watch._manipulation_score(dict(_news_boost_row("NEUTRAL", signal="neutral"))) == 75.0
    assert watch._manipulation_score(dict(_news_boost_row("POS", signal="positive"))) == 75.0


# ----------------------- Social sentiment score booster -----------------------

def test_social_sentiment_boost_adds_five_points(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"social_sentiment_enabled": True}})
    assert watch._manipulation_score(_social_boost_row("SOCUP")) == 80.0


def test_social_sentiment_boost_off_by_default(monkeypatch):
    """Controlled rollout: social sentiment boost is opt-in and defaults to off."""
    watch, _, _ = _make_watch(monkeypatch)
    assert watch.config["thresholds"]["social_sentiment_enabled"] is False
    assert watch._manipulation_score(dict(_social_boost_row("GATED"))) == 75.0


def test_social_sentiment_boost_only_on_negative(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"social_sentiment_enabled": True}})
    assert watch._manipulation_score(dict(_social_boost_row("NEUTRAL", signal="neutral"))) == 75.0
    assert watch._manipulation_score(dict(_social_boost_row("POS", signal="positive"))) == 75.0


def test_signals_include_ev_fields(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"ev_new_age_enabled": True}})
    row = dict(_ev_boost_row("EVSIG"), ev_new_age=True, ev_new_age_score=88.0)
    signals = watch._signals([row], "test.csv")
    assert len(signals) == 1
    assert signals[0].ev_new_age is True
    assert signals[0].ev_new_age_score == 88.0
    assert "ev/new-age" in signals[0].reason


def test_ev_new_age_boost_pushes_row_into_signals(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"ev_new_age_enabled": True}})
    assert watch._signals([_ev_boost_row("NOEV")], "test.csv") == []
    assert len(watch._signals([dict(_ev_boost_row("EVSIG"), ev_new_age=True)], "test.csv")) == 1


def test_run_once_enriches_rows_from_ev_skill(monkeypatch, tmp_path):
    def fake_criteria(symbol: str) -> Optional[dict[str, Any]]:
        if symbol == "EVSTOCK":
            return {
                "symbol": "EVSTOCK",
                "ev_new_age_score": 82.0,
                "ev_new_age": True,
                "sector": "Technology",
            }
        return None

    monkeypatch.setattr("ops.screener_manip_watch.get_ev_criteria", fake_criteria)
    rows = [_ev_boost_row("EVSTOCK")]
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, rows)
    watch, mem, heal = _make_watch(monkeypatch, config={"thresholds": {"ev_new_age_enabled": True}})
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])

    result = asyncio.run(watch.run_once())

    assert result["ok"] is True
    assert len(result["signals"]) == 1
    sig = result["signals"][0]
    assert sig["symbol"] == "EVSTOCK"
    assert sig["score"] == 85.0
    assert sig["ev_new_age"] is True
    assert sig["ev_new_age_score"] == 82.0
    pref = mem.get_preference("screener_manip_watch")
    assert pref["signals"][0]["ev_new_age"] is True
    assert pref["signals"][0]["ev_new_age_score"] == 82.0
    assert pref["ev_new_age_signals"] == 1


def test_run_once_ev_skill_failure_degrades_gracefully(monkeypatch, tmp_path):
    def boom(symbol: str) -> Optional[dict[str, Any]]:
        raise RuntimeError("skill down")

    monkeypatch.setattr("ops.screener_manip_watch.get_ev_criteria", boom)
    rows = [_ev_boost_row("DOWN")]
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, rows)
    watch, _, _ = _make_watch(monkeypatch, config={"thresholds": {"ev_new_age_enabled": True}})
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])

    result = asyncio.run(watch.run_once())

    assert result["ok"] is True
    assert result["signals"] == []  # 75, no boost -> below threshold


def test_run_once_ev_skill_returns_none_degrades_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr("ops.screener_manip_watch.get_ev_criteria", lambda symbol: None)
    rows = [_ev_boost_row("NONE")]
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, rows)
    watch, _, _ = _make_watch(monkeypatch)
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])

    result = asyncio.run(watch.run_once())

    assert result["ok"] is True
    assert result["signals"] == []


def test_signals_filters_by_threshold_and_sorts_desc(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch)
    rows = [_clean_row("AAA"), _signal_row("BBB"), _clean_row("CCC")]
    signals = watch._signals(rows, "test.csv")
    assert [s.symbol for s in signals] == ["BBB"]
    assert signals[0].score == 100.0
    assert isinstance(signals[0], ManipSignal)


# ----------------------- Pipeline health -----------------------

def test_pipeline_healthy_false_no_artifacts(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch)
    assert watch._pipeline_healthy([], []) is False


def test_pipeline_healthy_false_stale_artifact(monkeypatch, tmp_path):
    watch, _, _ = _make_watch(monkeypatch)
    path = tmp_path / "all_stocks_summary_20260101_000000.csv"
    _write_csv(path, [_clean_row(f"S{i}") for i in range(15)])
    old = datetime.now(timezone.utc) - timedelta(minutes=200)
    os.utime(path, (old.timestamp(), old.timestamp()))
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])
    artifacts = watch.fetch_screener_artifacts()
    rows = [row for artifact in artifacts for row in artifact["rows"]]
    assert watch._pipeline_healthy(artifacts, rows) is False


def test_pipeline_healthy_false_too_few_rows(monkeypatch, tmp_path):
    watch, _, _ = _make_watch(monkeypatch)
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, [_clean_row(f"S{i}") for i in range(5)])
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])
    artifacts = watch.fetch_screener_artifacts()
    rows = [row for artifact in artifacts for row in artifact["rows"]]
    assert watch._pipeline_healthy(artifacts, rows) is False


def test_pipeline_healthy_true(monkeypatch, tmp_path):
    watch, _, _ = _make_watch(monkeypatch)
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, [_clean_row(f"S{i}") for i in range(15)])
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])
    artifacts = watch.fetch_screener_artifacts()
    rows = [row for artifact in artifacts for row in artifact["rows"]]
    assert watch._pipeline_healthy(artifacts, rows) is True


def test_fetch_screener_artifacts_loads_csv(monkeypatch, tmp_path):
    watch, _, _ = _make_watch(monkeypatch)
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, [_signal_row("RELIANCE")])
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])
    artifacts = watch.fetch_screener_artifacts()
    assert len(artifacts) == 1
    assert artifacts[0]["source"] == path.name
    assert artifacts[0]["rows"][0]["symbol"] == "RELIANCE"
    assert isinstance(artifacts[0]["mtime"], datetime)


# ----------------------- Run cycle -----------------------

def test_run_once_pipeline_stuck_triggers_stuck_task_check(monkeypatch, tmp_path):
    watch, mem, heal = _make_watch(monkeypatch)
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [])

    result = asyncio.run(watch.run_once())

    assert result["ok"] is True
    assert result["pipeline_ok"] is False
    assert result["rows_screened"] == 0
    assert result["signals"] == []
    assert heal.calls == [("stuck_tasks", {})]
    assert heal.full_cycle_calls == 0
    assert any(a["type"] == "stuck_task_redispatch" for a in result["actions"])
    pref = mem.get_preference("screener_manip_watch")
    assert pref["pipeline_ok"] is False
    assert pref["rows_screened"] == 0


def test_run_once_high_manipulation_rate_triggers_pool_saturation_not_full_cycle(monkeypatch, tmp_path):
    """6 of 20 rows flagged -> rate exactly 30% -> high, not critical (>=60%)."""
    rows = [_signal_row(f"SIG{i}") for i in range(6)] + [_clean_row(f"CLEAN{i}") for i in range(14)]
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, rows)
    watch, mem, heal = _make_watch(monkeypatch)
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])

    result = asyncio.run(watch.run_once())

    assert result["ok"] is True
    assert result["pipeline_ok"] is True
    assert ("pool_saturation", {}) in heal.calls
    assert heal.full_cycle_calls == 0
    assert any(a["type"] == "pool_failover" for a in result["actions"])
    assert not any(a["type"] == "circuit_break" for a in result["actions"])
    pref = mem.get_preference("screener_manip_watch")
    assert pref["manipulation_signals"] == 6
    assert pref["manipulation_rate"] == 0.3


def test_run_once_critical_manipulation_rate_triggers_full_cycle(monkeypatch, tmp_path):
    """15 of 20 rows flagged -> rate 75% -> critical full self-healing cycle."""
    rows = [_signal_row(f"SIG{i}") for i in range(15)] + [_clean_row(f"CLEAN{i}") for i in range(5)]
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, rows)
    watch, mem, heal = _make_watch(monkeypatch)
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])

    result = asyncio.run(watch.run_once())

    assert result["ok"] is True
    assert result["pipeline_ok"] is True
    assert heal.full_cycle_calls == 1
    assert ("pool_saturation", {}) not in heal.calls
    assert any(a["type"] == "circuit_break" for a in result["actions"])
    assert result["healing"]["result"]["ok"] is True


def test_cooldown_blocks_repeat_per_symbol_actions(monkeypatch, tmp_path):
    """Same symbol flagged in back-to-back cycles: only the first acts."""
    rows = [_signal_row("SYM")] + [_clean_row(f"CLEAN{i}") for i in range(10)]
    path = tmp_path / "all_stocks_summary_today.csv"
    _write_csv(path, rows)
    watch, _, heal = _make_watch(monkeypatch)
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [path])

    first = asyncio.run(watch.run_once())
    assert any(a["type"] == "screener_manipulation_detected" and a["target"] == "SYM" for a in first["actions"])

    second = asyncio.run(watch.run_once())
    assert second["actions"] == []
    assert heal.full_cycle_calls == 0  # manipulation rate below high threshold anyway


def test_run_once_disabled_returns_early(monkeypatch):
    watch, _, heal = _make_watch(monkeypatch, config={"enabled": False})
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [])

    result = asyncio.run(watch.run_once())

    assert result["ok"] is True
    assert result["actions"] == []
    assert result["signals"] == []
    assert result["healing"] is None
    assert heal.calls == []


def test_record_action_outcome_tracks_failures(monkeypatch):
    watch, _, _ = _make_watch(monkeypatch)
    watch._record_action_outcome("key", False)
    watch._record_action_outcome("key", False)
    assert watch._consecutive_failures["key"] == 2
    watch._record_action_outcome("key", True)
    assert watch._consecutive_failures == {}


# ----------------------- Real artifact smoke test -----------------------

def test_run_once_reads_real_screener_artifact(monkeypatch):
    """End-to-end against the actual repo-root artifact: loads real rows,
    sees it as stale (pipeline stuck), triggers stuck-task check only."""
    artifact = "/Users/aryanagarwal/AI-Office/all_stocks_summary_20261120_173226.csv"
    watch, mem, heal = _make_watch(monkeypatch)
    # Point at the real artifact without touching REPO_ROOT globbing.
    monkeypatch.setattr(watch, "_artifact_paths", lambda: [__import__("pathlib").Path(artifact)])

    result = asyncio.run(watch.run_once())

    assert result["ok"] is True
    assert result["rows_screened"] == 2407
    assert result["pipeline_ok"] is False  # artifact is days old -> stuck
    for signal in result["signals"]:
        assert {"symbol", "score", "reason", "source"} <= set(signal)
    assert ("stuck_tasks", {}) in heal.calls
    assert heal.full_cycle_calls == 0
