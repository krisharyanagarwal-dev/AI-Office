"""Historical backtest runner for the best-signal bot.

Replays the exact paper-mode decision pipeline over archived data.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from best_signal.backtest_config import BacktestConfig, config_from_args
from best_signal.backtest_state import BacktestState
from best_signal.evidence import default_registry, select_tradable
from best_signal.execution import (
    ACTION_CLOSE,
    ACTION_FLIP,
    ACTION_HOLD,
    ACTION_NO_TRADE,
    ACTION_OPEN,
    ExecutionResult,
    build_paper_venue,
    load_price_at,
    risk_limits_for,
    run_paper_execution,
)
from best_signal.fill_journal import FillJournal, record_fill
from best_signal.funding import FundingPrint, load_symbol_prints
from best_signal.position import RiskLimits, build_paper_position
from best_signal.runner import _causal_price_returns
from best_signal.telemetry import TelemetrySink, record_cycle
from best_signal.report import build_report, write_report
from risk import RiskGovernor


def _load_all_prints(config: BacktestConfig) -> dict[str, list[FundingPrint]]:
    """Load all funding prints for configured symbols."""
    prints_by_symbol = {}
    for symbol in config.symbols:
        prints = load_symbol_prints(symbol, data_dir=config.data_dir)
        if config.start_ts_ms:
            prints = [p for p in prints if p.ts_ms >= config.start_ts_ms]
        if config.end_ts_ms:
            prints = [p for p in prints if p.ts_ms <= config.end_ts_ms]
        prints_by_symbol[symbol] = prints
    return prints_by_symbol


def _build_timestamp_grid(prints_by_symbol: dict[str, list[FundingPrint]]) -> list[int]:
    """Unified sorted timestamp grid across all symbols."""
    all_ts = set()
    for prints in prints_by_symbol.values():
        all_ts.update(p.ts_ms for p in prints)
    return sorted(all_ts)


def _prints_up_to(prints: list[FundingPrint], ts_ms: int) -> list[FundingPrint]:
    """Filter prints up to and including timestamp."""
    return [p for p in prints if p.ts_ms <= ts_ms]


def run_backtest(config: BacktestConfig) -> dict:
    """Run historical backtest and return all artifacts."""
    # Setup
    config.out_dir.mkdir(parents=True, exist_ok=True)

    # Load evidence registry
    records = default_registry()
    selected = select_tradable(records)

    # Load data
    prints_by_symbol = _load_all_prints(config)
    timestamps = _build_timestamp_grid(prints_by_symbol)

    # Initialize sinks
    telemetry_sink = TelemetrySink(
        config.out_dir / "telemetry.jsonl",
        enabled=config.telemetry_enabled,
    )
    fill_journal = FillJournal(
        config.out_dir / "fills.jsonl",
        enabled=config.fill_journal_enabled,
    )

    # Initialize state
    state = BacktestState.initial(config.equity)

    # Build venue
    engine, broker = build_paper_venue(
        config.equity,
        realism=config.execution_realism,
        fill_journal=fill_journal,
    )
    governor = RiskGovernor(risk_limits_for(config.limits, config.equity))

    # Pre-compute causal price returns for each symbol (for regime rules)
    returns_by_symbol = {}
    for symbol in config.symbols:
        prints = prints_by_symbol.get(symbol, [])
        returns_by_symbol[symbol] = _causal_price_returns(symbol, prints, config.data_dir)

    # Main loop
    for ts_ms in timestamps:
        # Load prices for all symbols at this timestamp
        prices = {}
        for symbol in config.symbols:
            price, _ = load_price_at(symbol, ts_ms, data_dir=config.data_dir)
            prices[symbol] = price

        # Process each symbol
        for symbol in config.symbols:
            if symbol not in prices:
                continue

            # Get prints up to this timestamp
            prints = _prints_up_to(prints_by_symbol[symbol], ts_ms)
            if not prints:
                continue

            # Current state for this symbol
            current = state.working.get(symbol, {"side": 0, "notional": 0.0})
            current_side = current.get("side", 0)
            current_notional = current.get("notional", 0.0)

            # Gross notional across all symbols
            gross_notional = sum(
                v.get("notional", 0.0) for v in state.working.values() if v.get("side", 0) != 0
            )
            open_symbols = sum(1 for v in state.working.values() if v.get("side", 0) != 0)

            # Day P&L for risk governor
            day_key = state.get_day_key(ts_ms)
            day_pnl = state.day_state.get(day_key, {}).get("pnl", 0.0)

            # Build paper position
            position = build_paper_position(
                symbol=symbol,
                prints=prints,
                records=records,
                limits=config.limits,
                equity=state.equity,
                current_side=current_side,
                current_notional=current_notional,
                gross_notional=gross_notional,
                open_symbols=open_symbols,
                daily_loss_pct=day_pnl / state.equity if state.equity > 0 else 0.0,
                returns=returns_by_symbol.get(symbol),
            )

            # Execute if action requires trading
            result: ExecutionResult | None = None
            if position.action in (ACTION_OPEN, ACTION_FLIP, ACTION_CLOSE):
                result = run_paper_execution(
                    engine=engine,
                    broker=broker,
                    symbol=symbol,
                    side=position.side,
                    notional=position.notional,
                    price=prices[symbol],
                    equity=state.equity,
                    governor=governor,
                    action=position.action,
                    current_side=current_side,
                    current_notional=current_notional,
                )
                # Record telemetry
                record_cycle(
                    telemetry_sink,
                    symbol,
                    position.side,
                    position.notional,
                    position.action,
                    result,
                    broker,
                )

            # Update working state
            if position.action == ACTION_CLOSE:
                state.working[symbol] = {"side": 0, "notional": 0.0}
            elif position.action in (ACTION_OPEN, ACTION_FLIP, ACTION_HOLD):
                state.working[symbol] = {
                    "side": position.side,
                    "notional": position.notional,
                    "last_funding_ts_ms": prints[-1].ts_ms if prints else 0,
                }

            # Record telemetry even for NO_TRADE/HOLD
            if result is None:
                if position.action == ACTION_HOLD:
                    result = ExecutionResult(
                        symbol=symbol,
                        action=ACTION_HOLD,
                        legs=(),
                        fees=0.0,
                        filled=True,
                        reason="held",
                    )
                elif position.action == ACTION_NO_TRADE:
                    result = ExecutionResult(
                        symbol=symbol,
                        action=ACTION_NO_TRADE,
                        legs=(),
                        fees=0.0,
                        filled=True,
                        reason="stand_down",
                    )
                record_cycle(
                    telemetry_sink,
                    symbol,
                    position.side,
                    position.notional,
                    position.action,
                    result,
                    broker,
                )

        # Accrue funding for this timestamp
        day_state = state.ensure_day(ts_ms)
        for symbol in config.symbols:
            prints = _prints_up_to(prints_by_symbol[symbol], ts_ms)
            if not prints:
                continue
            # Find prints exactly at this timestamp
            current_prints = [p for p in prints if p.ts_ms == ts_ms]
            if not current_prints:
                continue
            # Get current notional for funding accrual
            current = state.working.get(symbol, {})
            if current.get("side", 0) != 0:
                notional = current.get("notional", 0.0)
                funding = sum(p.rate for p in current_prints) * notional
                day_state["funding"] += funding
                broker.balances["USDT"] = round(broker.balances.get("USDT", 0.0) + funding, 8)

        # Update day P&L
        day_state["fees"] = broker.fees_total
        day_state["pnl"] = (
            day_state["funding"] - day_state["fees"] + sum(broker.realized_pnl.values())
        )

        # Snapshot for equity curve
        snapshot = state.snapshot_venue(broker, ts_ms)
        state.record_equity_point(snapshot)

    # Generate outputs
    _write_outputs(config, state, broker)

    return {
        "state": state,
        "broker": broker,
        "config": config,
        "equity_curve": state.equity_curve,
    }


def _write_outputs(config: BacktestConfig, state: BacktestState, broker: Any) -> None:
    """Write all backtest artifacts."""
    out_dir = config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Equity curve
    equity_path = out_dir / "equity_curve.jsonl"
    with equity_path.open("w") as f:
        for point in state.equity_curve:
            f.write(json.dumps(point) + "\n")

    # Backtest state
    state_path = out_dir / "backtest_state.json"
    state_path.write_text(json.dumps({
        "equity": state.equity,
        "working": state.working,
        "day_state": state.day_state,
        "equity_curve": state.equity_curve,
    }, indent=2))

    # Report
    report = _build_backtest_report(state, config)
    report_path = out_dir / "backtest_report.md"
    report_path.write_text(report)


def _build_backtest_report(state: BacktestState, config: BacktestConfig) -> str:
    """Generate markdown report with equity curve and metrics."""
    if not state.equity_curve:
        return "# Backtest Report\n\nNo data."

    initial = config.equity
    final = state.equity_curve[-1]["equity"]
    total_return = (final - initial) / initial * 100

    # Daily returns for Sharpe
    daily_returns = []
    day_equity = {}
    for pt in state.equity_curve:
        day = datetime.fromtimestamp(pt["ts_ms"] / 1000, tz=timezone.utc).date()
        day_equity[day] = pt["equity"]

    sorted_days = sorted(day_equity.keys())
    for i in range(1, len(sorted_days)):
        r = (day_equity[sorted_days[i]] - day_equity[sorted_days[i - 1]]) / day_equity[sorted_days[i - 1]]
        daily_returns.append(r)

    sharpe = 0.0
    if daily_returns:
        import math
        mean_r = sum(daily_returns) / len(daily_returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns))
        if std_r > 0:
            sharpe = mean_r / std_r * (252 ** 0.5)

    # Max drawdown
    peak = initial
    max_dd = 0.0
    for pt in state.equity_curve:
        if pt["equity"] > peak:
            peak = pt["equity"]
        dd = (peak - pt["equity"]) / peak
        if dd > max_dd:
            max_dd = dd

    lines = [
        "# Backtest Report",
        f"**Period:** {config.start_ts_ms} to {config.end_ts_ms}",
        f"**Initial Equity:** ${initial:,.2f}",
        f"**Final Equity:** ${final:,.2f}",
        f"**Total Return:** {total_return:.2f}%",
        f"**Sharpe (annualized):** {sharpe:.2f}",
        f"**Max Drawdown:** {max_dd * 100:.2f}%",
        "",
        "## Equity Curve",
        "```",
        "ts_ms,equity,pnl,funding,fees",
    ]
    for pt in state.equity_curve:
        lines.append(f"{pt['ts_ms']},{pt['equity']:.2f},{pt['pnl']:.2f},{pt.get('funding', 0):.2f},{pt.get('fees', 0):.2f}")
    lines.append("```")

    return "\n".join(lines)


def main(argv=None) -> int:
    from best_signal.backtest_config import _build_backtest_parser
    parser = _build_backtest_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    try:
        result = run_backtest(config)
        print(f"Backtest complete. Equity curve: {config.out_dir}/equity_curve.jsonl")
        print(f"Final equity: ${result['state'].equity_curve[-1]['equity']:,.2f}")
        return 0
    except Exception as e:
        print(f"Backtest failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())