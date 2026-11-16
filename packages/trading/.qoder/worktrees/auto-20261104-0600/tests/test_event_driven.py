"""
Unit tests for EventDrivenBacktester
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from alpha.backtest import EventDrivenBacktester, event_driven


class TestEventDrivenBacktester:
    """Test suite for EventDrivenBacktester class"""
    
    @pytest.fixture
    def sample_data(self):
        """Create sample OHLCV data for testing"""
        dates = pd.date_range('2020-01-01', periods=100, freq='D')
        
        # Create two assets with different patterns
        prices_a = 100 + np.cumsum(np.random.normal(0.001, 0.02, 100))
        prices_b = 50 + np.cumsum(np.random.normal(0.0005, 0.015, 100))
        
        data_a = pd.DataFrame({
            'open': prices_a * 0.99,
            'high': prices_a * 1.01,
            'low': prices_a * 0.98,
            'close': prices_a,
            'volume': np.random.randint(1000000, 5000000, 100)
        }, index=dates)
        
        data_b = pd.DataFrame({
            'open': prices_b * 0.99,
            'high': prices_b * 1.01,
            'low': prices_b * 0.98,
            'close': prices_b,
            'volume': np.random.randint(1000000, 5000000, 100)
        }, index=dates)
        
        return {
            'ASSET_A': data_a,
            'ASSET_B': data_b
        }
    
    @pytest.fixture
    def sample_signals(self, sample_data):
        """Create sample signals based on sample data"""
        signals = {}
        for symbol, df in sample_data.items():
            # Simple moving average crossover signal
            ma_10 = df['close'].rolling(10).mean()
            ma_30 = df['close'].rolling(30).mean()
            signal = np.where(ma_10 > ma_30, 1, -1)  # 1 for long, -1 for short
            signals[symbol] = pd.Series(signal, index=df.index)
        return signals
    
    def test_import_and_instantiation(self):
        """Test that EventDrivenBacktester can be imported and instantiated"""
        from alpha.backtest import EventDrivenBacktester
        
        # Should be able to import
        assert EventDrivenBacktester is not None
        
        # Should be able to instantiate
        backtester = EventDrivenBacktester()
        assert isinstance(backtester, EventDrivenBacktester)
    
    def test_get_common_index(self):
        """Test the _get_common_index helper method"""
        backtester = EventDrivenBacktester()
        
        # Create test data with overlapping dates
        dates1 = pd.date_range('2020-01-01', periods=50, freq='D')
        dates2 = pd.date_range('2020-02-15', periods=50, freq='D')  # Overlap Feb 15 - Mar 31
        
        data = {
            'ASSET_A': pd.DataFrame({'close': [1]*50}, index=dates1),
            'ASSET_B': pd.DataFrame({'close': [1]*50}, index=dates2)
        }
        
        common_index = backtester._get_common_index(data)
        
        # Should contain only overlapping dates
        assert len(common_index) > 0
        # Overlap should be from Feb 15 to Mar 31 (approximately 45 days)
        # With our specific dates: Feb 15 to Mar 31 is 45 days
        # But we only have 50 days in each series starting from their respective start dates
        # dates1: Jan 1 - Feb 19 (50 days)
        # dates2: Feb 15 - Apr 5 (50 days)
        # Overlap: Feb 15 - Feb 19 = 5 days
        assert len(common_index) == 5
    
    def test_get_common_index_no_overlap(self):
        """Test _get_common_index with no overlapping dates"""
        backtester = EventDrivenBacktester()
        
        dates1 = pd.date_range('2020-01-01', periods=30, freq='D')
        dates2 = pd.date_range('2020-03-01', periods=30, freq='D')
        
        data = {
            'ASSET_A': pd.DataFrame({'close': [1]*30}, index=dates1),
            'ASSET_B': pd.DataFrame({'close': [1]*30}, index=dates2)
        }
        
        common_index = backtester._get_common_index(data)
        
        # Should have no overlap
        assert len(common_index) == 0
    
    def test_run_backtest_basic(self, sample_data, sample_signals):
        """Test basic backtest execution"""
        backtester = EventDrivenBacktester()
        
        results = backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        
        # Should return results dictionary
        assert isinstance(results, dict)
        assert 'initial_capital' in results
        assert 'final_equity' in results
        assert 'total_return' in results
        assert 'annualized_return' in results
        assert 'volatility' in results
        assert 'sharpe_ratio' in results
        assert 'max_drawdown' in results
        assert 'win_rate' in results
        assert 'total_trades' in results
        
        # Basic validations
        assert results['initial_capital'] == 100000
        assert isinstance(results['total_return'], float)
        assert isinstance(results['annualized_return'], float)
        assert results['volatility'] >= 0
        assert 0 <= results['win_rate'] <= 1
        assert results['total_trades'] >= 0
        
        # Equity curve should exist
        assert 'equity_curve' in results
        assert isinstance(results['equity_curve'], pd.DataFrame)
        assert len(results['equity_curve']) > 0
    
    def test_run_backtest_with_costs(self, sample_data, sample_signals):
        """Test backtest with commission and slippage"""
        backtester = EventDrivenBacktester()
        
        # Run with costs
        results_with_costs = backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000,
            commission=0.001,
            slippage=0.0005
        )
        
        # Run without costs
        results_without_costs = backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000,
            commission=0.0,
            slippage=0.0
        )
        
        # Both should be valid
        assert 'total_return' in results_with_costs
        assert 'total_return' in results_without_costs
        
        # Both should be valid numbers
        assert isinstance(results_with_costs['total_return'], float)
        assert isinstance(results_without_costs['total_return'], float)
    
    def test_empty_data_handling(self):
        """Test handling of empty data inputs"""
        backtester = EventDrivenBacktester()
        
        empty_data = {}
        empty_signals = {}
        
        # Should handle gracefully (may raise ValueError which is acceptable)
        try:
            results = backtester.run_backtest(
                signals=empty_signals,
                data=empty_data,
                initial_capital=100000
            )
            # If it doesn't raise an exception, results should still be valid
            assert isinstance(results, dict)
        except ValueError:
            # This is also acceptable behavior
            pass
    
    def test_single_asset(self):
        """Test with single asset"""
        backtester = EventDrivenBacktester()
        
        dates = pd.date_range('2020-01-01', periods=50, freq='D')
        prices = 100 + np.cumsum(np.random.normal(0.001, 0.02, 50))
        
        data = {
            'ASSET_A': pd.DataFrame({
                'open': prices * 0.99,
                'high': prices * 1.01,
                'low': prices * 0.98,
                'close': prices,
                'volume': np.random.randint(1000000, 5000000, 50)
            }, index=dates)
        }
        
        # Simple buy signal
        signals = {
            'ASSET_A': pd.Series([1] * 50, index=dates)
        }
        
        results = backtester.run_backtest(
            signals=signals,
            data=data,
            initial_capital=100000
        )
        
        assert isinstance(results, dict)
        assert results['initial_capital'] == 100000
        assert 'total_return' in results
    
    def test_tear_sheet_generation(self, sample_data, sample_signals):
        """Test tear sheet generation"""
        backtester = EventDrivenBacktester()
        
        # Run a backtest first
        results = backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        
        # Generate tear sheet
        tear_sheet = backtester.get_tear_sheet()
        
        assert isinstance(tear_sheet, str)
        assert len(tear_sheet) > 0
        assert 'BACKTEST TEAR SHEET' in tear_sheet
        assert 'RETURNS' in tear_sheet
        assert 'RISK METRICS' in tear_sheet
    
    def test_get_results_before_run(self):
        """Test getting results before running backtest"""
        backtester = EventDrivenBacktester()
        
        results = backtester.get_results()
        
        # Should return empty dict or similar before running
        assert isinstance(results, dict)
    
    def test_deterministic_with_seed(self, sample_data):
        """Test that same seed produces same results"""
        # Create deterministic signals
        signals = {}
        for symbol, df in sample_data.items():
            # Use first column values to create deterministic signal
            signal = (df['close'] > df['close'].rolling(20).mean()).astype(int)
            signal = signal * 2 - 1  # Convert 0/1 to -1/1
            signals[symbol] = signal
        
        # Run backtest twice with same parameters
        backtester1 = EventDrivenBacktester()
        results1 = backtester1.run_backtest(
            signals=signals,
            data=sample_data,
            initial_capital=100000
        )
        
        backtester2 = EventDrivenBacktester()
        results2 = backtester2.run_backtest(
            signals=signals,
            data=sample_data,
            initial_capital=100000
        )
        
        # Results should be identical
        assert results1['total_return'] == results2['total_return']
        assert results1['final_equity'] == results2['final_equity']


def _flat_book(prices, signals):
    """Deterministic single-symbol book for hand-computable P&L checks."""
    dates = pd.date_range('2020-01-01', periods=len(prices), freq='D')
    prices = np.asarray(prices, dtype=float)
    data = {'ASSET_A': pd.DataFrame({
        'open': prices, 'high': prices, 'low': prices, 'close': prices,
        'volume': np.full(len(prices), 1e6),
    }, index=dates)}
    return data, {'ASSET_A': pd.Series(signals, index=dates, dtype=float)}


def _run(prices, signals, commission, slippage):
    data, sig = _flat_book(prices, signals)
    return EventDrivenBacktester().run_backtest(
        signals=sig, data=data, initial_capital=100000,
        commission=commission, slippage=slippage,
    )


class TestWinRateIsRealized:
    """`win_rate` used to be `len([t for t in trades if t['value'] > 0]) / len(trades)`.

    ``trade_value`` is ``abs(trade_size) * price`` and a trade is only recorded when
    ``abs(trade_size) > 1e-8``, so the numerator equalled the denominator on every
    book with at least one fill: the tear sheet and ``compare_backtesters.py``
    reported a 100.00% win rate for a strategy that lost money. These tests pin
    win rate to *realized* round-trip P&L, net of the modelled costs.
    """

    def test_a_book_where_every_round_trip_loses_does_not_report_100_percent(self):
        results = _run([100, 99, 98, 97, 96, 95, 94, 93],
                       [1, 1, 0, 0, 1, 1, 0, 0], commission=0.0, slippage=0.0)
        assert results['n_round_trips'] == 2
        assert results['winning_round_trips'] == 0
        assert results['win_rate'] == 0.0
        assert results['net_pnl'] < 0

    def test_win_rate_counts_wins_and_losses_exactly(self):
        # Long @100 -> flat @110 (+10), long @105 -> flat @95 (-10): one win, one loss.
        results = _run([100, 110, 105, 95], [1, 0, 1, 0],
                       commission=0.0, slippage=0.0)
        assert results['n_round_trips'] == 2
        assert results['winning_round_trips'] == 1
        assert results['losing_round_trips'] == 1
        assert results['win_rate'] == pytest.approx(0.5)
        assert results['gross_pnl'] == pytest.approx(0.0)
        assert results['net_pnl'] == pytest.approx(0.0)

    def test_round_trip_pnl_is_net_of_commission_and_slippage(self):
        # Same shape, Binance VIP0 taker 0.1% + 0.05% slippage per side.
        results = _run([100, 110, 105, 95], [1, 0, 1, 0],
                       commission=0.001, slippage=0.0005)
        per_side = 0.001 + 0.0005
        expected_win = 10.0 - (100 * per_side) - (110 * per_side)
        expected_loss = -10.0 - (105 * per_side) - (95 * per_side)
        assert results['gross_pnl'] == pytest.approx(0.0)
        assert results['net_pnl'] == pytest.approx(expected_win + expected_loss)
        assert results['total_costs'] == pytest.approx(
            (100 + 110 + 105 + 95) * per_side)
        # Costs turn a gross scratch into a net loss, so the second leg is a loss
        # and the win rate must not read as a coin flip.
        assert results['win_rate'] == pytest.approx(0.5)
        assert results['profit_factor'] == pytest.approx(
            expected_win / abs(expected_loss))

    def test_a_gross_win_that_costs_more_than_it_made_is_not_counted_as_a_win(self):
        # +0.20 gross on the round trip, 0.30 of costs -> a loser.
        results = _run([100.0, 100.2], [1, 0], commission=0.001, slippage=0.0005)
        assert results['gross_pnl'] == pytest.approx(0.2)
        assert results['net_pnl'] == pytest.approx(0.2 - (100.0 + 100.2) * 0.0015)
        assert results['win_rate'] == 0.0

    def test_realized_ledger_reconciles_with_equity(self):
        # Position still open at the end: the mark-to-market leg is what closes
        # the ledger, so it must reconcile with equity -- but a mark is not a
        # trade that happened, so it stays OUT of the realized statistics.
        results = _run([100, 108, 112], [1, 1, 1], commission=0.001, slippage=0.0005)
        assert results['n_round_trips'] == 0
        assert results['n_mark_to_market'] == 1
        assert results['realized_net_pnl'] == 0.0
        assert results['win_rate'] == 0.0
        assert results['profit_factor'] == 0.0
        assert results['open_positions_at_end'] == {'ASSET_A': 1.0}
        equity_move = results['final_equity'] - results['initial_capital']
        assert results['net_pnl'] == pytest.approx(equity_move)
        assert results['net_pnl'] == pytest.approx(12.0 - 100 * 0.0015)
        # The mark is reported separately, and realized + carried is the whole book.
        assert results['unrealized_net_pnl'] == pytest.approx(12.0 - 100 * 0.0015)
        assert results['net_pnl'] == pytest.approx(
            results['realized_net_pnl'] + results['unrealized_net_pnl'])

    def test_flipping_through_zero_closes_the_old_leg_before_opening_the_new_one(self):
        # Long @100, then a -1 signal from +1: closes 1 unit and opens 1 short @110.
        results = _run([100, 110, 121], [1, -1, 0], commission=0.0, slippage=0.0)
        ledger = results['round_trips']
        assert len(ledger) == 2
        first = ledger.iloc[0]
        assert first['direction'] == 1
        assert first['net_pnl'] == pytest.approx(10.0)
        short = ledger.iloc[1]
        assert short['direction'] == -1
        # Short from 110 closed by the flat signal at 121 -> the price ran away from it.
        assert short['net_pnl'] == pytest.approx(-11.0)
        assert short['kind'] == 'close'
        assert results['n_round_trips'] == 2
        assert results['win_rate'] == pytest.approx(0.5)
        assert results['losing_round_trips'] == 1

    def test_tear_sheet_reports_costs_and_round_trip_count(self):
        backtester = EventDrivenBacktester()
        data, sig = _flat_book([100, 99, 98, 97], [1, 1, 0, 0])
        backtester.run_backtest(signals=sig, data=data, initial_capital=100000,
                                commission=0.001, slippage=0.0005)
        sheet = backtester.get_tear_sheet()
        assert '100.00%' not in sheet
        assert 'Win Rate: 0.00%' in sheet
        # A cost figure is meaningless without the assumption that produced it.
        assert 'commission 0.10%' in sheet
        assert 'slippage 0.05%' in sheet
        assert '1 realized round trip' in sheet
        assert 'COST SENSITIVITY' in sheet

    def test_no_trades_still_reports_zero_win_rate(self):
        results = _run([100, 101, 102], [0, 0, 0], commission=0.001, slippage=0.0005)
        assert results['n_round_trips'] == 0
        assert results['win_rate'] == 0.0

    @pytest.mark.parametrize('seed', list(range(25)))
    def test_realized_ledger_reconciles_on_random_books(self, seed):
        """The ledger has to account for every dollar, every book, flips included."""
        rng = np.random.default_rng(seed)
        n = int(rng.integers(6, 40))
        prices = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
        signals = rng.choice([-1.0, 0.0, 1.0], size=n)
        backtester = EventDrivenBacktester()
        data, sig = _flat_book(prices, signals)
        results = backtester.run_backtest(
            signals=sig, data=data, initial_capital=100000,
            commission=0.001, slippage=0.0005,
        )
        assert results['n_round_trips'] > 0
        assert results['net_pnl'] == pytest.approx(
            results['final_equity'] - results['initial_capital'])
        assert results['net_pnl'] == pytest.approx(
            results['gross_pnl'] - results['total_costs'])
        assert results['winning_round_trips'] + results['losing_round_trips'] \
            <= results['n_round_trips']

    @pytest.mark.parametrize('seed', list(range(15)))
    def test_win_rate_is_not_one_hundred_on_random_books(self, seed):
        """The pre-fix formula returned exactly 1.0 for every book that traded."""
        rng = np.random.default_rng(seed)
        n = int(rng.integers(10, 40))
        prices = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
        signals = rng.choice([-1.0, 0.0, 1.0], size=n)
        data, sig = _flat_book(prices, signals)
        results = EventDrivenBacktester().run_backtest(
            signals=sig, data=data, initial_capital=100000,
            commission=0.001, slippage=0.0005,
        )
        if results['n_round_trips'] > 1:
            assert results['win_rate'] < 1.0


class TestMarksAreNotRealizedTrades:
    """A position still open at the last bar is marked, not traded.

    The ledger reconciles against the final price, but the mark must not be
    scored as a realized round trip: an unrealized gain is not a win and an
    unrealized loss is not a loss, and mixing them lets a book's "win rate"
    move on a bar nobody traded on.
    """

    def test_a_profitable_mark_does_not_count_as_a_win(self):
        # Long @100 and never closed: +8 of mark, zero completed round trips.
        results = _run([100, 104, 108], [1, 1, 1], commission=0.0, slippage=0.0)
        assert results['n_round_trips'] == 0
        assert results['n_mark_to_market'] == 1
        assert results['winning_round_trips'] == 0
        assert results['win_rate'] == 0.0
        assert results['realized_net_pnl'] == 0.0
        assert results['unrealized_net_pnl'] == pytest.approx(8.0)
        assert results['net_pnl'] == pytest.approx(8.0)

    def test_a_losing_mark_does_not_count_as_a_loss(self):
        results = _run([100, 96, 92], [1, 1, 1], commission=0.0, slippage=0.0)
        assert results['n_round_trips'] == 0
        assert results['losing_round_trips'] == 0
        assert results['unrealized_net_pnl'] == pytest.approx(-8.0)

    def test_marks_do_not_move_the_win_rate_of_a_realized_book(self):
        """Realized: one win, one loss. Then a third position is opened and left
        open, deep in the money. The realized win rate must stay 0.5."""
        data, sig = _flat_book([100, 110, 105, 95, 120, 130], [1, 0, 1, 0, 1, 1])
        results = EventDrivenBacktester().run_backtest(
            signals=sig, data=data, initial_capital=100000,
            commission=0.0, slippage=0.0)
        assert results['n_round_trips'] == 2
        assert results['win_rate'] == pytest.approx(0.5)
        assert results['n_mark_to_market'] == 1
        # Re-entered long @120, marked at the last bar's 130 -> +10, never traded.
        assert results['unrealized_net_pnl'] == pytest.approx(10.0)
        assert results['winning_round_trips'] == 1
        assert results['losing_round_trips'] == 1
        kinds = list(results['round_trips']['kind'])
        assert kinds.count('close') == 2 and kinds.count('mark_to_market') == 1

    def test_realized_and_carried_together_equal_the_equity_move(self):
        for seed in range(10):
            rng = np.random.default_rng(seed)
            n = int(rng.integers(6, 30))
            prices = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
            signals = rng.choice([-1.0, 0.0, 1.0], size=n)
            data, sig = _flat_book(prices, signals)
            results = EventDrivenBacktester().run_backtest(
                signals=sig, data=data, initial_capital=100000,
                commission=0.001, slippage=0.0005)
            assert results['realized_net_pnl'] + results['unrealized_net_pnl'] \
                == pytest.approx(results['final_equity'] - results['initial_capital'])
            assert results['n_round_trips'] + results['n_mark_to_market'] \
                == len(results['round_trips'])

    def test_costs_booked_in_the_ledger_equal_costs_charged_on_fills(self):
        data, sig = _flat_book([100, 110, 105, 95, 120], [1, 0, 1, 0, 1])
        results = EventDrivenBacktester().run_backtest(
            signals=sig, data=data, initial_capital=100000,
            commission=0.001, slippage=0.0005)
        assert results['total_costs'] == pytest.approx(
            results['trades']['total_cost'].sum())
        assert results['realized_costs'] + results['unrealized_costs'] \
            == pytest.approx(results['total_costs'])

    def test_carried_position_owes_its_way_out(self):
        """An open position has not paid its exit fee yet. Reporting it as if the
        book were flat at the end must subtract that fee, not pretend it is free."""
        results = _run([100, 104, 108], [1, 1, 1], commission=0.001, slippage=0.0005)
        # Entry fee was already booked (100 * 0.0015); the exit at 108 was not.
        assert results['exit_cost_on_open_positions'] == pytest.approx(108 * 0.0015)
        assert results['net_pnl_if_flat_at_end'] == pytest.approx(
            results['net_pnl'] - results['exit_cost_on_open_positions'])
        assert results['net_pnl_if_flat_at_end'] < results['net_pnl']


class TestProfitFactorIsNotInfinity:
    """`inf` in a report reads as unbounded edge. With no losing round trip the
    ratio has no denominator: report it undefined."""

    def test_wins_with_no_losses_is_undefined_not_infinite(self):
        results = _run([100, 110, 105, 115], [1, 0, 1, 0],
                       commission=0.0, slippage=0.0)
        assert results['winning_round_trips'] == 2
        assert results['losing_round_trips'] == 0
        assert results['profit_factor'] is None
        assert results['profit_factor'] != float('inf')

    def test_no_trades_at_all_is_zero(self):
        results = _run([100, 101, 102], [0, 0, 0], commission=0.001, slippage=0.0005)
        assert results['profit_factor'] == 0.0

    def test_a_real_ratio_is_still_reported(self):
        # Round trips: 100->110 (+10), 105->125 (+20), 120->110 (-10) -> 30/10 = 3.0
        results = _run([100, 110, 105, 125, 120, 110], [1, 0, 1, 0, 1, 0],
                       commission=0.0, slippage=0.0)
        assert results['winning_round_trips'] == 2
        assert results['losing_round_trips'] == 1
        assert results['profit_factor'] == pytest.approx(3.0)

    def test_tear_sheet_renders_when_profit_factor_is_undefined(self):
        backtester = EventDrivenBacktester()
        data, sig = _flat_book([100, 110, 105, 115], [1, 0, 1, 0])
        backtester.run_backtest(signals=sig, data=data, initial_capital=100000,
                                commission=0.001, slippage=0.0005)
        sheet = backtester.get_tear_sheet()
        assert 'inf' not in sheet
        assert 'undefined' in sheet

    def test_tear_sheet_renders_on_a_book_that_never_traded(self):
        backtester = EventDrivenBacktester()
        data, sig = _flat_book([100, 101, 102], [0, 0, 0])
        backtester.run_backtest(signals=sig, data=data, initial_capital=100000,
                                commission=0.001, slippage=0.0005)
        sheet = backtester.get_tear_sheet()
        assert 'no fee clears this book' in sheet



class TestCostSensitivityFlowsThroughTheEngine:
    """The event engine must publish the cost block, not just compute it internally."""

    def test_gross_is_reported_separately_from_net(self):
        results = _run([100, 110, 105, 95], [1, 0, 1, 0], commission=0.001, slippage=0.0005)
        cs = results['cost_sensitivity']
        assert cs['gross_pnl'] == pytest.approx(0.0)
        assert cs['costs_at_modelled'] > 0
        assert cs['net_pnl'] < cs['gross_pnl']
        assert cs['clears_modelled_costs'] is False
        assert cs['net_pnl'] == pytest.approx(results['net_pnl'])

    def test_venue_fee_assumption_is_stated_in_the_output(self):
        results = _run([100, 110, 105, 95], [1, 0, 1, 0], commission=0.001, slippage=0.0005)
        cs = results['cost_sensitivity']
        assert 'Binance' in cs['venue']
        assert cs['modelled_commission_bps_per_side'] == pytest.approx(10.0)
        assert cs['modelled_slippage_bps_per_side'] == pytest.approx(5.0)
        assert cs['modelled_cost_bps_per_round_trip'] == pytest.approx(30.0)
        assert cs['funding_modelled'] is False
        assert 'NOT modeled' in cs['funding_note']

    def test_significance_basis_says_what_one_observation_is(self):
        results = _run([100, 110, 105, 95], [1, 0, 1, 0], commission=0.001, slippage=0.0005)
        assert results['cost_sensitivity']['significance']['basis'] == 'per realized round trip'

    def test_break_even_is_hand_computable(self):
        # Buy @100, sell @110 -> gross +10 on one unit; two fills on 210 notional
        # at 0.0015/side = 0.315 of cost. net(fee) = 10 - (fee/1e4 + 0.0005) * 210.
        results = _run([100, 110], [1, 0], commission=0.001, slippage=0.0005)
        cs = results['cost_sensitivity']
        assert cs['gross_pnl'] == pytest.approx(10.0)
        assert cs['costs_at_modelled'] == pytest.approx(0.315)
        assert cs['net_pnl'] == pytest.approx(9.685)
        assert cs['break_even_bps_per_side'] == pytest.approx((10 / 210 - 0.0005) * 1e4)

    def test_scenarios_are_consistent_with_the_break_even(self):
        for seed in range(8):
            rng = np.random.default_rng(100 + seed)
            n = int(rng.integers(8, 40))
            prices = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
            signals = rng.choice([1.0, 0.0], size=n)
            data, sig = _flat_book(prices, signals)
            results = EventDrivenBacktester().run_backtest(
                signals=sig, data=data, initial_capital=100000,
                commission=0.001, slippage=0.0005)
            cs = results['cost_sensitivity']
            be = cs['break_even_bps_per_side']
            if be is None:
                assert all(not s['clears'] for s in cs['scenarios']
                           if s['fee_bps_per_side'] > 0)
                continue
            assert be > 0
            for s in cs['scenarios']:
                clears_expected = (s['fee_bps_per_side'] < be - 1e-9
                                   or abs(s['net_pnl']) < 1e-6)
                assert s['clears'] == clears_expected

    def test_a_losing_book_has_no_break_even_fee(self):
        results = _run([100, 99, 98, 97], [1, 1, 0, 0], commission=0.001, slippage=0.0005)
        cs = results['cost_sensitivity']
        assert cs['gross_pnl'] < 0
        assert cs['break_even_bps_per_side'] is None
        assert 'no fee clears' in cs['break_even_basis']
        assert all(not s['clears'] for s in cs['scenarios'])

    def test_a_small_winning_book_still_cannot_be_claimed_tradeable(self):
        results = _run([100, 110], [1, 0], commission=0.001, slippage=0.0005)
        cs = results['cost_sensitivity']
        assert cs['clears_venue_fee'] is True
        assert cs['gates']['sample_is_reliable'] is False
        assert cs['tradeable_claim_allowed'] is False
        assert 'sample_is_reliable' in cs['claim_blockers']

    def test_a_ci_that_includes_zero_blocks_a_claim_but_is_not_read_as_a_loss(self):
        # Round trips: +10, -10, +10, -10 -> mean exactly 0, interval straddles it.
        results = _run([100, 110, 105, 95, 100, 110, 105, 95], [1, 0, 1, 0, 1, 0, 1, 0],
                       commission=0.0, slippage=0.0)
        cs = results['cost_sensitivity']
        sig = cs['significance']
        assert sig['n'] == 4
        assert sig['ci_excludes_zero'] is False
        assert sig['ci_includes_zero'] is True
        assert cs['tradeable_claim_allowed'] is False
        assert 'ci_excludes_zero_positive' in cs['claim_blockers']
        # The unproven CI must not be laundered into a losing direction.
        assert sig['mean'] == pytest.approx(0.0)
        assert results['winning_round_trips'] == 2
        assert results['losing_round_trips'] == 2
        assert 'losing' not in str(cs['claim_blockers'])

    def test_a_30_trade_book_with_a_real_ci_clears_every_gate(self):
        prices = [100 + 2 * i for i in range(64)]
        data, sig = _flat_book(prices, [1, 0] * 32)
        results = EventDrivenBacktester().run_backtest(
            signals=sig, data=data, initial_capital=100000,
            commission=0.001, slippage=0.0005)
        cs = results['cost_sensitivity']
        assert cs['significance']['n'] == 32
        assert cs['significance']['ci_excludes_zero'] is True
        assert cs['clears_venue_fee'] is True
        assert cs['tradeable_claim_allowed'] is True
        assert cs['claim_blockers'] == []
        assert results['n_mark_to_market'] == 0

    def test_tear_sheet_prints_the_net_number_not_the_gross_one(self):
        backtester = EventDrivenBacktester()
        data, sig = _flat_book([100, 110], [1, 0])
        backtester.run_backtest(signals=sig, data=data, initial_capital=100000,
                                commission=0.001, slippage=0.0005)
        sheet = backtester.get_tear_sheet()
        assert 'COST SENSITIVITY' in sheet
        assert 'Binance spot VIP0 maker/taker' in sheet
        assert 'bps per round trip' in sheet
        assert 'Tradeable claim allowed: False' in sheet


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
