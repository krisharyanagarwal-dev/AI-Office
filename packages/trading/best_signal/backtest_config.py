"""Historical backtest configuration for the best-signal bot."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from best_signal.execution import ExecutionRealismConfig
from best_signal.position import RiskLimits
from best_signal.runner import DEFAULT_OUT_DIR, DEFAULT_DATA_DIR


@dataclass(frozen=True)
class BacktestConfig:
    """Configuration for a historical backtest run."""

    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    data_dir: Path | None = None
    out_dir: Path = DEFAULT_OUT_DIR / "backtest"
    equity: float = 10_000.0
    limits: RiskLimits = RiskLimits()
    execution_realism: ExecutionRealismConfig = ExecutionRealismConfig()
    start_ts_ms: int | None = None
    end_ts_ms: int | None = None
    telemetry_enabled: bool = True
    fill_journal_enabled: bool = True


def _build_backtest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="best_signal.backtest_runner",
        description="Run historical backtest of the best-signal bot in paper mode.",
    )
    parser.add_argument("--symbols", nargs="+", default=list(("BTCUSDT", "ETHUSDT")))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR / "backtest"))
    parser.add_argument("--equity", type=float, default=10_000.0)
    parser.add_argument(
        "--max-symbol-notional", type=float, default=RiskLimits.max_symbol_notional
    )
    parser.add_argument(
        "--max-gross-notional", type=float, default=RiskLimits.max_gross_notional
    )
    parser.add_argument(
        "--max-position-weight", type=float, default=RiskLimits.max_position_weight
    )
    parser.add_argument("--max-symbols", type=int, default=RiskLimits.max_symbols)
    parser.add_argument(
        "--max-daily-loss-pct", type=float, default=RiskLimits.max_daily_loss_pct
    )
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--latency-ms", type=float, default=0.0)
    parser.add_argument(
        "--partial-fill",
        dest="partial_fill",
        action="store_true",
        help="enable deterministic partial fills (paper mode only)",
    )
    parser.add_argument(
        "--partial-fill-fraction",
        type=float,
        default=ExecutionRealismConfig.partial_fill_fraction,
    )
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD (UTC)")
    parser.add_argument(
        "--no-telemetry",
        dest="telemetry",
        action="store_false",
        help="disable execution telemetry",
    )
    parser.add_argument(
        "--no-fill-journal",
        dest="fill_journal",
        action="store_false",
        help="disable fill journal",
    )
    return parser


def _parse_date(date_str: str) -> int:
    """Parse YYYY-MM-DD to UTC timestamp in milliseconds."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def config_from_args(args: argparse.Namespace) -> BacktestConfig:
    """Convert parsed CLI args to BacktestConfig."""
    limits = RiskLimits(
        max_symbol_notional=args.max_symbol_notional,
        max_gross_notional=args.max_gross_notional,
        max_position_weight=args.max_position_weight,
        max_symbols=args.max_symbols,
        max_daily_loss_pct=args.max_daily_loss_pct,
    )
    realism = ExecutionRealismConfig(
        slippage_bps=args.slippage_bps,
        latency_ms=args.latency_ms,
        partial_fill_enabled=args.partial_fill,
        partial_fill_fraction=args.partial_fill_fraction,
    )
    return BacktestConfig(
        symbols=tuple(args.symbols),
        data_dir=Path(args.data_dir) if args.data_dir else None,
        out_dir=Path(args.out_dir),
        equity=args.equity,
        limits=limits,
        execution_realism=realism,
        start_ts_ms=_parse_date(args.start_date) if args.start_date else None,
        end_ts_ms=_parse_date(args.end_date) if args.end_date else None,
        telemetry_enabled=args.telemetry,
        fill_journal_enabled=args.fill_journal,
    )