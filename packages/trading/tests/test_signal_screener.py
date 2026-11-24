"""Tests for the unified signal screener.

The screener runs candidate signals through the quality gates in
alpha.factors.quality_validator (IC mean, IR, turnover, decay, sector
neutrality, crowding, drawdown) and writes a ranked list of passing signals
as JSON and markdown artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha.factors.signal_screener import CandidateSignal, SignalScreener, main


def good_candidate(name="good", **overrides):
    fields = dict(
        name=name,
        ic_mean=0.05,
        ic_std=0.02,
        ic_ir=2.5,
        positive_ic_ratio=0.6,
        max_drawdown=-0.03,
        decay={1: 0.05, 5: 0.04, 10: 0.02},
        turnover=0.2,
        sector_neutral_ic=0.04,
        n_observations=200,
        crowding_score=10.0,
    )
    fields.update(overrides)
    return CandidateSignal(**fields)


def bad_candidate(name="bad", **overrides):
    fields = dict(
        name=name,
        ic_mean=0.005,
        ic_std=0.05,
        ic_ir=0.1,
        positive_ic_ratio=0.45,
        max_drawdown=-0.15,
        decay={1: 0.05, 10: 0.04},
        turnover=0.8,
        sector_neutral_ic=0.005,
        n_observations=50,
        crowding_score=200.0,
    )
    fields.update(overrides)
    return CandidateSignal(**fields)


class TestSignalScreener:
    def test_good_candidate_passes_quality_gates(self):
        screener = SignalScreener()
        passed, failed, reports = screener.screen([good_candidate()])
        assert passed == ["good"]
        assert failed == []
        assert reports["good"].overall_pass is True

    def test_bad_candidate_fails_quality_gates(self):
        screener = SignalScreener()
        passed, failed, reports = screener.screen([bad_candidate()])
        assert passed == []
        assert failed == ["bad"]
        assert reports["bad"].overall_pass is False

    def test_mixed_candidates_screen_independently(self):
        screener = SignalScreener()
        passed, failed, reports = screener.screen(
            [good_candidate("good"), bad_candidate("bad")]
        )
        assert passed == ["good"]
        assert failed == ["bad"]
        assert reports["good"].overall_pass is True
        assert reports["bad"].overall_pass is False

    def test_empty_candidate_list(self):
        screener = SignalScreener()
        passed, failed, reports = screener.screen([])
        assert passed == []
        assert failed == []
        assert reports == {}

    def test_ranking_puts_good_above_bad(self):
        screener = SignalScreener()
        ranking = screener.rank([bad_candidate("bad"), good_candidate("good")])
        assert list(ranking["factor"]) == ["good", "bad"]
        good_score = ranking.loc[ranking["factor"] == "good", "quality_score"].iloc[0]
        bad_score = ranking.loc[ranking["factor"] == "bad", "quality_score"].iloc[0]
        assert good_score > bad_score

    def test_writes_json_and_markdown_artifacts(self, tmp_path):
        screener = SignalScreener()
        result = screener.write_artifacts(
            [good_candidate("good"), bad_candidate("bad")], tmp_path / "out"
        )
        assert result["json"].exists()
        assert result["markdown"].exists()
        payload = json.loads(result["json"].read_text())
        assert payload["passed"] == ["good"]
        assert payload["failed"] == ["bad"]
        assert payload["pass_rate"] == 0.5
        markdown = result["markdown"].read_text()
        assert "## Passing signals" in markdown
        assert "## Failed signals" in markdown
        assert "good" in markdown
        assert "bad" in markdown

    def test_cli_writes_artifacts(self, tmp_path):
        candidates_file = tmp_path / "candidates.json"
        candidates_file.write_text(
            json.dumps(
                [
                    {
                        "name": "good",
                        "ic_mean": 0.05,
                        "ic_std": 0.02,
                        "ic_ir": 2.5,
                        "positive_ic_ratio": 0.6,
                        "max_drawdown": -0.03,
                        "decay": {1: 0.05, 10: 0.02},
                        "turnover": 0.2,
                        "sector_neutral_ic": 0.04,
                        "n_observations": 200,
                        "crowding_score": 10.0,
                    }
                ]
            )
        )
        out_dir = tmp_path / "out"
        code = main(["--candidates", str(candidates_file), "--out-dir", str(out_dir)])
        assert code == 0
        assert (out_dir / "signal_screener_results.json").exists()
        assert (out_dir / "signal_screener_report.md").exists()
        payload = json.loads((out_dir / "signal_screener_results.json").read_text())
        assert payload["passed"] == ["good"]
