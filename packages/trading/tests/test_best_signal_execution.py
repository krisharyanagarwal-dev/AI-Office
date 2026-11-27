"""Tests for the carry book's paper venue.

The venue is the only place where the bot's paper target becomes a position.
It must never be able to reach a live venue, it must charge the research
model's 5 bps per leg, and it must measure a delta-flat book by its true
gross.

Hand-derived numbers used below (notional 10,000 at price 100):

  * quantity per leg            = 10,000 / 100 = 100 units
  * fee per leg                 = 100 * 100 * 0.0005 = 5.00
  * fees to open a carry        = 2 legs * 5.00 = 10.00
  * venue cash to build         = 10,000 * (1 + 0.10) * 1.01 = 11,110.00
  * cash after opening a carry  = 11,110 - 10,000 - 5 + 10,000 - 5 = 11,100.00
  * margin reserved on the perp = 0.10 * 10,000 = 1,000.00
  * free cash after opening     = 11,100 - 1,000 = 10,100.00
  * cash after closing          = 11,110 - 4 legs * 5.00 = 11,090.00
"""
import json
import pandas as pd
import pytest
import time

from best_signal.execution import (
    CarryPaperBroker,
    ExecutionResult,
    LiveVenueRefused,
    approve_target,
    build_paper_venue,
    legs_for_target,
    load_price_at,
    restore_venue,
    risk_limits_for,
    run_paper_execution,
    venue_snapshot,
)
from best_signal.fill_journal import FillJournal
from best_signal.position import RiskLimits
from risk import LimitStatus, RiskGovernor
from risk import RiskLimits as GovernorLimits

EQUITY = 10_000.0
NOTIONAL = 10_000.0
PRICE = 100.0


def _governor(**limits) -> RiskGovernor:
    return RiskGovernor(GovernorLimits(**limits))


class TestLegs:
    def test_a_long_target_is_a_spot_buy_paired_with_a_perp_sell(self):
        """Catches: the venue dropping one leg of the delta-flat carry."""
        legs = legs_for_target("BTCUSDT", 1, NOTIONAL, PRICE)
        assert len(legs) == 2
        spot, perp = legs
        assert (spot.symbol, spot.market, spot.side) == ("BTCUSDT", "spot", "buy")
        assert (perp.symbol, perp.market, perp.side) == ("BTCUSDT_PERP", "perp", "sell")
        assert spot.quantity == 100.0
        assert spot.price == PRICE
        assert spot.notional == NOTIONAL
        assert perp.quantity == 100.0
        assert perp.notional == NOTIONAL

    def test_a_short_target_is_a_spot_sell_paired_with_a_perp_buy(self):
        """Catches: a sign flip on one leg that would make the book directional."""
        legs = legs_for_target("BTCUSDT", -1, NOTIONAL, PRICE)
        spot, perp = legs
        assert (spot.side, perp.side) == ("sell", "buy")
        assert spot.quantity == 100.0
        assert perp.quantity == 100.0


class TestPaperVenue:
    def test_opening_a_carry_fills_both_legs_at_five_bps(self):
        """Catches: the venue charging the shared broker's 10 bps default."""
        engine, broker = build_paper_venue(EQUITY)
        assert broker.paper_trading is True
        assert broker.balances["USDT"] == 11_110.0

        result = run_paper_execution(
            engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY
        )

        assert result.filled is True
        assert result.action == "OPEN"
        assert result.fees == 10.0
        assert result.mode == "PAPER"
        assert result.live is False
        assert len(result.legs) == 2
        assert broker.balances["USDT"] == 11_100.0
        assert broker.margin_used["BTCUSDT_PERP"] == 1_000.0
        assert broker.free_cash == 10_100.0
        assert broker.positions["BTCUSDT"].quantity == 100.0
        assert broker.positions["BTCUSDT_PERP"].quantity == -100.0

    def test_a_non_paper_venue_is_refused_before_any_order_is_sent(self):
        """Catches: the bot submitting an order to a venue that is not paper."""
        engine, broker = build_paper_venue(EQUITY)
        broker.paper_trading = False

        with pytest.raises(LiveVenueRefused):
            run_paper_execution(
                engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY
            )

        assert broker.orders == {}
        assert broker.balances["USDT"] == 11_110.0

    def test_a_rejected_second_leg_rolls_the_filled_leg_back(self):
        """Catches: a half-open carry left on the venue after a collateral failure."""
        engine, broker = build_paper_venue(EQUITY)
        broker.margin_ratio = 5.0

        result = run_paper_execution(
            engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY
        )

        assert result.action == "ROLLED_BACK"
        assert result.filled is False
        assert result.fees == 10.0
        assert broker.balances["USDT"] == 11_100.0
        assert broker.positions["BTCUSDT"].quantity == 0.0
        assert broker.positions["BTCUSDT_PERP"].quantity == 0.0

    def test_holding_a_carry_charges_no_new_fees(self):
        """Catches: the venue charging a round trip on every scheduled run."""
        engine, broker = build_paper_venue(EQUITY)
        run_paper_execution(engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY)
        cash_after_open = broker.balances["USDT"]

        result = run_paper_execution(
            engine,
            broker,
            "BTCUSDT",
            1,
            NOTIONAL,
            PRICE,
            EQUITY,
            action="HOLD",
            current_side=1,
            current_notional=NOTIONAL,
        )

        assert result.action == "HOLD"
        assert result.filled is True
        assert result.legs == ()
        assert result.fees == 0.0
        assert broker.balances["USDT"] == cash_after_open

    def test_closing_a_carry_flattens_both_legs_and_releases_the_margin(self):
        """Catches: a close that leaves the perp short open on the venue."""
        engine, broker = build_paper_venue(EQUITY)
        run_paper_execution(engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY)

        result = run_paper_execution(
            engine,
            broker,
            "BTCUSDT",
            0,
            NOTIONAL,
            PRICE,
            EQUITY,
            action="CLOSE",
            current_side=1,
            current_notional=NOTIONAL,
        )

        assert result.action == "CLOSE"
        assert result.filled is True
        assert result.fees == 10.0
        assert broker.balances["USDT"] == 11_090.0
        assert broker.margin_used.get("BTCUSDT_PERP", 0.0) == 0.0
        assert broker.positions["BTCUSDT"].quantity == 0.0
        assert broker.positions["BTCUSDT_PERP"].quantity == 0.0

    def test_flipping_a_carry_closes_both_legs_and_opens_the_new_pair(self):
        """Catches: a flip that reopens one leg without closing the other."""
        engine, broker = build_paper_venue(EQUITY)
        run_paper_execution(engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY)

        result = run_paper_execution(
            engine,
            broker,
            "BTCUSDT",
            -1,
            NOTIONAL,
            PRICE,
            EQUITY,
            action="FLIP",
            current_side=1,
            current_notional=NOTIONAL,
        )

        assert result.action == "FLIP"
        assert result.filled is True
        assert len(result.legs) == 4
        assert result.fees == 20.0
        assert broker.positions["BTCUSDT"].quantity == -100.0
        assert broker.positions["BTCUSDT_PERP"].quantity == 100.0
        assert broker.balances["USDT"] == 11_080.0

    def test_a_venue_snapshot_restores_cash_positions_and_margin(self):
        """Catches: a restarted run losing the venue's positions and collateral."""
        engine, broker = build_paper_venue(EQUITY)
        run_paper_execution(engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY)

        snapshot = venue_snapshot(broker)
        _, restored = build_paper_venue(EQUITY)
        restore_venue(restored, snapshot)

        assert restored.balances["USDT"] == broker.balances["USDT"]
        assert restored.positions["BTCUSDT"].quantity == 100.0
        assert restored.positions["BTCUSDT_PERP"].quantity == -100.0
        assert restored.margin_used["BTCUSDT_PERP"] == 1_000.0

    def test_fill_journal_captures_each_fill(self, tmp_path):
        """Each fill in a carry open writes a line to the fill journal."""
        journal_path = tmp_path / "fills.jsonl"
        journal = FillJournal(journal_path, enabled=True)

        engine, broker = build_paper_venue(EQUITY)
        # Attach journal to broker for access in _execute_market
        broker.fill_journal = journal

        result = run_paper_execution(
            engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY
        )

        assert result.filled is True
        assert result.action == "OPEN"

        # Journal should have 2 lines (spot buy + perp sell)
        lines = journal_path.read_text().strip().splitlines()
        assert len(lines) == 2

        for line in lines:
            payload = json.loads(line)
            assert payload["symbol"] in ("BTCUSDT", "BTCUSDT_PERP")
            assert payload["venue"] == "paper"
            assert payload["mode"] == "PAPER"
            assert "slippage_bps" in payload
            assert "latency_ms" in payload
            assert "partial_fill" in payload

    def test_execution_captures_bid_ask_spread_latency(self, tmp_path):
        """Execution records bid/ask/spread/latency per fill."""
        from best_signal.fill_journal import FillJournal
        from best_signal.telemetry import TelemetrySink
        from best_signal.execution import build_paper_venue, run_paper_execution
        from best_signal.position import RiskLimits
        from risk import RiskGovernor
        from risk import RiskLimits as GovernorLimits
        
        journal = FillJournal(tmp_path / "fills.jsonl", enabled=True)
        telemetry = TelemetrySink(tmp_path / "telemetry.jsonl", enabled=True)
        
        engine, broker = build_paper_venue(10_000.0, fill_journal=journal)
        # Attach telemetry to broker for access in _execute_market
        broker.telemetry = telemetry
        
        governor = RiskGovernor(risk_limits_for(RiskLimits(), 10_000.0))
        
        result = run_paper_execution(
            engine, broker, "BTCUSDT", 1, 10_000.0, 100.0, 10_000.0,
            governor=governor, action="OPEN"
        )
        
        assert result.filled is True
        # Read fills and verify bid/ask/spread recorded
        lines = (tmp_path / "fills.jsonl").read_text().strip().splitlines()
        for line in lines:
            payload = json.loads(line)
            assert "spread_bps" in payload
            assert "bid" in payload
            assert "ask" in payload
            assert payload["spread_bps"] >= 0.0
            assert payload["bid"] > 0
            assert payload["ask"] > 0
            assert "venue_latency_ms" in payload


class TestRiskApproval:
    def test_the_governor_measures_the_true_gross_of_a_delta_flat_book(self):
        """Catches: a signed-notional sum reading a carry book as zero exposure.
        
        Governor limits are now per-leg (Task 2: no 2x inflation). The test
        passes per-leg notional (10_000) which exceeds max_symbol_exposure_pct=0.5
        (50% of equity = 5_000 per-leg).
        """
        governor = _governor(
            min_confidence=0.0,
            max_notional_pct=1.0,
            max_symbol_exposure_pct=0.5,
            max_total_exposure_pct=4.0,
            max_open_positions=4,
            start_of_day_equity=EQUITY,
            high_water_mark=EQUITY,
        )

        approved, reason = approve_target(governor, "BTCUSDT", 10_000.0, EQUITY)

        assert approved is False
        assert "exposure" in reason
        assert governor.limits.positions == {}

    def test_an_approved_target_commits_the_projected_gross_book(self):
        """Catches: the governor approving without recording the new exposure.
        
        Governor limits are now per-leg (Task 2: no 2x inflation). The test
        passes per-leg notional (10_000) which fits within max_symbol_exposure_pct=1.0
        (100% of equity = 10_000 per-leg).
        """
        governor = _governor(
            min_confidence=0.0,
            max_notional_pct=1.0,
            max_symbol_exposure_pct=1.0,
            max_total_exposure_pct=4.0,
            max_open_positions=4,
            start_of_day_equity=EQUITY,
            high_water_mark=EQUITY,
        )

        approved, reason = approve_target(governor, "BTCUSDT", 10_000.0, EQUITY)

        assert approved is True
        assert reason is None
        assert governor.limits.positions["BTCUSDT"]["gross_notional"] == 10_000.0

    def test_the_bot_caps_map_onto_the_repo_governor_limits(self):
        """Catches: the governor's own defaults rejecting every carry target."""
        limits = risk_limits_for(RiskLimits(), equity=EQUITY)
        assert limits.min_confidence == 0.0
        assert limits.max_notional_abs == 10_000.0
        assert limits.max_notional_pct == 1.0
        assert limits.max_symbol_exposure_pct == 1.0
        assert limits.max_total_exposure_pct == 2.0
        assert limits.max_open_positions == 4
        assert limits.max_daily_loss_pct == 0.03

    def test_governor_limits_match_bot_caps(self):
        """Governor limits equal bot caps directly (no 2x inflation)."""
        bot_limits = RiskLimits(
            max_symbol_notional=15_000.0,
            max_gross_notional=30_000.0,
            max_symbols=5,
            max_daily_loss_pct=0.02,
        )
        equity = 25_000.0
        limits = risk_limits_for(bot_limits, equity=equity)

        # max_symbol_exposure_pct = max_symbol_notional / equity (no 2x)
        assert limits.max_symbol_exposure_pct == pytest.approx(15_000.0 / equity)
        # max_total_exposure_pct = max_gross_notional / equity (no 2x)
        assert limits.max_total_exposure_pct == pytest.approx(30_000.0 / equity)
        # Other fields pass through directly
        assert limits.max_notional_abs == 15_000.0
        assert limits.max_open_positions == 6  # max_symbols + 1
        assert limits.max_daily_loss_pct == 0.02

    def test_flip_rollback_restores_prior_book(self):
        """FLIP that rolls back restores governor to pre-flip state."""
        governor = _governor(
            min_confidence=0.0, max_notional_pct=1.0, max_symbol_exposure_pct=2.0,
            max_total_exposure_pct=4.0, max_open_positions=4,
            start_of_day_equity=EQUITY, high_water_mark=EQUITY,
        )
        # Pre-populate with BTCUSDT long carry
        governor.limits.positions["BTCUSDT"] = {"quantity": 0.0, "avg_entry_price": 0.0, "gross_notional": 20_000.0}
        pre_snapshot = {k: dict(v) for k, v in governor.limits.positions.items()}
        
        engine, broker = build_paper_venue(EQUITY)
        broker.margin_ratio = 5.0  # forces rejection
        
        # FLIP from long to short
        result = run_paper_execution(
            engine, broker, "BTCUSDT", -1, NOTIONAL, PRICE, EQUITY,
            action="FLIP", current_side=1, current_notional=NOTIONAL, governor=governor
        )
        
        assert result.filled is False
        assert result.action == "ROLLED_BACK"
        # Governor must be exactly as before (BTCUSDT 20000 gross)
        assert governor.limits.positions == pre_snapshot


class TestPriceLoader:
    def test_the_price_loader_reads_the_last_bar_at_or_before_the_timestamp(
        self, tmp_path
    ):
        """Catches: a price taken from a bar that printed after the funding print."""
        frame = pd.DataFrame(
            {
                "open_time": [1_000, 2_000, 3_000],
                "close": [10.0, 20.0, 30.0],
            }
        )
        frame.to_parquet(tmp_path / "BTCUSDT_15m.parquet")

        price, source = load_price_at("BTCUSDT", 2_500, tmp_path)

        assert price == 20.0
        assert source == "15m_close"

    def test_a_missing_price_file_falls_back_to_the_notional_unit(self):
        """Catches: a missing price file aborting the run instead of degrading."""
        price, source = load_price_at("BTCUSDT", 2_500, "/nonexistent-data-dir")
        assert price == 1.0
        assert source == "notional_unit"


def test_the_execution_result_is_a_paper_result():
    """Catches: an execution result that forgets it is paper-only."""
    result = ExecutionResult(
        symbol="BTCUSDT",
        action="OPEN",
        legs=(),
        fees=0.0,
        filled=True,
        reason="opened",
    )
    assert result.mode == "PAPER"
    assert result.live is False


def test_the_carry_broker_is_a_paper_broker():
    """Catches: the carry broker inheriting a live flag from its parent."""
    broker = CarryPaperBroker(initial_balance=1_000.0)
    assert broker.paper_trading is True
    assert broker.balances["USDT"] == 1_000.0


def test_approve_target_picks_up_a_daily_loss_recorded_mid_cycle():
    """The governor must re-check daily loss against the current day P&L.

    The runner re-syncs governor.limits.daily_pnl after every symbol, so a
    loss booked by an earlier symbol must stand later symbols down in the
    same cycle instead of being judged against a stale cycle-start snapshot.
    """
    governor = RiskGovernor(
        risk_limits_for(RiskLimits(max_daily_loss_pct=0.03), EQUITY)
    )
    approved, reason = approve_target(
        governor, "BTCUSDT", 2_000.0, EQUITY, per_leg_notional=1_000.0
    )
    assert approved is True
    assert reason is None
    # A $400 loss lands mid-cycle (4% of the 10,000 equity, over the 3% cap).
    governor.limits.daily_pnl = -400.0
    approved, reason = approve_target(
        governor, "ETHUSDT", 2_000.0, EQUITY, per_leg_notional=1_000.0
    )
    assert approved is False
    assert "daily loss" in reason
    # The failed approval must not leave an allocation behind.
    assert "ETHUSDT" not in governor.limits.positions


class TestRollbackGovernor:
    def test_rollback_restores_governor_book(self):
        """Rolled-back OPEN/FLIP leaves governor exactly as before."""
        governor = _governor(
            min_confidence=0.0,
            max_notional_pct=1.0,
            max_symbol_exposure_pct=2.0,
            max_total_exposure_pct=4.0,
            max_open_positions=4,
            start_of_day_equity=EQUITY,
            high_water_mark=EQUITY,
        )
        # Pre-populate with an existing symbol
        governor.limits.positions["ETHUSDT"] = {
            "quantity": 0.0,
            "avg_entry_price": 0.0,
            "gross_notional": 10_000.0,
        }
        pre_snapshot = {k: dict(v) for k, v in governor.limits.positions.items()}

        engine, broker = build_paper_venue(EQUITY)
        broker.margin_ratio = 5.0  # forces rejection on second leg

        result = run_paper_execution(
            engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY, governor=governor
        )

        assert result.filled is False
        assert result.action == "ROLLED_BACK"
        # Governor must be exactly as before
        assert governor.limits.positions == pre_snapshot

    def test_close_removes_governor_exposure(self):
        """After successful CLOSE, governor no longer has the symbol."""
        governor = _governor(
            min_confidence=0.0, max_notional_pct=1.0, max_symbol_exposure_pct=2.0,
            max_total_exposure_pct=4.0, max_open_positions=4,
            start_of_day_equity=EQUITY, high_water_mark=EQUITY,
        )
        governor.limits.positions["BTCUSDT"] = {"quantity": 0.0, "avg_entry_price": 0.0, "gross_notional": 10_000.0}
        
        engine, broker = build_paper_venue(EQUITY)
        # First open the position
        run_paper_execution(engine, broker, "BTCUSDT", 1, NOTIONAL, PRICE, EQUITY, governor=governor)
        
        # Now close it
        result = run_paper_execution(
            engine, broker, "BTCUSDT", 0, NOTIONAL, PRICE, EQUITY,
            action="CLOSE", current_side=1, current_notional=NOTIONAL, governor=governor
        )
        
        assert result.filled is True
        assert result.action == "CLOSE"
        assert "BTCUSDT" not in governor.limits.positions
