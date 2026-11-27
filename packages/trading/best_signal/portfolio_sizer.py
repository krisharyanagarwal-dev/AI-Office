"""Portfolio-level position sizing for the best-signal bot.

Allocates gross notional across symbols proportionally by candidate score,
respecting per-symbol cap and total gross cap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SizingInput:
    """Input for one symbol's sizing decision."""

    symbol: str
    side: int              # +1, -1, 0
    action: str            # OPEN, HOLD, FLIP, CLOSE, NO_TRADE
    current_notional: float
    candidate_score: float = 1.0


@dataclass(frozen=True)
class SizingResult:
    """Output target notional for one symbol."""

    symbol: str
    target_notional: float
    action: str
    side: int


def compute_target_notionals(
    inputs: list[SizingInput],
    equity: float,
    limits: Any,  # RiskLimits from best_signal.position
    current_book: dict[str, dict],
) -> list[SizingResult]:
    """Compute target notionals for all symbols respecting portfolio caps."""
    
    # Separate fixed actions (CLOSE, NO_TRADE, HOLD) from flexible (OPEN, FLIP)
    fixed_results = []
    flexible_inputs = []
    
    for inp in inputs:
        if inp.action in ("CLOSE", "NO_TRADE"):
            fixed_results.append(SizingResult(
                symbol=inp.symbol,
                target_notional=0.0,
                action=inp.action,
                side=inp.side,
            ))
        elif inp.action == "HOLD":
            # HOLD preserves exact current notional
            current = current_book.get(inp.symbol, {"notional": inp.current_notional})
            fixed_results.append(SizingResult(
                symbol=inp.symbol,
                target_notional=float(current.get("notional", inp.current_notional)),
                action="HOLD",
                side=inp.side,
            ))
        else:
            flexible_inputs.append(inp)
    
    # Calculate remaining gross budget after fixed allocations
    fixed_gross = sum(
        current_book.get(r.symbol, {}).get("notional", 0.0)
        for r in fixed_results
    )
    remaining_gross = max(0.0, limits.max_gross_notional - fixed_gross)
    
    if not flexible_inputs or remaining_gross <= 0:
        # No budget left for new positions
        zero_results = [
            SizingResult(symbol=inp.symbol, target_notional=0.0, action=inp.action, side=inp.side)
            for inp in flexible_inputs
        ]
        return fixed_results + zero_results
    
    # Proportional allocation by candidate_score
    total_score = sum(inp.candidate_score for inp in flexible_inputs)
    if total_score <= 0:
        # Equal weight fallback
        weight_per = remaining_gross / len(flexible_inputs)
        flexible_results = [
            SizingResult(
                symbol=inp.symbol,
                target_notional=min(weight_per, limits.max_symbol_notional),
                action=inp.action,
                side=inp.side,
            )
            for inp in flexible_inputs
        ]
    else:
        flexible_results = []
        for inp in flexible_inputs:
            weight = inp.candidate_score / total_score
            target = weight * remaining_gross
            # Cap at per-symbol limit
            target = min(target, limits.max_symbol_notional)
            # Also cap at position_weight * equity
            target = min(target, limits.max_position_weight * equity)
            flexible_results.append(SizingResult(
                symbol=inp.symbol,
                target_notional=target,
                action=inp.action,
                side=inp.side,
            ))
    
    # If sum exceeds remaining_gross (due to caps), scale down proportionally
    flex_gross = sum(r.target_notional for r in flexible_results)
    if flex_gross > remaining_gross and flex_gross > 0:
        scale = remaining_gross / flex_gross
        flexible_results = [
            SizingResult(
                symbol=r.symbol,
                target_notional=r.target_notional * scale,
                action=r.action,
                side=r.side,
            )
            for r in flexible_results
        ]
    
    return fixed_results + flexible_results