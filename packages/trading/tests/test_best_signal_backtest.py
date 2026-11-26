"""Tests for the historical backtest configuration module."""

import pytest
from pathlib import Path
from best_signal.backtest_config import BacktestConfig, _build_backtest_parser, _parse_date, config_from_args


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