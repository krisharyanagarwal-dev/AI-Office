"""
Unit tests for VectorizedBacktester (to ensure our fixes didn't break anything)
"""
import pytest
import pandas as pd
import numpy as np

from alpha.backtest import VectorizedBacktester


class TestVectorizedBacktester:
    """Test suite for VectorizedBacktester class"""
    
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
        """Test that VectorizedBacktester can be imported and instantiated"""
        from alpha.backtest import VectorizedBacktester
        
        # Should be able to import
        assert VectorizedBacktester is not None
        
        # Should be able to instantiate
        backtester = VectorizedBacktester()
        assert isinstance(backtester, VectorizedBacktester)
    
    def test_run_backtest_basic(self, sample_data, sample_signals):
        """Test basic backtest execution"""
        backtester = VectorizedBacktester()
        
        results = backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        
        # Should return results dictionary
        assert isinstance(results, dict)
        assert 'initial_capital' in results
        assert 'metrics' in results
        assert 'equity_curve' in results
        
        # Basic validations
        assert results['initial_capital'] == 100000
        assert isinstance(results['metrics']['total_return'], float)
        assert isinstance(results['metrics']['annualized_return'], float)
        assert results['metrics']['volatility'] >= 0
        assert 0 <= results['metrics']['win_rate'] <= 1
        
        # Equity curve should exist
        assert isinstance(results['equity_curve'], pd.Series)
        assert len(results['equity_curve']) > 0
    
    def test_tear_sheet_generation(self, sample_data, sample_signals):
        """Test tear sheet generation through the backtester"""
        backtester = VectorizedBacktester()
        
        # Run a backtest first
        results = backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        
        # Access tear sheet via get_tear_sheet method
        tear_sheet = backtester.get_tear_sheet()
        
        assert isinstance(tear_sheet, str)
        assert len(tear_sheet) > 0
        assert 'BACKTEST TEAR SHEET' in tear_sheet
    
    def test_different_frequencies(self):
        """Test with different data frequencies"""
        # Hourly data
        dates_hourly = pd.date_range('2020-01-01', periods=100, freq='h')
        prices = 100 + np.cumsum(np.random.normal(0.0001, 0.005, 100))
        
        data_hourly = pd.DataFrame({
            'open': prices * 0.999,
            'high': prices * 1.001,
            'low': prices * 0.998,
            'close': prices,
            'volume': np.random.randint(10000, 100000, 100)
        }, index=dates_hourly)
        
        data = {'ASSET_A': data_hourly}
        
        # Simple signal
        signals = {'ASSET_A': pd.Series([1] * 100, index=dates_hourly)}
        
        backtester = VectorizedBacktester()
        results = backtester.run_backtest(
            signals=signals,
            data=data,
            initial_capital=100000
        )
        
        assert isinstance(results, dict)
        assert results['initial_capital'] == 100000
        assert 'metrics' in results


if __name__ == "__main__":
    # Run tests if executed directly
    pytest.main([__file__, "-v"])
