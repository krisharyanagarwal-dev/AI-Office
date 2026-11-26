"""Tests for the historical backtest configuration module."""

import json
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

from best_signal.backtest_config import BacktestConfig, _build_backtest_parser, _parse_date, config_from_args
from best_signal.backtest_runner import (
    run_backtest,
    _load_all_prints,
    _build_timestamp_grid,
    _prints_up_to,
    _write_outputs,
    _build_backtest_report,
    main,
)
from best_signal.backtest_state import BacktestState
from best_signal.funding import FundingPrint
from best_signal.position import RiskLimits
from best_signal.execution import ExecutionRealismConfig


class TestBacktestConfig:
    def test_defaults_match_spec(self):
        config = BacktestConfig()
        assert config.symbols == ("BTCUSDT", "ETHUSDT")
        assert config.equity == 10_000.0
        assert config.start_ts_ms is None
        assert config.end_ts_ms is None
        assert config.telemetry_enabled is True
        assert config.fill_journal_enabled is True
        # execution_realism defaults
        assert config.execution_realism.slippage_bps == 0.0
        assert config.execution_realism.latency_ms == 0.0
        assert config.execution_realism.partial_fill_enabled is False
        assert config.execution_realism.partial_fill_fraction == 0.5

    def test_cli_parser_has_required_flags(self):
        parser = _build_backtest_parser()
        # Check all required flags exist
        args = parser.parse_args([
            "--symbols", "BTCUSDT", "ETHUSDT",
            "--data-dir", "/tmp/data",
            "--out-dir", "/tmp/out",
            "--equity", "100000",
            "--slippage-bps", "2.5",
            "--latency-ms", "50",
            "--partial-fill",
            "--start-date", "2024-01-01",
            "--end-date", "2024-12-31",
        ])
        assert args.symbols == ["BTCUSDT", "ETHUSDT"]
        assert args.data_dir == "/tmp/data"
        assert args.out_dir == "/tmp/out"
        assert args.equity == 100000.0
        assert args.slippage_bps == 2.5
        assert args.latency_ms == 50.0
        assert args.partial_fill is True
        assert args.start_date == "2024-01-01"
        assert args.end_date == "2024-12-31"

    def test_parse_date_valid(self):
        assert _parse_date("2024-01-01") == 1704067200000
        assert _parse_date("2024-12-31") == 1735603200000
        assert _parse_date("2025-06-15") == 1749945600000

    def test_config_from_args(self):
        parser = _build_backtest_parser()
        args = parser.parse_args([
            "--symbols", "BTCUSDT", "ETHUSDT",
            "--data-dir", "/tmp/data",
            "--out-dir", "/tmp/out",
            "--equity", "50000",
            "--max-symbol-notional", "20000",
            "--max-gross-notional", "40000",
            "--max-position-weight", "0.5",
            "--max-symbols", "5",
            "--max-daily-loss-pct", "0.05",
            "--slippage-bps", "1.0",
            "--latency-ms", "10",
            "--partial-fill",
            "--partial-fill-fraction", "0.3",
            "--start-date", "2024-01-01",
            "--end-date", "2024-12-31",
            "--no-telemetry",
            "--no-fill-journal",
        ])
        config = config_from_args(args)

        assert config.symbols == ("BTCUSDT", "ETHUSDT")
        assert config.data_dir == Path("/tmp/data")
        assert config.out_dir == Path("/tmp/out")
        assert config.equity == 50000.0
        assert config.limits.max_symbol_notional == 20000.0
        assert config.limits.max_gross_notional == 40000.0
        assert config.limits.max_position_weight == 0.5
        assert config.limits.max_symbols == 5
        assert config.limits.max_daily_loss_pct == 0.05
        assert config.execution_realism.slippage_bps == 1.0
        assert config.execution_realism.latency_ms == 10.0
        assert config.execution_realism.partial_fill_enabled is True
        assert config.execution_realism.partial_fill_fraction == 0.3
        assert config.start_ts_ms == 1704067200000
        assert config.end_ts_ms == 1735603200000
        assert config.telemetry_enabled is False
        assert config.fill_journal_enabled is False

    def test_config_from_args_defaults(self):
        parser = _build_backtest_parser()
        args = parser.parse_args([])
        config = config_from_args(args)

        assert config.symbols == ("BTCUSDT", "ETHUSDT")
        assert config.data_dir is None
        assert config.equity == 10_000.0
        assert config.limits.max_symbol_notional == 10_000.0
        assert config.limits.max_gross_notional == 20_000.0
        assert config.limits.max_position_weight == 1.0
        assert config.limits.max_symbols == 3
        assert config.limits.max_daily_loss_pct == 0.03
        assert config.execution_realism.slippage_bps == 0.0
        assert config.execution_realism.latency_ms == 0.0
        assert config.execution_realism.partial_fill_enabled is False
        assert config.execution_realism.partial_fill_fraction == 0.5
        assert config.start_ts_ms is None
        assert config.end_ts_ms is None
        assert config.telemetry_enabled is True
        assert config.fill_journal_enabled is True

    def test_config_from_args_without_optional_dates(self):
        parser = _build_backtest_parser()
        args = parser.parse_args([
            "--symbols", "BTCUSDT",
            "--equity", "25000",
        ])
        config = config_from_args(args)

        assert config.symbols == ("BTCUSDT",)
        assert config.equity == 25000.0
        assert config.start_ts_ms is None
        assert config.end_ts_ms is None


class TestBacktestState:
    def test_initial_state_empty(self):
        from best_signal.backtest_state import BacktestState

        state = BacktestState.initial(equity=10_000.0)
        assert state.equity == 10_000.0
        assert state.working == {}
        assert state.day_state == {}
        assert state.equity_curve == []

    def test_snapshot_venue_captures_equity(self):
        from best_signal.backtest_state import BacktestState

        state = BacktestState.initial(equity=10_000.0)
        # Mock broker with positions
        class MockBroker:
            balances = {"USDT": 11_000.0}
            realized_pnl = {"BTCUSDT": 100.0}
            margin_used = {"BTCUSDT_PERP": 1_000.0}
            fees_total = 10.0

        broker = MockBroker()
        snapshot = state.snapshot_venue(broker, ts_ms=1_000_000_000_000)

        assert snapshot["ts_ms"] == 1_000_000_000_000
        assert "equity" in snapshot
        assert snapshot["equity"] == 10_000.0 + 100.0  # equity + realized_pnl
        assert "cash" in snapshot
        assert "margin" in snapshot
        assert "fees" in snapshot


EIGHT_HOURS_MS = 8 * 3_600_000
FIFTEEN_MIN_MS = 15 * 60 * 1000
START_MS = 1_500_000_000_000


def write_funding(data_dir: Path, symbol: str, rates: list[float], start_ms: int = START_MS) -> None:
    """Write funding prints parquet file."""
    data_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({
        "fundingTime": [start_ms + index * EIGHT_HOURS_MS for index in range(len(rates))],
        "fundingRate": rates,
    })
    frame.to_parquet(data_dir / f"{symbol}_funding.parquet")


def write_prices(data_dir: Path, symbol: str, n_bars: int, start_ms: int = START_MS, vol: float = 0.05, drift: float = 0.0, seed: int = 1) -> None:
    """Write 15m close bars."""
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, vol, n_bars)
    closes = 100.0 * np.exp(np.cumsum(returns))
    frame = pd.DataFrame({
        "open_time": [start_ms + index * FIFTEEN_MIN_MS for index in range(n_bars)],
        "close": closes,
    })
    frame.to_parquet(data_dir / f"{symbol}_15m.parquet")


def make_backtest_config(tmp_path: Path, **overrides) -> BacktestConfig:
    """Create a BacktestConfig with sensible defaults for testing."""
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "out"
    settings = {
        "symbols": ("BTCUSDT",),
        "data_dir": data_dir,
        "out_dir": out_dir,
        "equity": 10_000.0,
        "limits": RiskLimits(),
        "execution_realism": ExecutionRealismConfig(),
        "telemetry_enabled": True,
        "fill_journal_enabled": True,
        "start_ts_ms": None,
        "end_ts_ms": None,
    }
    settings.update(overrides)
    return BacktestConfig(**settings)


class TestBacktestRunnerHelpers:
    def test_load_all_prints_loads_and_filters(self, tmp_path):
        data_dir = tmp_path / "data"
        write_funding(data_dir, "BTCUSDT", [0.0001] * 10)
        config = make_backtest_config(tmp_path, start_ts_ms=START_MS + 3 * EIGHT_HOURS_MS, end_ts_ms=START_MS + 7 * EIGHT_HOURS_MS)
        prints = _load_all_prints(config)["BTCUSDT"]
        assert len(prints) == 5  # indices 3,4,5,6,7 (inclusive start, inclusive end)

    def test_build_timestamp_grid_unifies_symbols(self, tmp_path):
        data_dir = tmp_path / "data"
        write_funding(data_dir, "BTCUSDT", [0.0001] * 5)
        write_funding(data_dir, "ETHUSDT", [0.0001] * 3)
        config = make_backtest_config(tmp_path, symbols=("BTCUSDT", "ETHUSDT"))
        timestamps = _build_timestamp_grid(_load_all_prints(config))
        assert len(timestamps) == 5  # BTCUSDT has 5, ETHUSDT has 3, union is 5
        assert timestamps == sorted(timestamps)

    def test_prints_up_to_filters_correctly(self, tmp_path):
        data_dir = tmp_path / "data"
        write_funding(data_dir, "BTCUSDT", [0.0001] * 10)
        config = make_backtest_config(tmp_path)
        all_prints = _load_all_prints(config)["BTCUSDT"]
        filtered = _prints_up_to(all_prints, START_MS + 4 * EIGHT_HOURS_MS)
        assert len(filtered) == 5  # indices 0-4


class TestBacktestRunner:
    def test_backtest_single_symbol_known_result(self, tmp_path):
        """Deterministic equity curve on synthetic data with simple always-long rule."""
        config = make_backtest_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 20)
        write_prices(config.data_dir, "BTCUSDT", n_bars=200, drift=0.0, vol=0.001, seed=42)

        result = run_backtest(config)

        # Verify the result structure
        assert "state" in result
        assert "broker" in result
        assert "config" in result
        assert "equity_curve" in result
        assert len(result["equity_curve"]) == 20  # one per funding print

        # Check equity curve has expected fields
        for pt in result["equity_curve"]:
            assert "ts_ms" in pt
            assert "equity" in pt
            assert "pnl" in pt
            assert "cash" in pt
            assert "margin" in pt
            assert "fees" in pt
            assert "realized_pnl" in pt

        # Final equity should be close to initial (small funding income, small fees)
        final_equity = result["equity_curve"][-1]["equity"]
        assert abs(final_equity - 10_000.0) < 100.0  # within $100

    def test_backtest_writes_equity_curve_file(self, tmp_path):
        config = make_backtest_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)

        run_backtest(config)

        equity_path = config.out_dir / "equity_curve.jsonl"
        assert equity_path.exists()
        lines = equity_path.read_text().strip().splitlines()
        assert len(lines) == 10
        for line in lines:
            pt = json.loads(line)
            assert "ts_ms" in pt
            assert "equity" in pt

    def test_backtest_writes_backtest_state_file(self, tmp_path):
        config = make_backtest_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)

        run_backtest(config)

        state_path = config.out_dir / "backtest_state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert "equity" in state
        assert "working" in state
        assert "day_state" in state
        assert "equity_curve" in state

    def test_backtest_writes_report_file(self, tmp_path):
        config = make_backtest_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)

        run_backtest(config)

        report_path = config.out_dir / "backtest_report.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert content.startswith("# Backtest Report")
        assert "Initial Equity:" in content
        assert "Final Equity:" in content
        assert "Sharpe" in content
        assert "Max Drawdown" in content

    def test_backtest_multiple_symbols(self, tmp_path):
        config = make_backtest_config(tmp_path, symbols=("BTCUSDT", "ETHUSDT"))
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_funding(config.data_dir, "ETHUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)
        write_prices(config.data_dir, "ETHUSDT", n_bars=100, seed=2)

        result = run_backtest(config)

        assert len(result["equity_curve"]) == 10
        # Both symbols should have been processed
        assert "BTCUSDT" in result["state"].working or "ETHUSDT" in result["state"].working

    def test_backtest_with_slippage_and_latency(self, tmp_path):
        config = make_backtest_config(
            tmp_path,
            execution_realism=ExecutionRealismConfig(slippage_bps=5.0, latency_ms=10.0),
        )
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)

        result = run_backtest(config)

        # Telemetry should capture slippage/latency
        telemetry_path = config.out_dir / "telemetry.jsonl"
        assert telemetry_path.exists()
        lines = telemetry_path.read_text().strip().splitlines()
        assert len(lines) > 0
        for line in lines:
            metrics = json.loads(line)
            assert metrics["slippage_bps"] == 5.0
            assert metrics["latency_ms"] == 10.0

    def test_backtest_with_partial_fills(self, tmp_path):
        config = make_backtest_config(
            tmp_path,
            execution_realism=ExecutionRealismConfig(partial_fill_enabled=True, partial_fill_fraction=0.5),
        )
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)

        result = run_backtest(config)

        # Should complete without error
        assert len(result["equity_curve"]) == 10

    def test_backtest_respects_start_end_dates(self, tmp_path):
        config = make_backtest_config(
            tmp_path,
            start_ts_ms=START_MS + 3 * EIGHT_HOURS_MS,
            end_ts_ms=START_MS + 7 * EIGHT_HOURS_MS,
        )
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 20)
        write_prices(config.data_dir, "BTCUSDT", n_bars=200, seed=1)

        result = run_backtest(config)

        # Should only process prints 3-7 inclusive = 5 prints
        assert len(result["equity_curve"]) == 5

    def test_backtest_fill_journal_created(self, tmp_path):
        config = make_backtest_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)

        run_backtest(config)

        journal_path = config.out_dir / "fills.jsonl"
        assert journal_path.exists()
        lines = journal_path.read_text().strip().splitlines()
        assert len(lines) >= 2  # At least one OPEN = 2 legs

    def test_backtest_disabled_telemetry_and_journal(self, tmp_path):
        config = make_backtest_config(tmp_path, telemetry_enabled=False, fill_journal_enabled=False)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)

        result = run_backtest(config)

        # Files should exist but be empty or not exist
        telemetry_path = config.out_dir / "telemetry.jsonl"
        journal_path = config.out_dir / "fills.jsonl"
        # With enabled=False, files may not be created or be empty
        assert len(result["equity_curve"]) == 10

    def test_build_backtest_report_empty(self, tmp_path):
        state = BacktestState.initial(10_000.0)
        config = make_backtest_config(tmp_path)
        report = _build_backtest_report(state, config)
        assert report == "# Backtest Report\n\nNo data."

    def test_build_backtest_report_with_data(self, tmp_path):
        state = BacktestState.initial(10_000.0)
        state.equity_curve = [
            {"ts_ms": 1_000_000_000_000, "equity": 10_000.0, "pnl": 0.0, "funding": 10.0, "fees": 5.0},
            {"ts_ms": 1_000_028_800_000, "equity": 10_010.0, "pnl": 10.0, "funding": 15.0, "fees": 5.0},
        ]
        config = make_backtest_config(tmp_path)
        report = _build_backtest_report(state, config)
        assert "10,000.00" in report
        assert "10,010.00" in report
        assert "Total Return:" in report
        assert "Sharpe" in report
        assert "Max Drawdown" in report

    def test_write_outputs_creates_all_files(self, tmp_path):
        config = make_backtest_config(tmp_path)
        state = BacktestState.initial(10_000.0)
        state.equity_curve = [
            {"ts_ms": 1_000_000_000_000, "equity": 10_000.0, "pnl": 0.0, "cash": 10_000.0, "margin": 0.0, "fees": 0.0, "realized_pnl": 0.0},
        ]

        class MockBroker:
            balances = {"USDT": 10_000.0}
            realized_pnl = {}
            margin_used = {}
            fees_total = 0.0

        broker = MockBroker()
        _write_outputs(config, state, broker)

        assert (config.out_dir / "equity_curve.jsonl").exists()
        assert (config.out_dir / "backtest_state.json").exists()
        assert (config.out_dir / "backtest_report.md").exists()

    def test_main_cli_entry(self, tmp_path, capsys):
        config = make_backtest_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 10)
        write_prices(config.data_dir, "BTCUSDT", n_bars=100, seed=1)

        code = main([
            "--symbols", "BTCUSDT",
            "--data-dir", str(config.data_dir),
            "--out-dir", str(config.out_dir),
            "--equity", "10000",
        ])
        assert code == 0
        out = capsys.readouterr().out
        assert "Backtest complete" in out
        assert "Final equity" in out

    def test_main_cli_fails_on_missing_data(self, tmp_path, capsys):
        code = main([
            "--symbols", "BTCUSDT",
            "--data-dir", str(tmp_path / "empty"),
            "--out-dir", str(tmp_path / "out"),
        ])
        assert code == 1
        err = capsys.readouterr().err
        assert "Backtest failed" in err