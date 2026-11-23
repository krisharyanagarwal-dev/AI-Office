"""
Tests for the best-signal rule layer.

Every rule must be causal: the decision for print i may only use prints
0..i. These tests pin that property, because a rule that peeks one print
ahead would manufacture out-of-sample edge that cannot be traded.
"""
import pytest

from best_signal.funding import FundingPrint, PERIODS_PER_YEAR
from best_signal.rules import (
    AlwaysOnCarry,
    PersistenceFlipCarry,
    RegimeFilteredCarry,
)


def make_prints(rates, start_ms=0, step_ms=8 * 3600 * 1000):
    return [
        FundingPrint(ts_ms=start_ms + index * step_ms, rate=rate)
        for index, rate in enumerate(rates)
    ]


class TestAlwaysOnCarry:
    def test_always_collects_positive_funding(self):
        rule = AlwaysOnCarry()
        state = rule.new_state()
        decision = rule.step(make_prints([0.001]), state)
        assert decision.side == 1
        assert decision.reason == "always_collect"

    def test_holds_through_negative_funding(self):
        rule = AlwaysOnCarry()
        state = rule.new_state()
        rule.step(make_prints([-0.001, -0.002]), state)
        decision = rule.step(make_prints([-0.001, -0.002, -0.003]), state)
        assert decision.side == 1

    def test_never_flips(self):
        rule = AlwaysOnCarry()
        state = rule.new_state()
        sides = []
        for index in range(10):
            rate = 0.001 if index % 2 == 0 else -0.001
            sides.append(rule.step(make_prints([rate] * (index + 1)), state).side)
        assert set(sides) == {1}


class TestRegimeFilteredCarry:
    def test_starts_in_carry_when_trailing_funding_positive(self):
        rule = RegimeFilteredCarry(lookback_prints=2)
        state = rule.new_state()
        decision = rule.step(make_prints([0.001, 0.001]), state)
        assert decision.side == 1

    def test_stands_down_when_trailing_funding_negative(self):
        rule = RegimeFilteredCarry(lookback_prints=2)
        state = rule.new_state()
        rule.step(make_prints([0.001, 0.001]), state)
        decision = rule.step(make_prints([0.001, 0.001, -0.001, -0.001]), state)
        assert decision.side == 0
        assert decision.reason == "stand_down_negative_funding"

    def test_reentry_requires_higher_threshold_than_exit(self):
        rule = RegimeFilteredCarry(lookback_prints=1, stand_down_ann=0.0, reenter_ann=0.03)
        state = rule.new_state()
        weak_positive = 0.01 / PERIODS_PER_YEAR
        rule.step(make_prints([-0.001]), state)
        assert rule.step(make_prints([-0.001, weak_positive]), state).side == 0

    def test_reenters_when_trailing_funding_clears_reentry_threshold(self):
        rule = RegimeFilteredCarry(lookback_prints=1, stand_down_ann=0.0, reenter_ann=0.03)
        state = rule.new_state()
        rule.step(make_prints([-0.001]), state)
        decision = rule.step(make_prints([-0.001, 0.001]), state)
        assert decision.side == 1
        assert decision.reason == "reenter_carry"

    def test_trailing_window_is_bounded(self):
        rule = RegimeFilteredCarry(lookback_prints=3)
        state = rule.new_state()
        rule.step(make_prints([0.001] * 10), state)
        decision = rule.step(make_prints([0.001] * 10 + [-0.001]), state)
        assert decision.trailing_ann == pytest.approx(
            (0.001 + 0.001 - 0.001) / 3 * PERIODS_PER_YEAR
        )


class TestCausality:
    def test_regime_decision_depends_only_on_the_prints_supplied(self):
        rule = RegimeFilteredCarry(lookback_prints=3)
        prefix = make_prints([0.001, 0.001, 0.001])
        first = rule.step(prefix, rule.new_state())
        second = rule.step(prefix, rule.new_state())
        assert first.side == second.side
        assert first.trailing_ann == second.trailing_ann


class TestPersistenceFlipCarry:
    """48h of continuous adverse funding at an 8h cadence completes on the
    seventh adverse print (the first adverse print starts the clock)."""

    def test_does_not_flip_before_persistence_window(self):
        rule = PersistenceFlipCarry(persistence_hours=48.0, threshold=5e-05)
        state = rule.new_state()
        for index in range(6):
            decision = rule.step(make_prints([-0.001] * (index + 1)), state)
        assert decision.side == 1
        assert decision.reason == "hold_adverse_within_window"

    def test_flips_after_persistence_window_with_threshold_met(self):
        rule = PersistenceFlipCarry(persistence_hours=48.0, threshold=5e-05)
        state = rule.new_state()
        for index in range(6):
            rule.step(make_prints([-0.001] * (index + 1)), state)
        decision = rule.step(make_prints([-0.001] * 7), state)
        assert decision.side == -1
        assert decision.reason == "flip_persistence"

    def test_does_not_flip_when_rate_below_threshold(self):
        rule = PersistenceFlipCarry(persistence_hours=48.0, threshold=5e-05)
        state = rule.new_state()
        tiny = 1e-06
        for index in range(7):
            decision = rule.step(make_prints([-tiny] * (index + 1)), state)
        assert decision.side == 1

    def test_adverse_timer_resets_when_funding_returns(self):
        rule = PersistenceFlipCarry(persistence_hours=48.0, threshold=5e-05)
        state = rule.new_state()
        for index in range(6):
            rule.step(make_prints([-0.001] * (index + 1)), state)
        rule.step(make_prints([-0.001] * 6 + [0.001]), state)
        decision = rule.step(make_prints([-0.001] * 6 + [0.001, -0.001]), state)
        assert decision.side == 1

    def test_empty_history_keeps_the_current_side(self):
        rule = PersistenceFlipCarry(persistence_hours=48.0, threshold=5e-05)
        state = rule.new_state()
        decision = rule.step([], state)
        assert decision.side == 1
        assert decision.reason == "no_history"
