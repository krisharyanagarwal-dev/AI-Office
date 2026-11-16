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


if __name__ == "__main__":
    # Run tests if executed directly
    pytest.main([__file__, "-v"])
