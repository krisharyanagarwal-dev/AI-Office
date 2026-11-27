"""Tests for the screener_ev_integration skill interface.

Covers get_ev_criteria, get_all_ev_criteria, is_ev_new_age, and
latest_artifact_path against fake CSV artifacts; the 70-point
is_ev_new_age threshold; graceful degradation when no artifact
exists; and mtime-based cache reload. No network, no credentials.
"""

from __future__ import annotations

import csv
from datetime import timezone
from pathlib import Path

import pytest

from skills.screener_ev_integration import (
    EVIntegrationConfig,
    EV_NEW_AGE_THRESHOLD,
    ScreenerEVIntegration,
    get_all_ev_criteria,
    get_ev_criteria,
    is_ev_new_age,
    latest_artifact_path,
)

ROW_ABOVE_THRESHOLD = {
    "symbol": "EVSTOCK",
    "sector": "Technology",
    "market_cap": "50000000000",
    "revenue_growth": "0.30",
    "ev_ebitda": "25.0",
    "pe_ttm": "45.0",
    "debt_to_equity": "40.0",
    "current_ratio": "2.0",
    "momentum_flag": "Parabolic",
    "leverage_flag": "Low",
    "pct_from_52w_high": "-5.0",
    "ev_new_age_score": "82.0",
}

ROW_AT_THRESHOLD = dict(ROW_ABOVE_THRESHOLD, symbol="BORDER", ev_new_age_score="70.0")
ROW_BELOW_THRESHOLD = dict(ROW_ABOVE_THRESHOLD, symbol="SLOWSTOCK", ev_new_age_score="69.0")
ROW_NO_SCORE = dict(ROW_ABOVE_THRESHOLD, symbol="NOSCORE", ev_new_age_score="")

FIELDNAMES = list(ROW_ABOVE_THRESHOLD)
REPO_ROOT = Path(__file__).resolve().parents[2]  # AI-Office/


def _write_artifact(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _make_skill(tmp_path: Path) -> ScreenerEVIntegration:
    return ScreenerEVIntegration(EVIntegrationConfig(artifact_root=tmp_path))


# ----------------------- threshold constant -----------------------


def test_ev_new_age_threshold_is_seventy():
    assert EV_NEW_AGE_THRESHOLD == 70


# ----------------------- skill interface vs fake artifact -----------------------


def test_get_ev_criteria_parses_fake_artifact(tmp_path: Path):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_ABOVE_THRESHOLD, ROW_BELOW_THRESHOLD])
    skill = _make_skill(tmp_path)

    criteria = skill.get_ev_criteria("evstock")

    assert criteria is not None
    assert criteria["symbol"] == "EVSTOCK"
    assert criteria["sector"] == "Technology"
    assert criteria["market_cap"] == 50_000_000_000.0
    assert criteria["revenue_growth"] == 0.30
    assert criteria["ev_ebitda"] == 25.0
    assert criteria["pe_ttm"] == 45.0
    assert criteria["debt_to_equity"] == 40.0
    assert criteria["current_ratio"] == 2.0
    assert criteria["momentum_flag"] == "Parabolic"
    assert criteria["leverage_flag"] == "Low"
    assert criteria["pct_from_52w_high"] == -5.0
    assert criteria["ev_new_age_score"] == 82.0
    assert criteria["ev_new_age"] is True  # 82 >= 70


def test_get_all_ev_criteria_returns_all_symbols(tmp_path: Path):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_ABOVE_THRESHOLD, ROW_AT_THRESHOLD])
    skill = _make_skill(tmp_path)

    criteria = skill.get_all_ev_criteria()

    assert len(criteria) == 2
    symbols = {c["symbol"] for c in criteria}
    assert symbols == {"EVSTOCK", "BORDER"}


def test_get_ev_criteria_unknown_symbol_returns_none(tmp_path: Path):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_ABOVE_THRESHOLD])
    skill = _make_skill(tmp_path)

    assert skill.get_ev_criteria("NOPE") is None


# ----------------------- is_ev_new_age threshold (70) -----------------------


def test_is_ev_new_age_above_threshold_true(tmp_path: Path):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_ABOVE_THRESHOLD])
    skill = _make_skill(tmp_path)

    assert skill.is_ev_new_age("evstock") is True


def test_is_ev_new_age_at_threshold_true(tmp_path: Path):
    """70 exactly meets the threshold (>=)."""
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_AT_THRESHOLD])
    skill = _make_skill(tmp_path)

    assert skill.is_ev_new_age("border") is True


def test_is_ev_new_age_below_threshold_false(tmp_path: Path):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_BELOW_THRESHOLD])
    skill = _make_skill(tmp_path)

    assert skill.is_ev_new_age("slowstock") is False


def test_is_ev_new_age_missing_score_false(tmp_path: Path):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_NO_SCORE])
    skill = _make_skill(tmp_path)

    assert skill.is_ev_new_age("noscore") is False


def test_is_ev_new_age_unknown_symbol_false(tmp_path: Path):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_ABOVE_THRESHOLD])
    skill = _make_skill(tmp_path)

    assert skill.is_ev_new_age("MISSING") is False


# ----------------------- graceful degradation: no artifact -----------------------


def test_no_artifact_returns_none_empty_false_no_crash(tmp_path: Path):
    """Empty artifact root: every accessor degrades to None/empty/False."""
    skill = _make_skill(tmp_path)

    assert skill.latest_artifact_path() is None
    assert skill.get_ev_criteria("ANY") is None
    assert skill.get_all_ev_criteria() == []
    assert skill.is_ev_new_age("ANY") is False


# ----------------------- mtime-based cache reload -----------------------


def test_reloads_when_artifact_mtime_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_BELOW_THRESHOLD])
    skill = _make_skill(tmp_path)

    assert skill.is_ev_new_age("slowstock") is False

    _write_artifact(path, [ROW_ABOVE_THRESHOLD])
    # mtime resolution is sub-second on this filesystem; force a new mtime.
    import time

    time.sleep(0.01)
    path.touch()

    assert skill.is_ev_new_age("evstock") is True
    assert skill.get_ev_criteria("evstock")["ev_new_age_score"] == 82.0


def test_reload_when_artifact_removed(tmp_path: Path):
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [ROW_ABOVE_THRESHOLD])
    skill = _make_skill(tmp_path)

    assert skill.is_ev_new_age("evstock") is True

    path.unlink()

    assert skill.latest_artifact_path() is None
    assert skill.get_ev_criteria("evstock") is None
    assert skill.get_all_ev_criteria() == []
    assert skill.is_ev_new_age("evstock") is False


# ----------------------- module-level convenience functions -----------------------


def test_module_level_functions_degrade_without_artifact(monkeypatch: pytest.MonkeyPatch):
    """Default instance reads REPO_ROOT; no artifact there means empty/None."""
    artifact = REPO_ROOT / "screener_ev_module_level_probe.csv"
    try:
        if artifact.exists():
            artifact.unlink()
        assert latest_artifact_path() is None
        assert get_ev_criteria("ANY") is None
        assert get_all_ev_criteria() == []
        assert is_ev_new_age("ANY") is False
    finally:
        artifact.unlink(missing_ok=True)


def test_module_level_functions_read_fake_artifact_in_repo_root(monkeypatch: pytest.MonkeyPatch):
    """Write a probe artifact into REPO_ROOT, read via module-level fns, remove it."""
    artifact = REPO_ROOT / "screener_ev_module_level_probe.csv"
    try:
        _write_artifact(artifact, [ROW_ABOVE_THRESHOLD])
        criteria = get_ev_criteria("evstock")
        assert criteria is not None
        assert criteria["ev_new_age"] is True
        assert criteria["ev_new_age_score"] == 82.0
        assert is_ev_new_age("evstock") is True
        assert latest_artifact_path() is not None
        assert latest_artifact_path().name == artifact.name
        assert len(get_all_ev_criteria()) == 1
    finally:
        artifact.unlink(missing_ok=True)


def test_csv_numeric_fields_coerce_to_float(tmp_path: Path):
    """_parse_row coerces numeric strings; bad values become None."""
    path = tmp_path / "screener_ev_20261128_120000.csv"
    _write_artifact(path, [dict(ROW_ABOVE_THRESHOLD, market_cap="not-a-number")])
    skill = _make_skill(tmp_path)

    criteria = skill.get_ev_criteria("evstock")
    assert criteria is not None
    assert criteria["market_cap"] is None
    assert criteria["ev_new_age_score"] == 82.0  # other fields unaffected
