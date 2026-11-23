"""Carry rules for the best-signal bot.

Every rule is causal: ``step`` may only use the prints it is handed, and the
harness always hands it the prefix up to and including the current print.
Rules return a side, where ``+1`` is long spot / short perp (collects positive
funding), ``-1`` is short spot / long perp (collects negative funding) and
``0`` is flat.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from best_signal.funding import FundingPrint, annualized_funding

HOUR_MS = 3_600_000


@dataclass
class RuleState:
    side: int = 0
    adverse_since_ms: int | None = None


@dataclass(frozen=True)
class RuleDecision:
    side: int
    reason: str
    trailing_ann: float = 0.0


class AlwaysOnCarry:
    """Hold the funding-receiving side unconditionally; never flip.

    This is the policy production already runs: the archived audit found the
    flip rules had no timing skill, so the simplest zero-fee book won.
    """

    name = "always_on_carry"
    description = "Long spot / short perp, never flips, collects funding every print."

    def new_state(self) -> RuleState:
        return RuleState(side=1)

    def step(self, prints: Sequence[FundingPrint], state: RuleState) -> RuleDecision:
        state.side = 1
        return RuleDecision(side=1, reason="always_collect")


class RegimeFilteredCarry:
    """Carry with a trailing-funding regime filter and hysteresis.

    Stands down when the trailing annualized funding falls below
    ``stand_down_ann`` and only re-enters once it clears ``reenter_ann``.
    The gap between the two thresholds is what stops the book from churning
    around a noisy zero line.
    """

    name = "regime_filtered_carry"

    def __init__(
        self,
        lookback_prints: int = 30,
        stand_down_ann: float = 0.0,
        reenter_ann: float = 0.03,
    ):
        self.lookback_prints = int(lookback_prints)
        self.stand_down_ann = float(stand_down_ann)
        self.reenter_ann = float(reenter_ann)

    @property
    def description(self) -> str:
        return (
            f"Carry book filtered on trailing {self.lookback_prints}-print "
            f"annualized funding: stand down below {self.stand_down_ann:.3f}, "
            f"re-enter above {self.reenter_ann:.3f}."
        )

    def new_state(self) -> RuleState:
        return RuleState()

    def step(self, prints: Sequence[FundingPrint], state: RuleState) -> RuleDecision:
        window = list(prints[-self.lookback_prints:]) if self.lookback_prints else []
        trailing_ann = annualized_funding(window) if window else 0.0

        if state.side != 0:
            if trailing_ann < self.stand_down_ann:
                state.side = 0
                return RuleDecision(0, "stand_down_negative_funding", trailing_ann)
            return RuleDecision(state.side, "hold_carry", trailing_ann)

        if trailing_ann >= self.reenter_ann:
            state.side = 1
            return RuleDecision(1, "reenter_carry", trailing_ann)
        return RuleDecision(0, "flat_waiting_reentry", trailing_ann)


class PersistenceFlipCarry:
    """The archived persistence flip rule, kept as a comparison baseline.

    Flips to the funding-receiving side only after ``persistence_hours`` of
    continuous adverse funding whose magnitude clears ``threshold``.
    """

    name = "persistence_flip_carry"

    def __init__(self, persistence_hours: float = 48.0, threshold: float = 5e-05):
        self.persistence_hours = float(persistence_hours)
        self.threshold = float(threshold)

    @property
    def description(self) -> str:
        return (
            f"Carry book that flips after {self.persistence_hours:g}h of continuous "
            f"adverse funding with |rate| >= {self.threshold:.1e}."
        )

    def new_state(self) -> RuleState:
        return RuleState(side=1)

    def step(self, prints: Sequence[FundingPrint], state: RuleState) -> RuleDecision:
        if not prints:
            return RuleDecision(state.side, "no_history", 0.0)
        current = prints[-1]
        if current.rate > 0:
            want = 1
        elif current.rate < 0:
            want = -1
        else:
            want = state.side

        if state.side and state.side != want:
            if state.adverse_since_ms is None:
                state.adverse_since_ms = current.ts_ms
                return RuleDecision(state.side, "adverse_started", 0.0)
            elapsed_hours = (current.ts_ms - state.adverse_since_ms) / HOUR_MS
            if elapsed_hours >= self.persistence_hours and abs(current.rate) >= self.threshold:
                state.side = want
                state.adverse_since_ms = None
                return RuleDecision(state.side, "flip_persistence", 0.0)
            return RuleDecision(state.side, "hold_adverse_within_window", 0.0)

        state.adverse_since_ms = None
        return RuleDecision(state.side, "hold_carry", 0.0)
