"""Paper-only position emitter for the best-signal bot.

The emitter never places an order and never holds an exchange credential. It
turns the accepted candidate's causal rule decision into a paper target that a
risk-aware execution layer may consume, and it stands down explicitly whenever
a gate fails instead of quietly resizing a position.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import pandas as pd

from best_signal.evidence import CandidateRecord, select_tradable
from best_signal.funding import FundingPrint
from best_signal.rules import (
    AlwaysOnCarry,
    PersistenceFlipCarry,
    RegimeFilteredCarry,
)

ACTION_OPEN = "OPEN"
ACTION_HOLD = "HOLD"
ACTION_FLIP = "FLIP"
ACTION_CLOSE = "CLOSE"
ACTION_NO_TRADE = "NO_TRADE"

DEFAULT_RULES = {
    "always_on_carry": AlwaysOnCarry,
    "regime_filtered_carry": RegimeFilteredCarry,
    "persistence_flip_carry": PersistenceFlipCarry,
}


@dataclass(frozen=True)
class RiskLimits:
    """Caps the emitter may never exceed."""

    max_symbol_notional: float = 10_000.0
    max_gross_notional: float = 20_000.0
    max_position_weight: float = 1.0
    max_symbols: int = 3
    max_daily_loss_pct: float = 0.03
    kill_switch: bool = False


@dataclass(frozen=True)
class PaperPosition:
    """A paper target. Never an order."""

    symbol: str
    action: str
    side: int
    notional: float
    reason: str
    candidate: str
    mode: str = "PAPER"
    live: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "side": self.side,
            "notional": self.notional,
            "reason": self.reason,
            "candidate": self.candidate,
            "mode": self.mode,
            "live": self.live,
        }


def _stand_down(symbol: str, reason: str, candidate: str = "") -> PaperPosition:
    return PaperPosition(
        symbol=symbol,
        action=ACTION_NO_TRADE,
        side=0,
        notional=0.0,
        reason=reason,
        candidate=candidate,
    )


def build_paper_position(
    symbol: str,
    prints: Sequence[FundingPrint],
    records: Sequence[CandidateRecord],
    limits: RiskLimits,
    equity: float = 10_000.0,
    current_side: int = 0,
    current_notional: float = 0.0,
    gross_notional: float = 0.0,
    open_symbols: int = 0,
    daily_loss_pct: float = 0.0,
    rules: dict | None = None,
    returns: pd.Series | None = None,
) -> PaperPosition:
    """Emit the paper target for ``symbol`` or an explicit stand-down."""
    if limits.kill_switch:
        return _stand_down(symbol, "kill_switch")

    if daily_loss_pct <= -abs(limits.max_daily_loss_pct):
        return _stand_down(symbol, "daily_loss_limit")

    candidate = select_tradable(records)
    if candidate is None:
        return _stand_down(symbol, "no_candidate")

    if not prints:
        return _stand_down(symbol, "no_history", candidate.name)

    rule_map = DEFAULT_RULES if rules is None else rules
    rule_factory = rule_map.get(candidate.rule_key)
    if rule_factory is None:
        return _stand_down(symbol, "no_rule_for_candidate", candidate.name)

    rule = rule_factory()
    decision = rule.step(prints, rule.new_state(), returns=returns)
    side = int(decision.side)
    if side not in (-1, 0, 1):
        return _stand_down(symbol, "invalid_side", candidate.name)

    if side == 0:
        action = ACTION_CLOSE if current_side != 0 else ACTION_NO_TRADE
        return PaperPosition(
            symbol=symbol,
            action=action,
            side=0,
            notional=0.0,
            reason=decision.reason,
            candidate=candidate.name,
        )

    if current_side == 0 and open_symbols >= limits.max_symbols:
        return _stand_down(symbol, "max_symbols", candidate.name)

    committed_elsewhere = max(0.0, gross_notional - current_notional)
    remaining_gross = max(0.0, limits.max_gross_notional - committed_elsewhere)
    cap = min(
        limits.max_symbol_notional,
        limits.max_position_weight * equity,
        remaining_gross,
    )
    if cap <= 0:
        return _stand_down(symbol, "risk_cap_exhausted", candidate.name)

    if current_side == 0:
        action = ACTION_OPEN
    elif current_side == side:
        action = ACTION_HOLD
        # HOLD: keep the existing position size exactly; risk caps only gate new exposure
        notional = float(current_notional)
        return PaperPosition(
            symbol=symbol,
            action=action,
            side=side,
            notional=notional,
            reason=decision.reason,
            candidate=candidate.name,
        )
    else:
        action = ACTION_FLIP

    return PaperPosition(
        symbol=symbol,
        action=action,
        side=side,
        notional=float(cap),
        reason=decision.reason,
        candidate=candidate.name,
    )
