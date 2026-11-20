"""
Out-of-Sample Validation for THE CLAUDE COMPANY.

Validates backtest results against out-of-sample data to prevent curve-fitting
and ensure strategy robustness across different market regimes.

All validation is read-only - reads backtest results and OOS data, produces
validation reports. No live orders, no strategy curve-fitting.
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

from dost.trading.backtest_engine import (
    BACKTEST_DIR,
    BACKTEST_RESULTS_DIR,
    load_backtest_result,
    list_backtest_results,
)
from dost.data_access import (
    compute_log_returns,
    compute_returns,
    load_ohlcv_from_csv,
    load_ohlcv_from_directory,
)

OOS_DIR = Path(os.path.expanduser("~/.openclaw/oos_validation"))
OOS_RESULTS_DIR = OOS_DIR / "results"
OOS_DIR.mkdir(parents=True, exist_ok=True)
OOS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class OOSResult:
    """Out-of-sample validation result."""

    validation_id: str
    backtest_task_id: str
    agent_id: str
    instrument: str
    strategy_name: str
    is_oos_passed: bool
    oos_return: float
    oos_return_pct: float
    oos_max_drawdown: float
    oos_max_drawdown_pct: float
    oos_win_rate: float
    oos_total_trades: int
    oos_winning_trades: int
    oos_losing_trades: int
    oos_profit_factor: float
    oos_sharpe_ratio: float
    parameter_stability: float  # 0.0 to 1.0 - how stable parameters are across regimes
    regime_consistency: float  # 0.0 to 1.0 - consistency across market regimes
    overall_score: float  # 0.0 to 1.0 - combined validation score
    passes_threshold: bool  # Whether it passes Tier C review threshold
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OOSResult":
        return cls(**d)


def _calculate_sharpe(returns: List[float], periods_per_year: int = 252) -> float:
    """Calculate annualized Sharpe ratio from returns."""
    if len(returns) < 2:
        return 0.0
    mean_return = sum(returns) / len(returns)
    if len(returns) < 2:
        return 0.0
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return 0.0
    return (mean_return / std_dev) * math.sqrt(periods_per_year)


def _calculate_sortino(returns: List[float], periods_per_year: int = 252) -> float:
    """Calculate annualized Sortino ratio."""
    if len(returns) < 2:
        return 0.0
    mean_return = sum(returns) / len(returns)
    downside_returns = [r for r in returns if r < 0]
    if not downside_returns:
        return float("inf") if mean_return > 0 else 0.0
    downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
    downside_std = math.sqrt(downside_variance)
    if downside_std == 0:
        return float("inf") if mean_return > 0 else 0.0
    return (mean_return / downside_std) * math.sqrt(periods_per_year)


def _calculate_max_drawdown(equity_curve: List[float]) -> tuple:
    """Calculate max drawdown from equity curve."""
    if not equity_curve:
        return 0.0, 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        dd = peak - value
        dd_pct = (dd / peak) * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
    return max_dd, max_dd_pct


def run_oos_validation(
    backtest_result_id: str,
    oos_candles: List[Dict[str, Any]],
    is_backtest_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run out-of-sample validation on a backtested strategy.

    Args:
        backtest_result_id: ID of the backtest result to validate.
        oos_candles: Out-of-sample OHLCV data.
        is_backtest_result: Optional backtest result dict (loaded if not provided).

    Returns:
        OOS validation result dict.
    """
    # Load backtest result
    if is_backtest_result is None:
        backtest_result = load_backtest_result(backtest_result_id)
        if not backtest_result:
            return {
                "validation_id": f"oos-{uuid.uuid4().hex[:8]}",
                "backtest_task_id": backtest_result_id,
                "agent_id": "unknown",
                "instrument": "UNKNOWN",
                "strategy_name": "unknown",
                "is_oos_passed": False,
                "oos_return": 0.0,
                "oos_return_pct": 0.0,
                "oos_max_drawdown": 0.0,
                "oos_max_drawdown_pct": 0.0,
                "oos_win_rate": 0.0,
                "oos_total_trades": 0,
                "oos_winning_trades": 0,
                "oos_losing_trades": 0,
                "oos_profit_factor": 0.0,
                "oos_sharpe_ratio": 0.0,
                "parameter_stability": 0.0,
                "regime_consistency": 0.0,
                "overall_score": 0.0,
                "passes_threshold": False,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error": "Backtest result not found",
            }
    else:
        backtest_result = is_backtest_result

    signal_id = backtest_result.get("task_id", backtest_result_id)
    agent_id = backtest_result.get("agent_id", "unknown")
    instrument = backtest_result.get("instrument", "UNKNOWN")
    strategy_name = backtest_result.get("strategy_name", "unknown")

    # If no OOS data, cannot validate
    if not oos_candles or len(oos_candles) < 2:
        return {
            "validation_id": f"oos-{uuid.uuid4().hex[:8]}",
            "backtest_task_id": signal_id,
            "agent_id": agent_id,
            "instrument": instrument,
            "strategy_name": strategy_name,
            "is_oos_passed": False,
            "oos_return": 0.0,
            "oos_return_pct": 0.0,
            "oos_max_drawdown": 0.0,
            "oos_max_drawdown_pct": 0.0,
            "oos_win_rate": 0.0,
            "oos_total_trades": 0,
            "oos_winning_trades": 0,
            "oos_losing_trades": 0,
            "oos_profit_factor": 0.0,
            "oos_sharpe_ratio": 0.0,
            "parameter_stability": 0.0,
            "regime_consistency": 0.0,
            "overall_score": 0.0,
            "passes_threshold": False,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "error": "No out-of-sample data provided",
        }

    # Run the strategy on OOS data
    # Re-run the backtest logic on OOS data
    from dost.trading.backtest_engine import run_backtest

    oos_result = run_backtest(
        backtest_result,
        oos_candles,
        initial_capital=backtest_result.get("initial_capital", 100000.0),
        risk_per_trade=backtest_result.get("risk_per_trade", 0.02),
        commission_pct=backtest_result.get("commission_pct", 0.001),
        slippage_pct=backtest_result.get("slippage_pct", 0.0005),
    )

    # Calculate OOS metrics
    oos_return = oos_result.get("net_value", 0) - 100000.0  # Assuming 100k initial
    oos_return_pct = oos_result.get("net_value", 0) / 100000.0 * 100 - 100 if 100000.0 > 0 else 0.0
    oos_max_drawdown = oos_result.get("max_drawdown", 0.0)
    oos_max_drawdown_pct = oos_result.get("max_drawdown_pct", 0.0)
    oos_win_rate = oos_result.get("win_rate", 0.0)
    oos_total_trades = oos_result.get("total_trades", 0)
    oos_winning_trades = oos_result.get("winning_trades", 0)
    oos_losing_trades = oos_result.get("losing_trades", 0)
    oos_profit_factor = oos_result.get("profit_factor", 0.0)
    oos_sharpe_ratio = oos_result.get("sharpe_ratio", 0.0)

    # Calculate parameter stability - how consistent are parameters across regimes?
    # For now, use a simplified metric based on the consistency of returns
    parameter_stability = min(1.0, max(0.0, 1.0 - abs(oos_return_pct - backtest_result.get("total_return_pct", 0)) / 100))

    # Calculate regime consistency - how consistent is performance across different market regimes
    regime_consistency = _calculate_regime_consistency(oos_candles, oos_result.get("equity_curve", []))

    # Calculate overall score
    # Weighted combination of various factors
    oos_return_score = min(1.0, max(0.0, (oos_return_pct + 20) / 40))  # Normalize around 0%
    sharpe_score = min(1.0, max(0.0, (oos_sharpe_ratio + 2) / 4))  # Normalize around 0-2
    drawdown_score = max(0.0, 1.0 - oos_max_drawdown_pct / 50)  # Penalize high drawdown
    win_rate_score = oos_win_rate  # Already 0-1

    overall_score = (
        oos_return_score * 0.3 +
        sharpe_score * 0.3 +
        drawdown_score * 0.2 +
        win_rate_score * 0.1 +
        parameter_stability * 0.1
    )

    # Determine if passes threshold
    passes_threshold = (
        overall_score >= 0.6 and
        oos_max_drawdown_pct < 20 and  # Max 20% drawdown
        oos_sharpe_ratio > 0.5 and  # Minimum Sharpe
        oos_win_rate > 0.4  # Minimum 40% win rate
    )

    return {
        "validation_id": f"oos-{uuid.uuid4().hex[:8]}",
        "backtest_task_id": signal_id,
        "agent_id": agent_id,
        "instrument": instrument,
        "strategy_name": strategy_name,
        "is_oos_passed": is_oos_passed,
        "oos_return": round(oos_return, 2),
        "oos_return_pct": round(oos_return_pct, 2),
        "oos_max_drawdown": round(oos_max_drawdown, 2),
        "oos_max_drawdown_pct": round(oos_max_drawdown_pct, 2),
        "oos_win_rate": round(oos_win_rate, 4),
        "oos_total_trades": oos_total_trades,
        "oos_winning_trades": oos_winning_trades,
        "oos_losing_trades": oos_losing_trades,
        "oos_profit_factor": round(oos_profit_factor, 2),
        "oos_sharpe_ratio": round(oos_sharpe_ratio, 2),
        "parameter_stability": round(parameter_stability, 4),
        "regime_consistency": round(regime_consistency, 4),
        "overall_score": round(overall_score, 4),
        "passes_threshold": passes_threshold,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _calculate_regime_consistency(candles: List[Dict[str, Any]], equity_curve: List[Dict[str, Any]]) -> float:
    """Calculate how consistent performance is across different market regimes.

    Splits the OOS period into sub-periods and checks if performance is
    consistent across them.
    """
    if len(candles) < 10 or len(equity_curve) < 2:
        return 0.0

    # Split into 3 roughly equal periods
    n = len(candles)
    segment_size = max(1, n // 3)

    segment_returns = []
    for i in range(0, len(candles), segment_size):
        segment = candles[i:i + segment_size]
        if len(segment) < 2:
            continue
        closes = [c.get("close", 0) for c in segment]
        if len(closes) < 2:
            continue
        ret = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0
        segment_returns.append(ret)

    if len(segment_returns) < 2:
        return 0.0

    # Calculate consistency as inverse of variance in segment returns
    mean_ret = sum(segment_returns) / len(segment_returns)
    variance = sum((r - mean_ret) ** 2 for r in segment_returns) / len(segment_returns)

    if variance == 0:
        return 1.0

    # Lower variance = higher consistency
    consistency = 1.0 / (1.0 + variance * 10)
    return max(0.0, min(1.0, consistency))


def save_oos_result(result_dict: Dict[str, Any]) -> str:
    """Save OOS validation result to file.

    Args:
        result_dict: Result dict from run_oos_validation.

    Returns:
        validation_id of the saved result.
    """
    OOS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_id = result_dict.get("validation_id", f"oos-{uuid.uuid4().hex[:8]}")
    task_path = OOS_RESULTS_DIR / f"{result_id}.json"
    with open(task_path, "w") as f:
        json.dump(result_dict, f, indent=2)
    return result_id


def load_oos_result(validation_id: str) -> Optional[Dict[str, Any]]:
    """Load an OOS validation result by ID."""
    path = OOS_RESULTS_DIR / f"{validation_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_oos_results() -> List[Dict[str, Any]]:
    """List all OOS validation results."""
    if not OOS_RESULTS_DIR.exists():
        return []

    results: List[Dict[str, Any]] = []
    for f in sorted(OOS_RESULTS_DIR.glob("*.json")):
        try:
            result = json.loads(f.read_text())
            results.append(result)
        except (json.JSONDecodeError, OSError):
            continue

    results.sort(key=lambda r: r.get("timestamp", ""))
    return results