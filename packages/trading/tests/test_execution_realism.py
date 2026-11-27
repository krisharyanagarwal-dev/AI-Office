"""Tests for execution realism in the paper venue: slippage, latency, partial fills.

Hand-derived numbers (notional 10,000 at price 100, slippage_bps=10):

  * quantity per leg            = 10,000 / 100 = 100 units
  * buy fill price              = 100 * (1 + 10/10000) = 100.10
  * sell fill price             = 100 * (1 - 10/10000) = 99.90
  * buy commission              = 100 * 100.10 * 0.0005 = 5.005
  * sell commission             = 100 * 99.90 * 0.0005 = 4.995
  * total fees                  = 10.00
  * cash after buy leg          = 11,110 - (100 * 100.10 + 5.005) = 1,094.995
  * cash after sell leg         = 1,094.995 + (100 * 99.90 - 4.995) = 11,080.0
"""
import time

import pytest

from best_signal.execution import (
    ACTION_OPEN,
    CarryPaperBroker,
    ExecutionRealismConfig,
    build_paper_venue,
    run_paper_execution,
)
from risk import RiskGovernor
from risk import RiskLimits as GovernorLimits

EQUITY = 10_000.0
NOTIONAL = 10_000.0
PRICE = 100.0


def _governor(**limits) -> RiskGovernor:
    return RiskGovernor(GovernorLimits(**limits))


def _broker_with(slippage_bps=0.0, latency_ms=0.0, partial_fill_enabled=False,
                 partial_fill_fraction=0.5):
    realism = ExecutionRealismConfig(
        slippage_bps=slippage_bps,
        latency_ms=latency_ms,
        partial_fill_enabled=partial_fill_enabled,
        partial_fill_fraction=partial_fill_fraction,
    )
    _, broker = build_paper_venue(EQUITY, realism=realism)
    return broker


class TestExecutionRealismConfig:
    def test_defaults_preserve_current_behavior(self):
        config = ExecutionRealismConfig()
        assert config.slippage_bps == 0.0
        assert config.latency_ms == 0.0
        assert config.partial_fill_enabled is False
        assert config.partial_fill_fraction == 0.5

    def test_config_stored_on_broker(self):
        broker = _broker_with(slippage_bps=10.0, latency_ms=5.0,
                              partial_fill_enabled=True, partial_fill_fraction=0.25)
        assert broker.slippage_bps == 10.0
        assert broker.latency_ms == 5.0
        assert broker.partial_fill_enabled is True
        assert broker.partial_fill_fraction == 0.25


class TestSlippage:
    def test_buy_fills_worse_higher_price_with_slippage(self):
        broker = _broker_with(slippage_bps=10.0)
        engine, _ = build_paper_venue(EQUITY)
        # Replace broker with slippage-configured one on the engine.
        engine.brokers["paper"] = broker
        engine.default_broker = "paper"

        from best_signal.execution import _submit_leg, legs_for_target
        legs = legs_for_target("BTCUSDT", 1, NOTIONAL, PRICE)
        spot, perp = legs
        _submit_leg(engine, spot)
        _submit_leg(engine, perp)

        assert broker.positions["BTCUSDT"].quantity == 100.0
        assert broker.positions["BTCUSDT"].avg_entry_price == pytest.approx(100.10)
        assert broker.positions["BTCUSDT_PERP"].quantity == -100.0
        assert broker.positions["BTCUSDT_PERP"].avg_entry_price == pytest.approx(99.90)
        assert broker.balances["USDT"] == pytest.approx(11_080.0)
        assert broker.fees_total == pytest.approx(10.0)

    def test_zero_slippage_matches_existing_behavior(self):
        broker = _broker_with(slippage_bps=0.0)
        engine, _ = build_paper_venue(EQUITY)
        engine.brokers["paper"] = broker
        engine.default_broker = "paper"

        from best_signal.execution import _submit_leg, legs_for_target
        legs = legs_for_target("BTCUSDT", 1, NOTIONAL, PRICE)
        spot, perp = legs
        _submit_leg(engine, spot)
        _submit_leg(engine, perp)

        assert broker.positions["BTCUSDT"].avg_entry_price == PRICE
        assert broker.positions["BTCUSDT_PERP"].avg_entry_price == PRICE
        assert broker.balances["USDT"] == 11_100.0
        assert broker.fees_total == 10.0


class TestPartialFill:
    def test_partial_fill_rolls_back_and_leaves_book_flat(self):
        broker = _broker_with(partial_fill_enabled=True, partial_fill_fraction=0.5)
        engine, _ = build_paper_venue(EQUITY)
        engine.brokers["paper"] = broker
        engine.default_broker = "paper"

        from best_signal.execution import run_paper_execution
        result = run_paper_execution(
            engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY,
            action=ACTION_OPEN,
        )

        assert result.filled is False
        assert result.action == "ROLLED_BACK"
        assert result.partial is True
        assert "partial" in result.reason or "leg_rejected" in result.reason
        # Book restored to flat: no open exposure left behind.
        assert broker.positions["BTCUSDT"].quantity == 0.0
        assert broker.positions["BTCUSDT_PERP"].quantity == 0.0
        assert broker.margin_used.get("BTCUSDT_PERP", 0.0) == 0.0

    def test_partial_fill_fraction_applies_to_fill_quantity(self):
        broker = _broker_with(partial_fill_enabled=True, partial_fill_fraction=0.25)
        engine, _ = build_paper_venue(EQUITY)
        engine.brokers["paper"] = broker
        engine.default_broker = "paper"

        from best_signal.execution import _submit_leg, legs_for_target
        legs = legs_for_target("BTCUSDT", 1, NOTIONAL, PRICE)
        spot, _ = legs
        _submit_leg(engine, spot)

        assert broker.positions["BTCUSDT"].quantity == pytest.approx(25.0)


class TestLatency:
    def test_per_leg_latency_sleep_is_applied(self):
        """Each market order sleeps at least the configured latency_ms.

        Two legs are submitted serially, so a run with 50 ms of latency per
        leg must take materially longer than the same run with zero latency.
        The base broker's own fixed sleep cancels out in the difference.
        """

        def run_with(latency_ms: float) -> float:
            broker = _broker_with(latency_ms=latency_ms)
            engine, _ = build_paper_venue(EQUITY)
            engine.brokers["paper"] = broker
            engine.default_broker = "paper"
            start = time.perf_counter()
            run_paper_execution(
                engine,
                broker,
                "BTCUSDT",
                1,
                NOTIONAL,
                PRICE,
                EQUITY,
                action=ACTION_OPEN,
            )
            return time.perf_counter() - start

        fast = run_with(0.0)
        slow = run_with(50.0)
        assert slow - fast >= 0.08  # 2 legs * 50 ms, allowing for scheduling jitter

    def test_latency_run_still_fills_both_legs(self):
        broker = _broker_with(latency_ms=20.0)
        engine, _ = build_paper_venue(EQUITY)
        engine.brokers["paper"] = broker
        engine.default_broker = "paper"

        result = run_paper_execution(
            engine,
            broker,
            "BTCUSDT",
            1,
            NOTIONAL,
            PRICE,
            EQUITY,
            action=ACTION_OPEN,
        )

        assert result.filled is True
        assert result.partial is False
        assert result.action == ACTION_OPEN
        assert broker.positions["BTCUSDT"].quantity == 100.0
        assert broker.positions["BTCUSDT_PERP"].quantity == -100.0
