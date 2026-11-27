"""Tests for the portfolio-level position sizer.

The sizer allocates gross notional across symbols proportionally by candidate score,
respecting per-symbol cap and total gross cap. Paper-mode only — no live venue.
"""
import pytest

from best_signal.portfolio_sizer import (
    SizingInput,
    SizingResult,
    compute_target_notionals,
)
from best_signal.position import RiskLimits


class TestPortfolioSizer:
    def test_proportional_allocation_two_symbols(self):
        """Two symbols with 60/40 weights, max_gross=20k → 12k/8k."""
        inputs = [
            SizingInput("BTCUSDT", 1, "OPEN", 0.0, candidate_score=0.6),
            SizingInput("ETHUSDT", 1, "OPEN", 0.0, candidate_score=0.4),
        ]
        # max_symbol_notional=15k allows 12k; equity=20k with weight=1.0 allows 20k
        limits = RiskLimits(max_gross_notional=20_000.0, max_symbol_notional=15_000.0, max_position_weight=1.0)
        results = compute_target_notionals(inputs, 20_000.0, limits, {})

        assert len(results) == 2
        btc = next(r for r in results if r.symbol == "BTCUSDT")
        eth = next(r for r in results if r.symbol == "ETHUSDT")
        assert btc.target_notional == pytest.approx(12_000.0)
        assert eth.target_notional == pytest.approx(8_000.0)

    def test_scales_down_when_demand_exceeds_gross_cap(self):
        """Three symbols want 10k each, max_gross=20k → 6.67k each."""
        inputs = [
            SizingInput("BTCUSDT", 1, "OPEN", 0.0, candidate_score=1.0),
            SizingInput("ETHUSDT", 1, "OPEN", 0.0, candidate_score=1.0),
            SizingInput("SOLUSDT", 1, "OPEN", 0.0, candidate_score=1.0),
        ]
        limits = RiskLimits(max_gross_notional=20_000.0, max_symbol_notional=10_000.0)
        results = compute_target_notionals(inputs, 10_000.0, limits, {})

        for r in results:
            assert r.target_notional == pytest.approx(20_000.0 / 3)

    def test_respects_symbol_cap_even_if_weight_allows_more(self):
        """Weight would give 15k but max_symbol=10k → 10k."""
        inputs = [
            SizingInput("BTCUSDT", 1, "OPEN", 0.0, candidate_score=0.75),
            SizingInput("ETHUSDT", 1, "OPEN", 0.0, candidate_score=0.25),
        ]
        limits = RiskLimits(max_gross_notional=20_000.0, max_symbol_notional=10_000.0)
        results = compute_target_notionals(inputs, 10_000.0, limits, {})

        btc = next(r for r in results if r.symbol == "BTCUSDT")
        assert btc.target_notional == 10_000.0  # capped at max_symbol

    def test_hold_preserves_current_notional(self):
        """HOLD keeps exact current notional, no resize."""
        inputs = [
            SizingInput("BTCUSDT", 1, "HOLD", 6_000.0, candidate_score=1.0),
            SizingInput("ETHUSDT", 1, "OPEN", 0.0, candidate_score=1.0),
        ]
        # max_symbol_notional=15k allows 14k for ETH; equity=20k with weight=1.0 allows 20k
        limits = RiskLimits(max_gross_notional=20_000.0, max_symbol_notional=15_000.0, max_position_weight=1.0)
        current_book = {"BTCUSDT": {"side": 1, "notional": 6_000.0}}
        results = compute_target_notionals(inputs, 20_000.0, limits, current_book)

        btc = next(r for r in results if r.symbol == "BTCUSDT")
        eth = next(r for r in results if r.symbol == "ETHUSDT")
        assert btc.target_notional == 6_000.0  # preserved
        assert eth.target_notional == pytest.approx(14_000.0)  # remaining gross

    def test_close_returns_zero_notional(self):
        """CLOSE returns 0 notional regardless of score."""
        inputs = [
            SizingInput("BTCUSDT", 1, "CLOSE", 10_000.0, candidate_score=1.0),
        ]
        limits = RiskLimits(max_gross_notional=20_000.0)
        current_book = {"BTCUSDT": {"side": 1, "notional": 10_000.0}}
        results = compute_target_notionals(inputs, 10_000.0, limits, current_book)

        assert results[0].target_notional == 0.0
        assert results[0].action == "CLOSE"

    def test_flip_treated_as_close_plus_open(self):
        """FLIP = CLOSE current + OPEN opposite with same weight."""
        inputs = [
            SizingInput("BTCUSDT", -1, "FLIP", 10_000.0, candidate_score=1.0),
        ]
        limits = RiskLimits(max_gross_notional=20_000.0, max_symbol_notional=10_000.0)
        current_book = {"BTCUSDT": {"side": 1, "notional": 10_000.0}}
        results = compute_target_notionals(inputs, 10_000.0, limits, current_book)

        assert results[0].target_notional == 10_000.0
        assert results[0].side == -1
        assert results[0].action == "FLIP"

    def test_no_trade_returns_zero(self):
        """NO_TRADE returns 0 notional."""
        inputs = [
            SizingInput("BTCUSDT", 0, "NO_TRADE", 0.0, candidate_score=1.0),
        ]
        limits = RiskLimits(max_gross_notional=20_000.0)
        results = compute_target_notionals(inputs, 10_000.0, limits, {})

        assert results[0].target_notional == 0.0
        assert results[0].action == "NO_TRADE"

    def test_zero_candidate_score_equal_weight(self):
        """Zero/negative candidate_score → equal weight fallback."""
        inputs = [
            SizingInput("BTCUSDT", 1, "OPEN", 0.0, candidate_score=0.0),
            SizingInput("ETHUSDT", 1, "OPEN", 0.0, candidate_score=-0.5),
            SizingInput("SOLUSDT", 1, "OPEN", 0.0, candidate_score=0.0),
        ]
        limits = RiskLimits(max_gross_notional=30_000.0, max_symbol_notional=15_000.0)
        results = compute_target_notionals(inputs, 10_000.0, limits, {})

        assert len(results) == 3
        for r in results:
            assert r.target_notional == pytest.approx(10_000.0)  # 30k / 3 = 10k each

    def test_mixed_hold_and_open_respects_gross(self):
        """HOLD preserves notional, OPEN gets remaining gross within cap."""
        inputs = [
            SizingInput("BTCUSDT", 1, "HOLD", 8_000.0, candidate_score=1.0),
            SizingInput("ETHUSDT", 1, "OPEN", 0.0, candidate_score=1.0),
            SizingInput("SOLUSDT", 1, "OPEN", 0.0, candidate_score=1.0),
        ]
        # BTC HOLD takes 8k, remaining 12k for 2 OPEN symbols → 6k each (capped by max_symbol=10k)
        limits = RiskLimits(max_gross_notional=20_000.0, max_symbol_notional=10_000.0)
        current_book = {"BTCUSDT": {"side": 1, "notional": 8_000.0}}
        results = compute_target_notionals(inputs, 10_000.0, limits, current_book)

        btc = next(r for r in results if r.symbol == "BTCUSDT")
        eth = next(r for r in results if r.symbol == "ETHUSDT")
        sol = next(r for r in results if r.symbol == "SOLUSDT")

        assert btc.target_notional == 8_000.0  # HOLD preserved
        assert eth.target_notional == pytest.approx(6_000.0)  # (20k - 8k) / 2
        assert sol.target_notional == pytest.approx(6_000.0)

    def test_empty_inputs_returns_empty(self):
        """Empty input list returns empty results."""
        inputs = []
        limits = RiskLimits(max_gross_notional=20_000.0)
        results = compute_target_notionals(inputs, 10_000.0, limits, {})

        assert results == []