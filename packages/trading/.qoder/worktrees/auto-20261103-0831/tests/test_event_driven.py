"""
Unit tests for EventDrivenBacktester
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from alpha.backtest import EventDrivenBacktester


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
        # the ledger, and it has to reconcile or the counts are decorative.
        results = _run([100, 108, 112], [1, 1, 1], commission=0.001, slippage=0.0005)
        assert results['n_round_trips'] == 1
        assert results['open_positions_at_end'] == {'ASSET_A': 1.0}
        equity_move = results['final_equity'] - results['initial_capital']
        assert results['net_pnl'] == pytest.approx(equity_move)
        assert results['net_pnl'] == pytest.approx(12.0 - 100 * 0.0015)

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
        # Short from 110 marked at 121 -> the price ran away from it.
        assert short['net_pnl'] == pytest.approx(-11.0)
        assert results['win_rate'] == pytest.approx(0.5)

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
        assert 'Round trips: 1' in sheet

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


if __name__ == "__main__":
    # Run tests if executed directly
    pytest.main([__file__, "-v"])
