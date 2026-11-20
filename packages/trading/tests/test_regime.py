"""
Tests for Regime Detection Module
"""
import numpy as np
import pandas as pd
import pytest
from alpha.factors.regime import (
    RegimeType,
    RegimeState,
    VolatilityRegimeDetector,
    HMMRegimeDetector,
    RegimeDetector,
    detect_regime,
    get_current_regime,
)


class TestRegimeType:
    def test_regime_types_exist(self):
        assert RegimeType.TREND_UP.value == "trend_up"
        assert RegimeType.TREND_DOWN.value == "trend_down"
        assert RegimeType.MEAN_REVERSION.value == "mean_reversion"
        assert RegimeType.VOLATILE.value == "volatile"
        assert RegimeType.UNKNOWN.value == "unknown"


class TestRegimeState:
    def test_regime_state_creation(self):
        state = RegimeState(
            regime=RegimeType.TREND_UP,
            confidence=0.9,
            start_idx=0,
            end_idx=100,
            params={'mean': 0.001, 'vol': 0.01}
        )
        assert state.regime == RegimeType.TREND_UP
        assert state.confidence == 0.9
        assert state.start_idx == 0
        assert state.end_idx == 100


class TestVolatilityRegimeDetector:
    def test_detect_unknown_for_short_series(self):
        detector = VolatilityRegimeDetector(window=60)
        returns = pd.Series(np.random.normal(0, 0.01, 50))
        regimes = detector.detect(returns)
        assert len(regimes) == 1
        assert regimes[0].regime == RegimeType.UNKNOWN
    
    def test_detect_trend_up(self):
        detector = VolatilityRegimeDetector(window=20, vol_threshold_high=0.02)
        # Strong positive trend, moderate vol
        returns = pd.Series(np.random.normal(0.002, 0.01, 200))
        regimes = detector.detect(returns)
        assert len(regimes) >= 1
        # At least one regime should be trend_up
        trend_regimes = [r for r in regimes if r.regime == RegimeType.TREND_UP]
        assert len(trend_regimes) > 0
    
    def test_detect_volatile(self):
        detector = VolatilityRegimeDetector(window=20, vol_threshold_high=0.02)
        # High volatility
        returns = pd.Series(np.random.normal(0.0, 0.05, 200))
        regimes = detector.detect(returns)
        volatile_regimes = [r for r in regimes if r.regime == RegimeType.VOLATILE]
        assert len(volatile_regimes) > 0
    
    def test_detect_mean_reversion(self):
        detector = VolatilityRegimeDetector(window=20, vol_threshold_low=0.015)
        # Low volatility
        returns = pd.Series(np.random.normal(0.0, 0.005, 200))
        regimes = detector.detect(returns)
        mr_regimes = [r for r in regimes if r.regime == RegimeType.MEAN_REVERSION]
        assert len(mr_regimes) > 0


class TestHMMRegimeDetector:
    def test_fit_predict(self):
        np.random.seed(42)
        returns = np.concatenate([
            np.random.normal(0.001, 0.01, 100),
            np.random.normal(-0.001, 0.005, 100),
            np.random.normal(0.0, 0.03, 100),
        ])
        
        detector = HMMRegimeDetector(n_states=3, self_transition_prob=0.99)
        detector.fit(returns)
        
        regimes = detector.get_regime_sequence(returns)
        assert len(regimes) >= 2  # At least 2 regimes (trend and volatile)
        assert all(isinstance(r, RegimeState) for r in regimes)
        assert all(r.start_idx <= r.end_idx for r in regimes if r.end_idx is not None)
    
    def test_predict_regimes_shape(self):
        np.random.seed(42)
        returns = np.random.normal(0.0005, 0.015, 300)
        
        detector = HMMRegimeDetector(n_states=3)
        detector.fit(returns)
        states = detector.predict_regimes(returns)
        
        assert len(states) == len(returns)
        assert states.min() >= 0
        assert states.max() < 3
    
    def test_three_distinct_regimes(self):
        np.random.seed(42)
        # Create clearly separable regimes with more distinct characteristics
        returns = np.concatenate([
            np.random.normal(0.005, 0.005, 100),   # Strong trend up, low vol
            np.random.normal(-0.005, 0.005, 100),  # Strong trend down, low vol
            np.random.normal(0.0, 0.04, 100),      # Volatile
        ])
        
        detector = HMMRegimeDetector(n_states=3, self_transition_prob=0.99)
        detector.fit(returns)
        regimes = detector.get_regime_sequence(returns)
        
        # Should detect at least 2 regimes (trend and volatile)
        assert len(regimes) >= 2
        # Check we have different regime types
        regime_types = {r.regime for r in regimes}
        assert len(regime_types) >= 2  # At least 2 distinct types


class TestRegimeDetector:
    def test_volatility_method(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.01, 200))
        
        detector = RegimeDetector(method="volatility")
        regimes = detector.detect(returns)
        
        assert len(regimes) >= 1
        assert all(isinstance(r, RegimeState) for r in regimes)
    
    def test_hmm_method(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0005, 0.015, 300))
        
        detector = RegimeDetector(method="hmm")
        regimes = detector.detect(returns)
        
        assert len(regimes) >= 1
        assert all(isinstance(r, RegimeState) for r in regimes)
    
    def test_ensemble_method(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0005, 0.015, 300))
        
        detector = RegimeDetector(method="ensemble")
        regimes = detector.detect(returns)
        
        assert len(regimes) >= 1
        assert all(isinstance(r, RegimeState) for r in regimes)
    
    def test_invalid_method(self):
        with pytest.raises(ValueError):
            RegimeDetector(method="invalid_method")


class TestConvenienceFunctions:
    def test_detect_regime_function(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.01, 200))
        
        regimes = detect_regime(returns, method="volatility")
        assert len(regimes) >= 1
        
        regimes = detect_regime(returns, method="hmm")
        assert len(regimes) >= 1
        
        regimes = detect_regime(returns, method="ensemble")
        assert len(regimes) >= 1
    
    def test_get_current_regime(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.01, 200))
        
        current = get_current_regime(returns, method="volatility")
        assert isinstance(current, RegimeState)


class TestRegimePersistence:
    def test_regime_persistence_in_trend(self):
        """Test that trend regimes persist appropriately"""
        np.random.seed(42)
        # Strong trend should have fewer regime changes
        returns = pd.Series(np.cumsum(np.random.normal(0.005, 0.005, 300)))
        returns = returns.diff().dropna()
        
        detector = RegimeDetector(method="volatility")
        regimes = detector.detect(returns)
        
        # In a strong trend with vol detector, should have very few regime switches
        assert len(regimes) <= 3  # Very few switches for clear trend
    
    def test_regime_switches_in_volatile(self):
        """Test that volatile periods show more regime changes"""
        np.random.seed(42)
        # Alternating high/low vol
        returns_list = []
        for i in range(6):
            if i % 2 == 0:
                returns_list.append(np.random.normal(0, 0.005, 50))  # Low vol
            else:
                returns_list.append(np.random.normal(0, 0.04, 50))   # High vol
        returns = pd.Series(np.concatenate(returns_list))
        
        detector = RegimeDetector(method="volatility")
        regimes = detector.detect(returns)
        
        # Should detect at least some regime changes
        assert len(regimes) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])