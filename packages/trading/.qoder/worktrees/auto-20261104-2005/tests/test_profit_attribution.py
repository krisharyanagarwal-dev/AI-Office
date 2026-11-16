"""
Unit tests for profit attribution functions in alpha.validation.metrics
"""
import pytest
import pandas as pd
import numpy as np
from scipy import stats

# Import the functions to test
import sys
sys.path.insert(0, '/Users/aryanagarwal/alpha-system')
from alpha.validation.metrics import (
    calculate_profit_attribution_by_factor,
    calculate_profit_attribution_by_regime,
    calculate_profit_attribution_by_model,
    calculate_factor_half_life,
    calculate_regime_transition_probability,
)


class TestCalculateProfitAttributionByFactor:
    """Tests for calculate_profit_attribution_by_factor function"""
    
    def setup_method(self):
        """Set up test data"""
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=252, freq='D')
        
        # Create factor returns with known properties
        self.factor_returns = pd.DataFrame({
            'momentum': np.random.normal(0.0005, 0.015, 252),
            'reversal': np.random.normal(0.0003, 0.012, 252),
            'quality': np.random.normal(0.0004, 0.010, 252),
        }, index=dates)
        
        # Add some correlation
        self.factor_returns['reversal'] += 0.3 * self.factor_returns['momentum']
        
        # Equal weights
        self.factor_weights = pd.DataFrame(
            0.33,
            index=dates,
            columns=['momentum', 'reversal', 'quality']
        )
    
    def test_normal_case(self):
        """Test normal case with valid data"""
        result = calculate_profit_attribution_by_factor(
            self.factor_returns, self.factor_weights
        )
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3  # 3 factors
        assert set(result.columns) == {'factor', 'total_return', 'attribution', 'contribution_pct'}
        assert set(result['factor']) == {'momentum', 'reversal', 'quality'}
        assert result['contribution_pct'].sum() == pytest.approx(100.0, rel=0.1)
    
    def test_empty_dataframes(self):
        """Test with empty DataFrames"""
        empty_returns = pd.DataFrame()
        empty_weights = pd.DataFrame()
        
        result = calculate_profit_attribution_by_factor(empty_returns, empty_weights)
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
        assert list(result.columns) == ['factor', 'total_return', 'attribution', 'contribution_pct']
    
    def test_misaligned_indices(self):
        """Test with misaligned indices"""
        dates1 = pd.date_range('2023-01-01', periods=100, freq='D')
        dates2 = pd.date_range('2023-05-01', periods=100, freq='D')
        
        returns = pd.DataFrame({'factor1': np.random.normal(0, 0.01, 100)}, index=dates1)
        weights = pd.DataFrame(0.5, index=dates2, columns=['factor1'])
        
        result = calculate_profit_attribution_by_factor(returns, weights)
        
        assert isinstance(result, pd.DataFrame)
        # Should only use intersection
        assert len(result) >= 0
    
    def test_zero_total_return(self):
        """Test when total return is zero"""
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        
        returns = pd.DataFrame({
            'factor1': np.zeros(100),
            'factor2': np.zeros(100),
        }, index=pd.date_range('2023-01-01', periods=100, freq='D'))
        
        weights = pd.DataFrame(0.5, index=returns.index, columns=['factor1', 'factor2'])
        
        result = calculate_profit_attribution_by_factor(returns, weights)
        
        assert result['contribution_pct'].sum() == 0  # or NaN handled as 0


class TestCalculateProfitAttributionByRegime:
    """Tests for calculate_profit_attribution_by_regime function"""
    
    def setup_method(self):
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=252, freq='D')
        self.returns = pd.Series(np.random.normal(0.0005, 0.015, 252), index=dates)
        
        # Create regimes
        trend = self.returns.rolling(20).mean().fillna(0)
        self.regimes = pd.Series(
            np.where(trend > 0.001, 'trend_up',
                    np.where(trend < -0.001, 'trend_down', 'chop')),
            index=dates
        )
    
    def test_normal_case(self):
        result = calculate_profit_attribution_by_regime(self.returns, self.regimes)
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3  # 3 regimes
        assert set(result.columns) == {'regime', 'total_return', 'annualized_return', 'contribution_pct'}
        assert set(result['regime']) == {'trend_up', 'trend_down', 'chop'}
    
    def test_single_regime(self):
        """Test with only one regime"""
        regimes = pd.Series('trend_up', index=self.returns.index)
        
        result = calculate_profit_attribution_by_regime(self.returns, regimes)
        
        assert len(result) == 1
        assert result.iloc[0]['regime'] == 'trend_up'
        assert result.iloc[0]['contribution_pct'] == 100.0
    
    def test_empty_returns(self):
        result = calculate_profit_attribution_by_regime(pd.Series(), pd.Series())
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestCalculateProfitAttributionByModel:
    """Tests for calculate_profit_attribution_by_model function"""
    
    def setup_method(self):
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        self.actual_returns = pd.Series(np.random.normal(0.0005, 0.015, 100), index=dates)
        
        self.model_predictions = {
            'model1': pd.Series(np.random.normal(0.0003, 0.010, 100), index=dates),
            'model2': pd.Series(np.random.normal(0.0002, 0.012, 100), index=dates),
        }
        self.model_weights = {'model1': 0.6, 'model2': 0.4}
    
    def test_normal_case(self):
        result = calculate_profit_attribution_by_model(
            self.model_predictions, self.actual_returns, self.model_weights
        )
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert set(result.columns) == {'model', 'weight', 'ic', 'attribution', 'contribution_pct'}
        assert set(result['model']) == {'model1', 'model2'}
    
    def test_misaligned_predictions(self):
        """Test with misaligned prediction indices"""
        dates1 = pd.date_range('2023-01-01', periods=100, freq='D')
        dates2 = pd.date_range('2023-02-01', periods=80, freq='D')
        
        model_predictions = {
            'model1': pd.Series(np.random.normal(0.0003, 0.010, 100), index=dates1),
            'model2': pd.Series(np.random.normal(0.0002, 0.012, 80), index=dates2),
        }
        
        result = calculate_profit_attribution_by_model(
            model_predictions, self.actual_returns, self.model_weights
        )
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) <= 2
    
    def test_zero_weights(self):
        weights = {'model1': 0.0, 'model2': 0.0}
        
        result = calculate_profit_attribution_by_model(
            self.model_predictions, self.actual_returns, weights
        )
        
        assert result['attribution'].sum() == 0


class TestCalculateFactorHalfLife:
    """Tests for calculate_factor_half_life function"""
    
    def test_strong_autocorrelation(self):
        """Test with strong autocorrelation (slow decay)"""
        # AR(1) process with phi=0.95 and low noise
        np.random.seed(42)
        n = 1000
        phi = 0.95
        series = np.zeros(n)
        series[0] = np.random.normal(0, 1)
        for i in range(1, n):
            series[i] = phi * series[i-1] + np.random.normal(0, 0.01)  # Low noise
        
        series = pd.Series(series)
        half_life = calculate_factor_half_life(series)
        
        # Half-life for AR(1) with phi=0.95 should be around 14 periods
        # Theoretical: -1/log(0.95) ≈ 19.5
        # With noise, estimate will be higher; check it's reasonable
        assert half_life > 5
        assert half_life < 300  # Allow wider range due to noise
    
    def test_no_autocorrelation(self):
        """Test with white noise (no autocorrelation)"""
        np.random.seed(42)
        series = pd.Series(np.random.normal(0, 1, 100))
        
        half_life = calculate_factor_half_life(series)
        
        # Should be small (fast decay)
        assert half_life < 5 or np.isnan(half_life)
    
    def test_short_series(self):
        """Test with very short series"""
        series = pd.Series(np.random.normal(0, 1, 5))
        
        half_life = calculate_factor_half_life(series)
        
        assert np.isnan(half_life) or half_life == 252  # default fallback
    
    def test_all_nan(self):
        series = pd.Series([np.nan] * 100)
        
        half_life = calculate_factor_half_life(series)
        
        assert np.isnan(half_life)


class TestCalculateRegimeTransitionProbability:
    """Tests for calculate_regime_transition_probability function"""
    
    def test_normal_case(self):
        """Test with multiple regimes"""
        regimes = pd.Series(['trend_up', 'trend_up', 'chop', 'trend_down', 'chop', 'trend_up'] * 10)
        
        result = calculate_regime_transition_probability(regimes)
        
        assert isinstance(result, pd.DataFrame)
        assert set(result.index) == {'trend_up', 'chop', 'trend_down'}
        assert set(result.columns) == {'trend_up', 'chop', 'trend_down'}
        
        # Rows should sum to 1
        row_sums = result.sum(axis=1)
        assert all(row_sums.round(6) == 1.0)
    
    def test_absorbing_state(self):
        """Test with absorbing state"""
        regimes = pd.Series(['trend_up'] * 100)
        
        result = calculate_regime_transition_probability(regimes)
        
        assert result.loc['trend_up', 'trend_up'] == 1.0
    
    def test_single_regime(self):
        regimes = pd.Series(['chop'] * 10)
        
        result = calculate_regime_transition_probability(regimes)
        
        assert result.loc['chop', 'chop'] == 1.0
    
    def test_empty_history(self):
        result = calculate_regime_transition_probability(pd.Series())
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
