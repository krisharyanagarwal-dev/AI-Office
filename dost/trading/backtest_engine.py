"""
Backtesting Engine for THE CLAUDE COMPANY.

Vectorized backtesting engine that tests trading signals against historical
OHLCV data with realistic transaction costs, slippage, and position sizing.

All backtesting is read-only - reads signal files and OHLCV data, produces
backtest result files. No live orders, no curve-fitting (parameters fixed
before backtest, no optimization during backtest).
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from dost.data_access import (
    compute_log_returns,
    compute_returns,
    get_latest_price,
    load_ohlcv_from_csv,
    load_ohlcv_from_directory,
)
from dost.trading.strategy_engine import SIGNAL_DIR

BACKTEST_DIR = Path(os.path.expanduser("~/.openclaw/backtests"))
BACKTEST_RESULTS_DIR = BACKTEST_DIR / "results"
BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
BACKTEST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class BacktestResult:
    """Result of a backtest run."""

    task_id: str
    signal_id: str
    instrument: str
    strategy_name: str
    start_date: str
    end_date: str
    total_return: float
    total_return_pct: float
    max_drawdown: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    total_cost_units: float
    net_value: float
    equity_curve: List[Dict[str, Any]]
    trade_list: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BacktestResult":
        return cls(**d)


def _calculate_position_size(
    capital: float,
    risk_per_trade: float,
    entry_price: float,
    stop_loss: float,
) -> float:
    """Calculate position size based on risk per trade.

    Args:
        capital: Total capital available.
        risk_per_trade: Risk per trade as decimal (e.g., 0.02 = 2%).
        entry_price: Entry price per share/unit.
        stop_loss: Stop loss price.

    Returns:
        Position size in units.
    """
    if entry_price <= 0 or stop_loss <= 0:
        return 0.0

    risk_amount = capital * risk_per_trade
    risk_per_unit = abs(entry_price - stop_loss)

    if risk_per_unit <= 0:
        return 0.0

    size = risk_amount / risk_per_unit
    return size


def run_backtest(
    signal: Dict[str, Any],
    candles: List[Dict[str, Any]],
    initial_capital: float = 100000.0,
    risk_per_trade: float = 0.02,
    commission_pct: float = 0.001,  # 0.1% commission per trade
    slippage_pct: float = 0.0005,   # 0.05% slippage per trade
    funding_rate_pct: float = 0.0001,  # 0.01% funding per day (for perpetuals)
) -> Dict[str, Any]:
    """Run a backtest for a signal against historical OHLCV data.

    Args:
        signal: Signal dict from strategy_engine.
        candles: List of OHLCV dicts sorted by timestamp.
        initial_capital: Starting capital in currency units.
        risk_per_trade: Risk per trade as decimal (default 2%).
        commission_pct: Commission per trade as decimal (default 0.1%).
        slippage_pct: Slippage per trade as decimal (default 0.05%).
        funding_rate_pct: Funding rate per day for perpetuals (default 0.01%).

    Returns:
        Backtest result dict.
    """
    signal_id = signal.get("task_id", f"signal-{uuid.uuid4().hex[:8]}")
    agent_id = signal.get("agent_id", "unknown")
    instrument = signal.get("instrument", "UNKNOWN")
    strategy_name = signal.get("strategy_name", "unknown")
    direction = signal.get("direction", "neutral")
    entry_price_signal = signal.get("entry_price", 0) or 0
    stop_loss_signal = signal.get("stop_loss")
    take_profit_signal = signal.get("take_profit")

    if not candles or len(candles) < 2:
        return _empty_backtest_result(signal_id, signal_id, instrument, strategy_name)

    # Extract price series
    closes = [c.get("close", 0) for c in candles]
    highs = [c.get("high", 0) for c in candles]
    lows = [c.get("low", 0) for c in candles]
    opens = [c.get("open", 0) for c in candles]
    timestamps = [c.get("timestamp", 0) for c in candles]
    timestamps_str = [c.get("timestamp_str", "") for c in candles]

    # Find entry point - use the signal's entry price or the last close
    if entry_price_signal > 0:
        entry_price = entry_price_signal
    else:
        entry_price = closes[-1]

    # Find entry index - the candle where price is closest to entry_price
    entry_idx = 0
    min_diff = float("inf")
    for i, close in enumerate(closes):
        diff = abs(close - entry_price)
        if diff < min_diff:
            min_diff = diff
            entry_idx = i

    # If starting from current price, use the last candle
    if entry_price_signal <= 0:
        entry_idx = len(closes) - 1

    # Simulate the trade from entry point
    capital = initial_capital
    position_size = 0.0
    position_entry_price = 0.0
    position_direction = direction  # "long", "short", or "neutral"

    if direction == "neutral":
        return _empty_backtest_result(
            signal_id, signal_id, instrument, strategy_name, "neutral"
        )

    # Calculate position size based on risk
    stop_loss = stop_loss_signal if stop_loss_signal else entry_price * 0.98
    if direction == "long":
        position_size = _calculate_position_size(capital, risk_per_trade, entry_price, stop_loss)
        if position_size <= 0:
            position_size = capital / entry_price  # Fallback: all in
    elif direction == "short":
        position_size = _calculate_position_size(capital, risk_per_trade, entry_price, stop_loss)
        if position_size <= 0:
            position_size = capital / entry_price  # Fallback: all in
    else:
        position_size = 0.0

    # Track equity curve
    equity_curve = []
    trade_list = []

    # Execute the trade from entry point
    total_commission = 0.0
    total_slippage = 0.0
    total_funding = 0.0

    max_equity = capital
    min_equity = capital
    max_drawdown = 0.0
    max_drawdown_pct = 0.0

    position_active = True
    exit_reason = None

    for i in range(entry_idx + 1, len(closes)):
        current_close = closes[i]
        current_high = highs[i]
        current_low = lows[i]
        current_timestamp = timestamps[i]
        current_timestamp_str = timestamps_str[i]

        # Check stop loss and take profit
        if position_active:
            if direction == "long":
                if current_low <= stop_loss:
                    exit_price = stop_loss
                    exit_reason = "stop_loss"
                    position_active = False
                elif take_profit and current_high >= take_profit:
                    exit_price = take_profit
                    exit_reason = "take_profit"
                    position_active = False
            elif direction == "short":
                if current_high >= stop_loss:
                    exit_price = stop_loss
                    exit_reason = "stop_loss"
                    position_active = False
                elif take_profit and current_low <= take_profit:
                    exit_price = take_profit
                    exit_reason = "take_profit"
                    position_active = False

        # Calculate current equity
        if position_active:
            if direction == "long":
                unrealized_pnl = position_size * (current_close - entry_price)
            else:
                unrealized_pnl = position_size * (entry_price - current_close)
        else:
            unrealized_pnl = 0.0

        current_equity = capital + unrealized_pnl - total_commission - total_slippage - total_funding
        equity_curve.append({
            "timestamp": current_timestamp,
            "timestamp_str": current_timestamp_str,
            "equity": round(current_equity, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "price": current_close,
        })

        max_equity = max(max_equity, current_equity)
        min_equity = min(min_equity, current_equity)
        current_drawdown = max_equity - current_equity
        if max_equity > 0:
            current_drawdown_pct = (current_drawdown / max_equity) * 100
        else:
            current_drawdown_pct = 0
        max_drawdown = max(max_equity - current_equity, max_drawdown)
        max_drawdown_pct = max(max_drawdown_pct, current_drawdown_pct)

        # Exit position if triggered
        if not position_active:
            # Calculate final PnL
            if direction == "long":
                gross_pnl = position_size * (exit_price - entry_price)
            else:
                gross_pnl = position_size * (entry_price - exit_price)

            # Apply commission and slippage on exit
            exit_commission = position_size * exit_price * commission_pct
            exit_slippage = position_size * exit_price * slippage_pct

            total_commission += exit_commission
            total_slippage += exit_slippage

            net_pnl = gross_pnl - exit_commission - exit_slippage

            trade_list.append({
                "entry_time": timestamps[entry_idx] if entry_idx < len(timestamps) else 0,
                "entry_time_str": timestamps_str[entry_idx] if entry_idx < len(timestamps_str) else "",
                "exit_time": current_timestamp,
                "exit_time_str": current_timestamp_str,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "position_size": position_size,
                "direction": direction,
                "gross_pnl": round(gross_pnl, 2),
                "net_pnl": round(net_pnl, 2),
                "commission": round(exit_commission, 2),
                "slippage": round(exit_slippage, 2),
                "exit_reason": exit_reason,
            })
            break

        # Apply funding cost for perpetuals (daily)
        if direction != "neutral":
            daily_funding = position_size * current_close * funding_rate_pct
            total_funding += daily_funding

    # If position still open at end, close at last price
    if position_active:
        exit_price = closes[-1]
        if direction == "long":
            gross_pnl = position_size * (exit_price - entry_price)
        else:
            gross_pnl = position_size * (entry_price - exit_price)

        exit_commission = position_size * exit_price * commission_pct
        exit_slippage = position_size * exit_price * slippage_pct

        total_commission += exit_commission
        total_slippage += exit_slippage

        net_pnl = gross_pnl - exit_commission - exit_slippage

        trade_list.append({
            "entry_time": timestamps[entry_idx] if entry_idx < len(timestamps) else 0,
            "entry_time_str": timestamps_str[entry_idx] if entry_idx < len(timestamps_str) else "",
            "exit_time": timestamps[-1],
            "exit_time_str": timestamps_str[-1],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "position_size": position_size,
            "direction": direction,
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "commission": round(exit_commission, 2),
            "slippage": round(exit_slippage, 2),
            "exit_reason": "end_of_data",
        })

    # Calculate metrics
    total_cost_units = total_commission + total_slippage + total_funding
    net_value = capital + sum(t["net_pnl"] for t in trade_list) - total_cost_units

    if total_trades := len(trade_list):
        winning_trades = sum(1 for t in trade_list if t["net_pnl"] > 0)
        losing_trades = sum(1 for t in trade_list if t["net_pnl"] < 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        avg_win = sum(t["net_pnl"] for t in trade_list if t["net_pnl"] > 0) / max(winning_trades, 1)
        avg_loss = sum(t["net_pnl"] for t in trade_list if t["net_pnl"] < 0) / max(losing_trades, 1)
        gross_profit = sum(t["net_pnl"] for t in trade_list if t["net_pnl"] > 0)
        gross_loss = abs(sum(t["net_pnl"] for t in trade_list if t["net_pnl"] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0
    else:
        win_rate = 0.0
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        avg_win = 0.0
        avg_loss = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        profit_factor = 0.0

    # Sharpe ratio (annualized, assuming daily data)
    if len(equity_curve) > 1:
        equity_values = [e["equity"] for e in equity_curve]
        returns = compute_returns([{"close": v} for v in equity_values])
        if len(returns) > 1 and any(r != 0 for r in returns):
            mean_return = sum(returns) / len(returns)
            std_return = (sum((r - mean_return) ** 2 for r in returns) / len(returns)) ** 0.5
            if std_return > 0:
                sharpe_ratio = (mean_return / std_return) * (252 ** 0.5)  # Annualized
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0
    else:
        sharpe_ratio = 0.0

    # Sortino ratio
    if len(equity_curve) > 1:
        equity_values = [e["equity"] for e in equity_curve]
        returns = compute_returns([{"close": v} for v in equity_values])
        downside_returns = [r for r in returns if r < 0]
        if len(downside_returns) > 0:
            downside_std = (sum(r ** 2 for r in downside_returns) / len(downside_returns)) ** 0.5
            if downside_std > 0:
                mean_return = sum(returns) / len(returns)
                sortino_ratio = (mean_return / downside_std) * (252 ** 0.5)
            else:
                sortino_ratio = 0.0
        else:
            sortino_ratio = 0.0
    else:
        sortino_ratio = 0.0

    # Calmar ratio
    if max_drawdown_pct > 0:
        calmar_ratio = (total_return_pct / 100) / (max_drawdown_pct / 100)
    else:
        calmar_ratio = 0.0

    result = BacktestResult(
        task_id=signal_id,
        signal_id=signal_id,
        instrument=instrument,
        strategy_name=strategy_name,
        start_date=timestamps_str[entry_idx] if entry_idx < len(timestamps_str) else "",
        end_date=timestamps_str[-1] if timestamps_str else "",
        total_return=net_value - initial_capital,
        total_return_pct=((net_value - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0.0,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        calmar_ratio=calmar_ratio,
        total_cost_units=total_cost_units,
        net_value=net_value,
        equity_curve=equity_curve,
        trade_list=trade_list,
    )

    result_dict = result.to_dict()
    result_dict["status"] = "done"
    return result_dict


def _empty_backtest_result(task_id: str, signal_id: str, instrument: str, strategy_name: str, reason: str = "insufficient_data") -> Dict[str, Any]:
    """Create an empty backtest result when there's insufficient data."""
    return {
        "task_id": signal_id,
        "signal_id": signal_id,
        "instrument": instrument,
        "strategy_name": strategy_name,
        "start_date": "",
        "end_date": "",
        "total_return": 0.0,
        "total_return_pct": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "win_rate": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "total_cost_units": 0.0,
        "net_value": 0.0,
        "equity_curve": [],
        "trade_list": [],
        "error": reason,
    }


def save_backtest_result(result_dict: Dict[str, Any]) -> str:
    """Save backtest result to file.

    Args:
        result_dict: Result dict from run_backtest.

    Returns:
        task_id of the saved result.
    """
    BACKTEST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_id = result_dict.get("task_id", f"backtest-{uuid.uuid4().hex[:8]}")
    task_path = BACKTEST_RESULTS_DIR / f"{result_id}.json"
    with open(task_path, "w") as f:
        json.dump(result_dict, f, indent=2)
    return result_id


def load_backtest_result(result_id: str) -> Optional[Dict[str, Any]]:
    """Load a backtest result by ID."""
    path = BACKTEST_RESULTS_DIR / f"{result_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_backtest_results() -> List[Dict[str, Any]]:
    """List all backtest results."""
    if not BACKTEST_RESULTS_DIR.exists():
        return []

    results = []
    for f in sorted(BACKTEST_RESULTS_DIR.glob("*.json")):
        try:
            result = json.loads(f.read_text())
            results.append(result)
        except (json.JSONDecodeError, OSError):
            continue

    results.sort(key=lambda r: r.get("task_id", ""))
    return results