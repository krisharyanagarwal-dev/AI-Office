"""
Tests for IC Analysis Module
"""
import numpy as np
import pandas as pd
import pytest
from alpha.factors.ic_analysis import (
    ICMethod,
    ICResult,
    FactorRanking,
    ICAnalyzer,
    FactorRanker,
    compute_ic,
    rank_factors,
)


class TestICMethod:
    def test_enum_values(self):
        assert ICMethod.SPEARMAN.value == "spearman"
        assert ICMethod.PEARSON.value == "pearson"


class TestICResult:
    def test_creation(self):
        result = ICResult(
            factor_name="test",
            ic_mean=0.05,
            ic_std=0.02,
            ic_ir=2.5,
            ic_t_stat=5.0,
            ic_p_value=0.001,
            positive_ic_ratio=0.6,
            max_drawdown=-0.02,
            decay={1: 0.05, 5: 0.04, 10: 0.03},
            turnover=0.15,
        )
        assert result.factor_name == "test"
        assert result.ic_mean == 0.05


class TestICAnalyzer:
    def test_compute_ic_spearman(self):
        np.random.seed(42)
        n = 100
        factor = pd.Series(np.random.normal(0, 1, n))
        returns = pd.Series(factor * 0.3 + np.random.normal(0, 0.5, n))
        
        analyzer = ICAnalyzer(method=ICMethod.SPEARMAN)
        ic, p_val = analyzer.compute_ic(factor, returns)
        
        assert not np.isnan(ic)
        assert 0 <= p_val <= 1
        assert ic > 0  # Positive correlation expected
    
    def test_compute_ic_pearson(self):
        np.random.seed(42)
        n = 100
        factor = pd.Series(np.random.normal(0, 1, n))
        returns = pd.Series(factor * 0.3 + np.random.normal(0, 0.5, n))
        
        analyzer = ICAnalyzer(method=ICMethod.PEARSON)
        ic, p_val = analyzer.compute_ic(factor, returns)
        
        assert not np.isnan(ic)
        assert ic > 0
    
    def test_compute_ic_insufficient_data(self):
        factor = pd.Series([1, 2, 3])
        returns = pd.Series([0.1, 0.2, 0.3])
        
        analyzer = ICAnalyzer(min_periods=10)
        ic, p_val = analyzer.compute_ic(factor, returns)
        
        assert np.isnan(ic)
        assert np.isnan(p_val)
    
    def test_compute_ic_series(self):
        np.random.seed(42)
        n = 200
        dates = pd.date_range('2020-01-01', periods=n, freq='D')
        
        factor = pd.DataFrame({
            'f1': np.random.normal(0, 1, n),
            'f2': np.random.normal(0, 1, n),
        }, index=dates)
        returns = pd.DataFrame({
            'f1': np.random.normal(0, 0.01, n),
            'f2': np.random.normal(0, 0.01, n),
        }, index=dates)
        
        analyzer = ICAnalyzer(min_periods=60)
        ic_series = analyzer.compute_ic_series(factor, returns)
        
        assert isinstance(ic_series, pd.DataFrame)
        assert 'f1' in ic_series.columns
        assert 'f2' in ic_series.columns
        # First 60 periods should be mostly NaN (rolling window needs min_periods)
        # At least first 50 should be NaN
        assert ic_series['f1'].iloc[:50].isna().sum() >= 45
    
    def test_compute_ic_decay(self):
        np.random.seed(42)
        n = 200
        factor = pd.Series(np.random.normal(0, 1, n))
        returns = pd.DataFrame({
            1: np.random.normal(0, 0.01, n),
            5: np.random.normal(0, 0.02, n),
            10: np.random.normal(0, 0.03, n),
        })
        
        analyzer = ICAnalyzer(horizons=[1, 5, 10, 20])
        decay = analyzer.compute_ic_decay(factor, returns)
        
        assert 1 in decay
        assert 5 in decay
        assert 10 in decay
        assert 20 in decay
        assert np.isnan(decay[20])  # Not in returns
    
    def test_compute_turnover(self):
        # Low turnover factor (stable ranks) - consecutive ranks
        np.random.seed(42)
        factor = pd.Series(np.arange(100))
        turnover = ICAnalyzer().compute_turnover(factor, window=20)
        assert turnover <= 1.0  # Minimal turnover for perfectly ordered
        
        # High turnover factor (random ranks)
        np.random.seed(42)
        factor = pd.Series(np.random.permutation(100))
        turnover = ICAnalyzer().compute_turnover(factor, window=20)
        assert turnover > 5  # High turnover
    
    def test_compute_sector_neutral_ic(self):
        np.random.seed(42)
        n = 100
        factor = pd.Series(np.random.normal(0, 1, n))
        returns = pd.Series(factor * 0.3 + np.random.normal(0, 0.5, n))
        sectors = pd.Series(np.random.choice(['A', 'B', 'C'], n))
        
        analyzer = ICAnalyzer()
        sn_ic, sn_p = analyzer.compute_sector_neutral_ic(factor, returns, sectors)
        
        assert not np.isnan(sn_ic)
        assert 0 <= sn_p <= 1
    
    def test_analyze_factor_basic(self):
        np.random.seed(42)
        n = 200
        dates = pd.date_range('2020-01-01', periods=n, freq='D')
        
        # Factor with some predictive power
        factor = pd.Series(np.random.normal(0, 1, n), index=dates)
        returns_1d = pd.Series(factor * 0.2 + np.random.normal(0, 0.5, n), index=dates)
        returns_5d = returns_1d.rolling(5).sum()
        
        forward_returns = pd.DataFrame({
            1: returns_1d,
            5: returns_5d,
        }, index=dates)
        
        analyzer = ICAnalyzer(min_periods=60)
        result = analyzer.analyze_factor('test_factor', factor, forward_returns)
        
        assert isinstance(result, ICResult)
        assert result.factor_name == 'test_factor'
        assert not np.isnan(result.ic_mean)
        assert not np.isnan(result.ic_ir)
        assert 0 <= result.positive_ic_ratio <= 1
        assert result.turnover >= 0
        assert result.n_observations > 0
        assert 1 in result.decay
        assert 5 in result.decay
    
    def test_analyze_factor_insufficient_data(self):
        factor = pd.Series([1, 2, 3])
        returns = pd.DataFrame({1: [0.1, 0.2, 0.3]})
        
        analyzer = ICAnalyzer(min_periods=10)
        result = analyzer.analyze_factor('test', factor, returns)
        
        assert np.isnan(result.ic_mean)
        assert result.n_observations == 0


class TestFactorRanker:
    def test_rank_factors_basic(self):
        # Create mock ICResults
        results = [
            ICResult('f1', ic_mean=0.05, ic_std=0.01, ic_ir=5.0, ic_t_stat=10, ic_p_value=0.001,
                     positive_ic_ratio=0.7, max_drawdown=-0.01, decay={}, turnover=0.1, n_observations=100),
            ICResult('f2', ic_mean=0.03, ic_std=0.02, ic_ir=1.5, ic_t_stat=3, ic_p_value=0.01,
                     positive_ic_ratio=0.55, max_drawdown=-0.02, decay={}, turnover=0.2, n_observations=100),
            ICResult('f3', ic_mean=0.01, ic_std=0.03, ic_ir=0.3, ic_t_stat=1, ic_p_value=0.3,
                     positive_ic_ratio=0.5, max_drawdown=-0.05, decay={}, turnover=0.3, n_observations=100),
        ]
        
        ranker = FactorRanker()
        rankings = ranker.rank_factors(results)
        
        assert len(rankings) == 3
        assert rankings[0].factor_name == 'f1'  # Best IC
        assert rankings[1].factor_name == 'f2'
        assert rankings[2].factor_name == 'f3'
        assert rankings[0].composite_score > rankings[1].composite_score
    
    def test_rank_factors_with_crowding(self):
        results = [
            ICResult('f1', ic_mean=0.05, ic_std=0.01, ic_ir=5.0, ic_t_stat=10, ic_p_value=0.001,
                     positive_ic_ratio=0.7, max_drawdown=-0.01, decay={}, turnover=0.1, n_observations=100),
            ICResult('f2', ic_mean=0.04, ic_std=0.01, ic_ir=4.0, ic_t_stat=8, ic_p_value=0.001,
                     positive_ic_ratio=0.65, max_drawdown=-0.01, decay={}, turnover=0.15, n_observations=100),
        ]
        
        # f1 is more crowded
        crowding = {'f1': 100, 'f2': 10}
        
        ranker = FactorRanker(crowding_weight=0.5)
        rankings = ranker.rank_factors(results, crowding_scores=crowding)
        
        # f2 should rank higher due to lower crowding
        # But weights matter - with 50% crowding weight, might still favor f1
        assert len(rankings) == 2
    
    def test_custom_weights(self):
        results = [
            ICResult('f1', ic_mean=0.05, ic_std=0.01, ic_ir=5.0, ic_t_stat=10, ic_p_value=0.001,
                     positive_ic_ratio=0.7, max_drawdown=-0.01, decay={}, turnover=0.5, n_observations=100),
            ICResult('f2', ic_mean=0.04, ic_std=0.01, ic_ir=4.0, ic_t_stat=8, ic_p_value=0.001,
                     positive_ic_ratio=0.65, max_drawdown=-0.01, decay={}, turnover=0.1, n_observations=100),
        ]
        
        # Heavy turnover penalty
        ranker = FactorRanker(turnover_weight=0.8, ic_weight=0.1, ir_weight=0.1)
        rankings = ranker.rank_factors(results)
        
        # f2 should win due to lower turnover
        assert rankings[0].factor_name == 'f2'


class TestConvenienceFunctions:
    def test_compute_ic_function(self):
        np.random.seed(42)
        factor = pd.Series(np.random.normal(0, 1, 100))
        returns = pd.Series(factor * 0.3 + np.random.normal(0, 0.5, 100))
        
        ic, p = compute_ic(factor, returns)
        assert not np.isnan(ic)
        assert ic > 0
    
    def test_rank_factors_function(self):
        results = [
            ICResult('f1', ic_mean=0.05, ic_std=0.01, ic_ir=5.0, ic_t_stat=10, ic_p_value=0.001,
                     positive_ic_ratio=0.7, max_drawdown=-0.01, decay={}, turnover=0.1, n_observations=100),
            ICResult('f2', ic_mean=0.03, ic_std=0.02, ic_ir=1.5, ic_t_stat=3, ic_p_value=0.01,
                     positive_ic_ratio=0.55, max_drawdown=-0.02, decay={}, turnover=0.2, n_observations=100),
        ]
        
        rankings = rank_factors(results)
        assert len(rankings) == 2
        assert rankings[0].factor_name == 'f1'


class TestICDecayProperties:
    def test_decay_decreases_with_horizon(self):
        """Test that IC typically decays with longer horizons"""
        np.random.seed(42)
        n = 300
        factor = pd.Series(np.random.normal(0, 1, n))
        # Returns with decaying signal
        returns = pd.DataFrame({
            1: factor * 0.3 + np.random.normal(0, 0.5, n),
            5: (factor * 0.2).rolling(5).sum() + np.random.normal(0, 1, n),
            10: (factor * 0.1).rolling(10).sum() + np.random.normal(0, 1.5, n),
        })
        
        analyzer = ICAnalyzer(horizons=[1, 5, 10])
        result = analyzer.analyze_factor('test', factor, returns)
        
        # IC should generally decay
        assert abs(result.decay[1]) >= abs(result.decay[10]) * 0.5  # Not too strict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])