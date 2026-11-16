import pytest
import pandas as pd
import numpy as np
from alpha.validation.metrics import (
    calculate_profit_attribution_by_factor_tca,
    calculate_factor_timing_attribution,
    calculate_brinson_attribution,
)


class TestCalculateProfitAttributionByFactorTCA:
    """Tests for calculate_profit_attribution_by_factor_tca function"""
    
    def setup_method(self):
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        
        self.factor_returns = pd.DataFrame({
            'momentum': np.random.normal(0.0005, 0.015, 100),
            'value': np.random.normal(0.0003, 0.012, 100),
        }, index=dates)
        
        self.factor_weights = pd.DataFrame(
            0.5, index=dates, columns=['momentum', 'value']
        )
        
        self.transaction_costs = pd.DataFrame(
            0.001, index=dates, columns=['momentum', 'value']
        )
    
    def test_normal_case(self):
        result = calculate_profit_attribution_by_factor_tca(
            self.factor_returns, self.factor_weights, self.transaction_costs
        )
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert set(result.columns) == {'factor', 'total_return', 'attribution', 'costs', 'net_attribution', 'contribution_pct'}
        assert set(result['factor']) == {'momentum', 'value'}
        # Net attribution should be less than gross attribution
        for _, row in result.iterrows():
            assert row['net_attribution'] <= row['attribution']
    
    def test_empty_dataframes(self):
        result = calculate_profit_attribution_by_factor_tca(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
    
    def test_costs_reduce_attribution(self):
        """Test that costs reduce net attribution"""
        result = calculate_profit_attribution_by_factor_tca(
            self.factor_returns, self.factor_weights, self.transaction_costs
        )
        for _, row in result.iterrows():
            assert row['net_attribution'] == pytest.approx(row['attribution'] - row['costs'])


class TestCalculateFactorTimingAttribution:
    """Tests for calculate_factor_timing_attribution function"""
    
    def setup_method(self):
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        
        self.factor_returns = pd.DataFrame({
            'momentum': np.random.normal(0.0005, 0.015, 100),
            'value': np.random.normal(0.0003, 0.012, 100),
        }, index=dates)
        
        self.factor_weights = pd.DataFrame(
            0.5, index=dates, columns=['momentum', 'value']
        )
        
        self.benchmark_weights = pd.DataFrame(
            0.5, index=dates, columns=['momentum', 'value']
        )
    
    def test_normal_case(self):
        result = calculate_factor_timing_attribution(
            self.factor_returns, self.factor_weights, self.benchmark_weights
        )
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert set(result.columns) == {'factor', 'allocation', 'selection', 'interaction', 'total_effect'}
        assert set(result['factor']) == {'momentum', 'value'}
        # With equal weights, allocation should be 0
        assert (result['allocation'] == 0).all()
    
    def test_misaligned_indices(self):
        dates1 = pd.date_range('2023-01-01', periods=100, freq='D')
        dates2 = pd.date_range('2023-05-01', periods=80, freq='D')
        
        returns = pd.DataFrame({'factor1': np.random.normal(0, 0.01, 100)}, index=dates1)
        weights = pd.DataFrame(0.5, index=dates1, columns=['factor1'])
        bench = pd.DataFrame(0.5, index=dates2, columns=['factor1'])
        
        result = calculate_factor_timing_attribution(returns, weights, bench)
        assert isinstance(result, pd.DataFrame)
        # Should only use intersection


class TestCalculateBrinsonAttribution:
    """Tests for calculate_brinson_attribution function"""
    
    def setup_method(self):
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        
        self.portfolio_returns = pd.Series(np.random.normal(0.001, 0.02, 100), index=dates)
        self.benchmark_returns = pd.Series(np.random.normal(0.0005, 0.015, 100), index=dates)
        
        self.portfolio_weights = pd.DataFrame(
            0.5, index=dates, columns=['asset1', 'asset2']
        )
        self.benchmark_weights = pd.DataFrame(
            0.5, index=dates, columns=['asset1', 'asset2']
        )
    
    def test_normal_case(self):
        result = calculate_brinson_attribution(
            self.portfolio_returns, 
            pd.Series(np.random.normal(0.001, 0.02, 100), index=pd.date_range('2023-01-01', periods=100, freq='D')),
            self.portfolio_weights,
            self.benchmark_weights
        )
        
        assert isinstance(result, dict)
        assert 'total' in result
        assert 'by_asset' in result
        assert 'by_sector' in result
        
        assert isinstance(result['total'], pd.DataFrame)
        assert isinstance(result['by_asset'], pd.DataFrame)
        assert isinstance(result['by_sector'], pd.DataFrame)
        
        # Total should have expected columns
        total_cols = result['total'].columns
        assert 'total_portfolio_return' in result['total'].columns
        assert 'total_benchmark_return' in result['total'].columns
        assert 'total_excess_return' in result['total'].columns
    
    def test_with_sector_returns(self):
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        sector_returns = pd.DataFrame({
            'tech': np.random.normal(0.001, 0.02, 100),
            'healthcare': np.random.normal(0.0005, 0.015, 100),
        }, index=dates)
        
        result = calculate_brinson_attribution(
            pd.Series(np.random.normal(0.001, 0.02, 100), index=dates),
            pd.Series(np.random.normal(0.0005, 0.015, 100), index=dates),
            pd.DataFrame(0.5, index=pd.date_range('2023-01-01', periods=100, freq='D'), columns=['tech', 'healthcare']),
            pd.DataFrame(0.5, index=pd.date_range('2023-01-01', periods=100, freq='D'), columns=['tech', 'healthcare']),
            sector_returns=pd.DataFrame({
                'tech': np.random.normal(0.001, 0.02, 100),
                'healthcare': np.random.normal(0.0005, 0.015, 100),
            }, index=dates)
        )
        
        assert 'by_sector' in result
        assert len(result['by_sector']) == 2
        assert 'tech' in result['by_sector']['sector'].values
        assert 'healthcare' in result['by_sector']['sector'].values
    
    def test_empty_inputs(self):
        result = calculate_brinson_attribution(
            pd.Series(), pd.Series(), pd.DataFrame(), pd.DataFrame()
        )
        assert isinstance(result, dict)
        assert len(result['total']) == 0
        assert len(result['by_asset']) == 0
        assert len(result['by_sector']) == 0
