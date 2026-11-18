"""
Position Sizing for THE CLAUDE COMPANY.

Calculates position sizes based on various sizing methods:
- Fixed fractional (fixed % of capital per trade)
- Kelly criterion (optimal growth based on win rate and payoff ratio)
- Fixed dollar amount
- Volatility-based (ATR-based)
- Equal weight (equal allocation across positions)

All calculations are read-only and produce sizing recommendations only.
No live orders are placed.
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

SIZING_DIR = Path(os.path.expanduser("~/.openclaw/position_sizing"))
SIZING_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class PositionSize:
    """Position sizing result."""

    task_id: str
    agent_id: str
    instrument: str
    direction: str  # "long", "short"
    signal_confidence: float  # 0.0 to 1.0
    entry_price: float
    stop_loss: Optional[float]
    method: str  # "fixed_fraction", "kelly", "fixed_dollar", "volatility", "equal_weight"
    cost_units: int  # Cost units consumed
    position_size: float  # Number of units/shares
    position_value: float  # Position value in currency
    cost_units_used: int  # Cost units consumed
    risk_amount: float  # Amount at risk in currency
    risk_percent: float  # Risk as % of capital
    leverage: float  # Leverage ratio
    max_position_size: float  # Maximum allowed position size
    sizing_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PositionSize":
        return cls(**d)


def fixed_fraction_sizing(
    capital: float,
    risk_per_trade: float,
    entry_price: float,
    stop_loss: Optional[float],
) -> float:
    """Fixed fractional position sizing.

    Risks a fixed percentage of capital per trade.
    Position size = (Capital * RiskPerTrade) / |EntryPrice - StopLoss|

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


def kelly_sizing(
    win_rate: float,
    win_loss_ratio: float,
    capital: float,
    kelly_fraction: float = 0.25,  # Conservative Kelly (quarter Kelly)
) -> float:
    """Kelly Criterion position sizing.

    Kelly % = (WinRate * (WinLossRatio + 1) - 1) / WinLossRatio
    Or equivalently: Kelly % = (WinRate - (1 - WinRate) / WinLossRatio)

    Args:
        win_rate: Win rate as decimal (e.g., 0.6 = 60%).
        win_loss_ratio: Ratio of average win to average loss.
        capital: Total capital available.
        kelly_fraction: Fraction of full Kelly to use (0.25 = quarter Kelly, conservative).

    Returns:
        Position size in currency units.
    """
    if win_rate <= 0 or win_rate >= 1 or win_loss_ratio <= 0:
        return 0.0

    kelly_percent = (win_rate * (win_loss_ratio + 1) - 1) / win_loss_ratio
    # Alternative: kelly_percent = win_rate - (1 - win_rate) / win_loss_ratio

    if kelly_percent <= 0:
        return 0.0

    # Apply Kelly fraction (typically 0.25 to 0.5 for safety)
    kelly_percent = kelly_percent * kelly_fraction

    position_value = capital * kelly_percent
    return position_value


def fixed_dollar_sizing(
    capital: float,
    fixed_dollar_amount: float,
) -> float:
    """Fixed dollar amount position sizing.

    Args:
        capital: Total capital available.
        fixed_dollar_amount: Fixed dollar amount to risk per trade.

    Returns:
        Position size in currency units.
    """
    return min(fixed_dollar_amount, capital)


def volatility_sizing(
    capital: float,
    risk_per_trade: float,
    entry_price: float,
    stop_loss: Optional[float],
    atr: float,  # Average True Range
    atr_multiplier: float = 2.0,
) -> float:
    """Volatility-based position sizing (ATR-based).

    Position size is based on ATR (Average True Range) to account for
    volatility. Higher volatility = smaller position size.

    Args:
        capital: Total capital available.
        risk_per_trade: Risk per trade as decimal.
        entry_price: Entry price per share/unit.
        stop_loss: Stop loss price.
        atr: Average True Range value.
        atr_multiplier: Multiplier for ATR to determine stop distance.

    Returns:
        Position size in units.
    """
    if entry_price <= 0 or atr <= 0:
        return 0.0

    risk_amount = capital * risk_per_trade
    risk_per_unit = atr * atr_multiplier

    if risk_per_unit <= 0:
        return 0.0

    size = risk_amount / risk_per_unit
    return size


def equal_weight_sizing(
    capital: float,
    num_positions: int,
) -> float:
    """Equal weight position sizing.

    Divides capital equally across N positions.

    Args:
        capital: Total capital available.
        num_positions: Number of positions to divide capital among.

    Returns:
        Position size in currency units per position.
    """
    if num_positions <= 0:
        return 0.0

    return capital / num_positions


def calculate_position_size(
    agent_id: str,
    instrument: str,
    direction: str,
    signal_confidence: float,
    entry_price: float,
    stop_loss: Optional[float],
    cost_units: int,
    method: str = "fixed_fraction",
    capital: float = 100000.0,
    risk_per_trade: float = 0.02,
    kelly_win_rate: float = 0.5,
    kelly_win_loss_ratio: float = 1.0,
    kelly_fraction: float = 0.25,
    fixed_dollar_amount: float = 1000.0,
    atr: float = 0.0,
    atr_multiplier: float = 2.0,
    num_positions: int = 1,
) -> Dict[str, Any]:
    """Calculate position size for a trade signal.

    Args:
        agent_id: ID of the agent generating the signal.
        instrument: Trading instrument symbol.
        direction: Trade direction ("long", "short", "neutral").
        signal_confidence: Signal confidence (0.0 to 1.0).
        entry_price: Entry price per share/unit.
        stop_loss: Stop loss price.
        cost_units: Cost units available for this trade.
        method: Sizing method ("fixed_fraction", "kelly", "fixed_dollar", "volatility", "equal_weight").
        capital: Total capital available.
        risk_per_trade: Risk per trade as decimal.
        kelly_win_rate: Win rate for Kelly calculation.
        kelly_win_loss_ratio: Win/loss ratio for Kelly calculation.
        kelly_fraction: Kelly fraction (0.25 = quarter Kelly).
        fixed_dollar_amount: Fixed dollar amount for fixed dollar sizing.
        atr: Average True Range value.
        atr_multiplier: Multiplier for ATR.
        num_positions: Number of positions for equal weight sizing.

    Returns:
        Position sizing result dict.
    """
    task_id = f"position-{uuid.uuid4().hex[:8]}"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    if direction == "neutral" or entry_price <= 0:
        position_size = 0.0
        cost_units_used = 0
        risk_amount = 0.0
        risk_percent = 0.0
        leverage = 0.0
        max_position_size = 0.0
    else:
        # Calculate position size based on method
        if method == "fixed_fraction":
            position_size = fixed_fraction_sizing(capital, risk_per_trade, entry_price, stop_loss)
        elif method == "kelly":
            position_size = kelly_sizing(kelly_win_rate, kelly_win_loss_ratio, capital, kelly_fraction)
        elif method == "fixed_dollar":
            position_size = fixed_dollar_sizing(capital, fixed_dollar_amount)
        elif method == "volatility":
            position_size = volatility_sizing(capital, risk_per_trade, entry_price, stop_loss, atr, atr_multiplier)
        elif method == "equal_weight":
            position_size = equal_weight_sizing(capital, num_positions)
        else:
            position_size = fixed_fraction_sizing(capital, risk_per_trade, entry_price, stop_loss)

        # Calculate cost units used (proportional to position size relative to capital)
        if capital > 0:
            cost_units_used = int((position_size / capital) * cost_units)
        else:
            cost_units_used = 0

        # Calculate risk amount
        if direction == "long" and stop_loss and stop_loss > 0:
            risk_amount = position_size * abs(entry_price - stop_loss)
        elif direction == "short" and stop_loss and stop_loss > 0:
            risk_amount = position_size * abs(stop_loss - entry_price)
        else:
            risk_amount = position_size * entry_price * 0.02  # Default 2% risk

        risk_percent = risk_amount / capital if capital > 0 else 0.0

        # Calculate leverage
        position_value = position_size * entry_price
        leverage = position_value / capital if capital > 0 else 0.0

        # Max position size based on available capital
        max_position_size = capital / entry_price if entry_price > 0 else 0.0

    position_size_obj = PositionSize(
        task_id=task_id,
        agent_id=agent_id,
        instrument=instrument,
        direction=direction,
        signal_confidence=signal_confidence,
        entry_price=round(entry_price, 2),
        stop_loss=round(stop_loss, 2) if stop_loss else None,
        method=method,
        cost_units=cost_units_used,
        position_size=round(position_size, 6),
        position_value=round(position_size * entry_price, 2),
        cost_units_used=cost_units_used,
        risk_amount=round(risk_amount, 2),
        risk_percent=round(risk_percent * 100, 2),
        leverage=round(leverage, 4),
        max_position_size=round(max_position_size, 6),
        sizing_timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    return position_size_obj.to_dict()


def save_position_size(result_dict: Dict[str, Any]) -> str:
    """Save position sizing result to file.

    Args:
        result_dict: Position sizing result dict.

    Returns:
        task_id of the saved result.
    """
    SIZING_DIR.mkdir(parents=True, exist_ok=True)
    result_id = result_dict.get("task_id", f"position-{uuid.uuid4().hex[:8]}")
    task_path = SIZING_DIR / f"{result_id}.json"
    with open(task_path, "w") as f:
        json.dump(result_dict, f, indent=2)
    return result_id


def load_position_size(task_id: str) -> Optional[Dict[str, Any]]:
    """Load a position sizing result by task ID."""
    path = SIZING_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_position_sizes() -> List[Dict[str, Any]]:
    """List all position sizing results."""
    if not SIZING_DIR.exists():
        return []

    results: List[Dict[str, Any]] = []
    for f in sorted(SIZING_DIR.glob("*.json")):
        try:
            result = json.loads(f.read_text())
            results.append(result)
        except (json.JSONDecodeError, OSError):
            continue

    results.sort(key=lambda r: r.get("sizing_timestamp", ""))
    return results