"""
Integration tests for both backtesters
"""
import pytest
import pandas as pd
import numpy as np
import os

from alpha.backtest import VectorizedBacktester, EventDrivenBacktester


def get_vectorized_metrics(vec_results):
    """Extract metrics from vectorized backtester results in a standardized format"""
    metrics = vec_results["metrics"]
    equity_curve = vec_results["equity_curve"]
    
    return {
        "initial_capital": vec_results["initial_capital"],
        "final_equity": equity_curve.iloc[-1] if len(equity_curve) > 0 else vec_results["initial_capital"],
        "total_return": metrics["total_return"],
        "annualized_return": metrics["annualized_return"],
        "volatility": metrics["volatility"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "max_drawdown": metrics["max_drawdown"],
        "win_rate": metrics["win_rate"],
        "total_trades": metrics.get("total_days", 0)  # Approximation
    }


def get_event_driven_metrics(evt_results):
    """Extract metrics from event-driven backtester results"""
    return {
        "initial_capital": evt_results["initial_capital"],
        "final_equity": evt_results["final_equity"],
        "total_return": evt_results["total_return"],
        "annualized_return": evt_results["annualized_return"],
        "volatility": evt_results["volatility"],
        "sharpe_ratio": evt_results["sharpe_ratio"],
        "max_drawdown": evt_results["max_drawdown"],
        "win_rate": evt_results["win_rate"],
        "total_trades": evt_results["total_trades"]
    }


class TestBacktestIntegration:
    """Integration tests comparing both backtesters"""
    
    @pytest.fixture
    def sample_data(self):
        """Create sample OHLCV data for testing"""
        dates = pd.date_range('2020-01-01', periods=200, freq='D')
        
        # Create two assets with correlated returns
        np.random.seed(42)  # For reproducibility
        returns_a = np.random.normal(0.0005, 0.02, 200)  # 0.05% daily return, 2% volatility
        returns_b = np.random.normal(0.0003, 0.015, 200) + 0.5 * returns_a  # correlated with A
        
        # Convert to prices
        prices_a = 100 * np.exp(np.cumsum(returns_a))
        prices_b = 100 * np.exp(np.cumsum(returns_b))
        
        data_a = pd.DataFrame({
            'open': prices_a * 0.99,
            'high': prices_a * 1.01,
            'low': prices_a * 0.98,
            'close': prices_a,
            'volume': np.random.randint(1000000, 5000000, 200)
        }, index=dates)
        
        data_b = pd.DataFrame({
            'open': prices_b * 0.99,
            'high': prices_b * 1.01,
            'low': prices_b * 0.98,
            'close': prices_b,
            'volume': np.random.randint(1000000, 5000000, 200)
        }, index=dates)
        
        return {
            'ASSET_A': data_a,
            'ASSET_B': data_b
        }
    
    @pytest.fixture
    def sample_signals(self, sample_data):
        """Create sample signals: buy when price > 50-day moving average"""
        signals = {}
        for symbol, df in sample_data.items():
            ma_50 = df['close'].rolling(50).mean()
            signal = np.where(df['close'] > ma_50, 1, -1)  # 1 for long, -1 for short
            signals[symbol] = pd.Series(signal, index=df.index)
        return signals
    
    def test_both_backtesters_import(self):
        """Test that both backtesters can be imported"""
        from alpha.backtest import VectorizedBacktester, EventDrivenBacktester
        
        assert VectorizedBacktester is not None
        assert EventDrivenBacktester is not None
    
    def test_both_backtesters_instantiate(self):
        """Test that both backtesters can be instantiated"""
        from alpha.backtest import VectorizedBacktester, EventDrivenBacktester
        
        vec_backtester = VectorizedBacktester()
        evt_backtester = EventDrivenBacktester()
        
        assert isinstance(vec_backtester, VectorizedBacktester)
        assert isinstance(evt_backtester, EventDrivenBacktester)
    
    def test_both_produce_results(self, sample_data, sample_signals):
        """Test that both backtesters produce valid results"""
        # Set API keys to avoid provider errors
        os.environ['ALPHAVANTAGE_API_KEY'] = 'test_key'
        os.environ['POLYGON_API_KEY'] = 'test_key'
        
        # Vectorized backtester
        vec_backtester = VectorizedBacktester()
        vec_results = vec_backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        vec_metrics = get_vectorized_metrics(vec_results)
        
        # Event-driven backtester
        evt_backtester = EventDrivenBacktester()
        evt_results = evt_backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        evt_metrics = get_event_driven_metrics(evt_results)
        
        # Both should produce valid results
        assert isinstance(vec_results, dict)
        assert isinstance(evt_results, dict)
        
        # Check required fields exist using metrics
        required_fields = ["initial_capital", "total_return"]
        for field in required_fields:
            assert field in vec_metrics
            assert field in evt_metrics
    
    def test_results_are_reasonable(self, sample_data, sample_signals):
        """Test that results are within reasonable bounds"""
        # Set API keys to avoid provider errors
        os.environ['ALPHAVANTAGE_API_KEY'] = 'test_key'
        os.environ['POLYGON_API_KEY'] = 'test_key'
        
        # Vectorized backtester
        vec_backtester = VectorizedBacktester()
        vec_results = vec_backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        vec_metrics = get_vectorized_metrics(vec_results)
        
        # Event-driven backtester
        evt_backtester = EventDrivenBacktester()
        evt_results = evt_backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        evt_metrics = get_event_driven_metrics(evt_results)
        
        # Returns should be reasonable (not extreme values)
        # These are loose bounds - in practice returns could be higher/lower
        # but these prevent catastrophic failures
        assert -0.99 < vec_metrics["total_return"] < 10.0  # -99% to 1000%
        assert -0.99 < evt_metrics["total_return"] < 10.0  # -99% to 1000%
        
        # Volatility should be reasonable
        assert 0 <= vec_metrics["volatility"] < 5.0  # 0% to 500% annualized
        assert 0 <= evt_metrics["volatility"] < 5.0  # 0% to 500% annualized
        
        # Max drawdown should be between -100% and 0%
        assert -1.0 <= vec_metrics.get("max_drawdown", 0) <= 0
        assert -1.0 <= evt_metrics.get("max_drawdown", 0) <= 0
        
        # Win rate should be valid percentage
        assert 0 <= vec_metrics.get("win_rate", 0) <= 1
        assert 0 <= evt_metrics.get("win_rate", 0) <= 1
    
    def test_both_have_tear_sheets(self, sample_data, sample_signals):
        """Test that both backtesters can generate tear sheets"""
        # Set API keys to avoid provider errors
        os.environ['ALPHAVANTAGE_API_KEY'] = 'test_key'
        os.environ['POLYGON_API_KEY'] = 'test_key'
        
        # Vectorized backtester
        vec_backtester = VectorizedBacktester()
        vec_results = vec_backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        vec_tear_sheet = vec_backtester.get_tear_sheet()
        
        # Event-driven backtester
        evt_backtester = EventDrivenBacktester()
        evt_results = evt_backtester.run_backtest(
            signals=sample_signals,
            data=sample_data,
            initial_capital=100000
        )
        evt_tear_sheet = evt_backtester.get_tear_sheet()
        
        # Both should produce tear sheets
        assert isinstance(vec_tear_sheet, str)
        assert isinstance(evt_tear_sheet, str)
        assert len(vec_tear_sheet) > 0
        assert len(evt_tear_sheet) > 0
        
        # Should contain expected sections
        assert 'BACKTEST TEAR SHEET' in vec_tear_sheet
        assert 'BACKTEST TEAR SHEET' in evt_tear_sheet
        assert 'RETURNS' in vec_tear_sheet
        assert 'RETURNS' in evt_tear_sheet
    
    def test_consistent_initial_capital(self, sample_data, sample_signals):
        """Test that both backtesters respect initial capital parameter"""
        # Set API keys to avoid provider errors
        os.environ['ALPHAVANTAGE_API_KEY'] = 'test_key'
        os.environ['POLYGON_API_KEY'] = 'test_key'
        
        test_capitals = [10000, 50000, 100000, 500000]
        
        for capital in test_capitals:
            # Vectorized backtester
            vec_backtester = VectorizedBacktester()
            vec_results = vec_backtester.run_backtest(
                signals=sample_signals,
                data=sample_data,
                initial_capital=capital
            )
            vec_metrics = get_vectorized_metrics(vec_results)
            
            # Event-driven backtester
            evt_backtester = EventDrivenBacktester()
            evt_results = evt_backtester.run_backtest(
                signals=sample_signals,
                data=sample_data,
                initial_capital=capital
            )
            evt_metrics = get_event_driven_metrics(evt_results)
            
            # Both should respect the initial capital
            assert vec_metrics["initial_capital"] == capital
            assert evt_metrics["initial_capital"] == capital


if __name__ == "__main__":
    # Run tests if executed directly
    pytest.main([__file__, "-v"])
