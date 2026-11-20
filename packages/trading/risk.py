"""
Risk Governor for OpenClaw Trader Execution Engine.

Enforces pre-trade risk limits and post-trade monitoring constraints.
All limits are checked before order submission; breaches result in
order rejection with a descriptive reason string.

PAPER ONLY — no real orders, no API keys, no funds. Ever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, Tuple

import logging

logger = logging.getLogger(__name__)


class LimitStatus(Enum):
    """Result of a limit check."""

    PASS = auto()
    FAIL = auto()
    WARNING = auto()


@dataclass
class RiskLimits:
    """Configuration for all risk limits.

    Defaults are moderately conservative and intended for production-like
    paper-trade environments. Adjust per your strategy's risk appetite.
    """

    # Confidence
    min_confidence: float = 0.6

    # Notional
    max_notional_pct: float = 0.02  # 2% of equity per trade
    max_notional_abs: Optional[float] = None  # e.g. 1_000_000.0

    # Concentration
    max_symbol_exposure_pct: float = 0.10  # 10% of equity per symbol
    max_total_exposure_pct: float = 0.60  # 60% of equity across all symbols
    max_open_positions: int = 8

    # Daily / drawdown
    max_daily_loss_pct: float = 0.03  # 3% of start-of-day equity
    max_drawdown_pct: float = 0.15  # 15% vs high-water mark

    # State (populated at check time)
    start_of_day_equity: float = 0.0
    high_water_mark: float = 0.0
    daily_pnl: float = 0.0  # running P&L for the day
    positions: Dict[str, dict] = field(default_factory=dict)


@dataclass
class LimitResult:
    """Result of checking the full risk limit suite."""

    status: LimitStatus
    reason: Optional[str] = None  # human-readable reason on FAIL/WARNING


class RiskGovernor:
    """Evaluates risk limits for each signal before execution.

    Checks are applied in the following order, short-circuiting on first FAIL:
    1. Min confidence floor
    2. Max per-trade notional (clamp or reject)
    3. Max per-symbol exposure
    4. Max total exposure
    5. Max open positions
    6. Max daily loss
    7. Max drawdown (kill switch)
    """

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self._daily_pnl_start: float = 0.0

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def update_start_of_day_equity(self, equity: float) -> None:
        """Call once at the beginning of each trading day."""
        self.limits.start_of_day_equity = equity
        self.limits.high_water_mark = equity
        self.limits.daily_pnl = 0.0
        self._daily_pnl_start = equity

    def update_high_water_mark(self, equity: float) -> None:
        """Update high-water mark (call after each trade that improves equity)."""
        if equity > self.limits.high_water_mark:
            self.limits.high_water_mark = equity

    def add_daily_pnl(self, pnl: float) -> None:
        """Add realised P&L for the current day."""
        self.limits.daily_pnl += pnl

    def add_position(self, symbol: str, pos_info: dict) -> None:
        """Track an open position (called after fills)."""
        self.limits.positions[symbol] = pos_info
        self.update_high_water_mark(
            self.limits.start_of_day_equity
            + self.limits.daily_pnl
            + sum(
                (
                    pos.get("avg_entry_price", 0) * pos.get("quantity", 0)
                    if isinstance(pos, dict)
                    else 0
                )
                for pos in self.limits.positions.values()
            )
        )

    # ------------------------------------------------------------------
    # Limit checks (each returns LimitStatus + optional reason)
    # ------------------------------------------------------------------

    def check_min_confidence(self, confidence: float) -> LimitResult:
        if confidence >= self.limits.min_confidence:
            return LimitResult(status=LimitStatus.PASS)
        return LimitResult(
            status=LimitStatus.FAIL,
            reason=f"confidence {confidence:.2f} below min {self.limits.min_confidence:.2f}",
        )

    def check_max_notional(
        self, symbol: str, notional: float, equity: float
    ) -> LimitResult:
        """Check max per-trade notional (as % of equity or absolute cap)."""
        pct = notional / equity if equity > 0 else 0.0
        if self.limits.max_notional_abs is not None and notional > self.limits.max_notional_abs:
            return LimitResult(
                status=LimitStatus.FAIL,
                reason=f"notional ${notional:,.2f} exceeds abs cap ${self.limits.max_notional_abs:,.2f}",
            )
        if pct > self.limits.max_notional_pct:
            return LimitResult(
                status=LimitStatus.FAIL,
                reason=f"notional {pct:.2%} of equity exceeds per-trade cap {self.limits.max_notional_pct:.2%}",
            )
        return LimitResult(status=LimitStatus.PASS)

    def check_symbol_exposure(self, symbol: str, equity: float) -> LimitResult:
        """Check max exposure to a single symbol."""
        # Current notional for this symbol from open positions
        pos_notional = 0.0
        if symbol in self.limits.positions:
            pos = self.limits.positions[symbol]
            qty = pos.get("quantity", 0) or 0
            entry = pos.get("avg_entry_price", 0) or 0
            pos_notional = abs(qty * entry)

        total_symbol_notional = pos_notional  # no hedging netting in this simple guard
        pct = total_symbol_notional / equity if equity > 0 else 0.0
        if pct > self.limits.max_symbol_exposure_pct:
            return LimitResult(
                status=LimitStatus.FAIL,
                reason=f"symbol {symbol} exposure {pct:.2%} of equity exceeds cap {self.limits.max_symbol_exposure_pct:.2%}",
            )
        return LimitResult(status=LimitStatus.PASS)

    def check_total_exposure(self, equity: float) -> LimitResult:
        """Check aggregate exposure across all open symbols."""
        total_notional = sum(
            (pos.get("avg_entry_price", 0) * pos.get("quantity", 0) or 0)
            for pos in self.limits.positions.values()
        )
        pct = total_notional / equity if equity > 0 else 0.0
        if pct > self.limits.max_total_exposure_pct:
            return LimitResult(
                status=LimitStatus.FAIL,
                reason=f"total exposure {pct:.2%} of equity exceeds cap {self.limits.max_total_exposure_pct:.2%}",
            )
        return LimitResult(status=LimitStatus.PASS)

    def check_max_positions(self) -> LimitResult:
        """Check max number of open positions."""
        if len(self.limits.positions) >= self.limits.max_open_positions:
            return LimitResult(
                status=LimitStatus.FAIL,
                reason=f"open positions {len(self.limits.positions)} >= cap {self.limits.max_open_positions}",
            )
        return LimitResult(status=LimitStatus.PASS)

    def check_daily_loss(self) -> LimitResult:
        """Check max daily loss limit."""
        loss_pct = abs(self.limits.daily_pnl) / self.limits.start_of_day_equity if self.limits.start_of_day_equity > 0 else 0.0
        if loss_pct > self.limits.max_daily_loss_pct:
            return LimitResult(
                status=LimitStatus.FAIL,
                reason=f"daily loss {loss_pct:.2%} of start-of-day equity exceeds cap {self.limits.max_daily_loss_pct:.2%}",
            )
        return LimitResult(status=LimitStatus.PASS)

    def check_drawdown(self) -> LimitResult:
        """Check max drawdown vs high-water mark (kill switch)."""
        current_equity = self.limits.start_of_day_equity + self.limits.daily_pnl
        drawdown_pct = (
            (self.limits.high_water_mark - current_equity) / self.limits.high_water_mark
            if self.limits.high_water_mark > 0 else 0.0
        )
        if drawdown_pct > self.limits.max_drawdown_pct:
            return LimitResult(
                status=LimitStatus.FAIL,
                reason=f"drawdown {drawdown_pct:.2%} of high-water mark exceeds kill-switch cap {self.limits.max_drawdown_pct:.2%}",
            )
        return LimitResult(status=LimitStatus.PASS)

    # ------------------------------------------------------------------
    # Full check pipeline
    # ------------------------------------------------------------------

    def check_all(self, confidence: float, symbol: str, notional: float, equity: float) -> Tuple[LimitStatus, Optional[str]]:
        """Run the full limit suite; short-circuit on first FAIL.

        Returns (status, reason) — status is a LimitStatus enum, reason is
        None on PASS, or a string describing the breach.
        """
        checks = [
            self.check_min_confidence(confidence),
            self.check_max_notional(symbol, notional, equity),
            self.check_symbol_exposure(symbol, equity),
            self.check_total_exposure(equity),
            self.check_max_positions(),
            self.check_daily_loss(),
            self.check_drawdown(),
        ]

        for check in checks:
            if check.status == LimitStatus.FAIL:
                return check.status, check.reason
            if check.status == LimitStatus.WARNING:
                # could soft-block or just log; here we short-circuit fail only
                pass

        return LimitStatus.PASS, None


# ------------------------------------------------------------------
# Convenience: quick check for a single signal
# ------------------------------------------------------------------

def quick_check(
    confidence: float,
    symbol: str,
    notional: float,
    equity: float,
    limits: RiskLimits | None = None,
) -> Tuple[LimitStatus, Optional[str]]:
    """One-liner risk check for a signal.

    Returns (status, reason) — use like:
        status, reason = quick_check(conf, sym, notional, equity)
        if status != LimitStatus.PASS:
            logger.warning(f"Risk reject: {reason}")
            continue
    """
    governor = RiskGovernor(limits)
    # We need start_of_day_equity set; if not, use the notional-equity ratio as rough check
    if governor.limits.start_of_day_equity == 0:
        # No day-start set — do a basic confidence+notional guard
        if confidence < governor.limits.min_confidence:
            return LimitStatus.FAIL, "confidence below min (no day-start)"
        if notional / equity > governor.limits.max_notional_pct if equity > 0 else 1.0:
            return LimitStatus.FAIL, "notional exceeds % of equity (no day-start)"
        return LimitStatus.PASS, None

    return governor.check_all(confidence, symbol, notional, equity)