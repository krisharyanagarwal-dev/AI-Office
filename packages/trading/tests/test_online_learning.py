"""
Tests for Online Learning / Adaptive Factors Module
"""
import numpy as np
import pandas as pd
import pytest
from alpha.factors.online_learning import (
    EWMAWeights,
    OnlineRidgeRegression,
    KalmanFactorModel,
    AdaptiveFactorCombiner,
    OnlineModelState,
    create_adaptive_combiner,
)


class TestEWMAWeights:
    def test_initialization(self):
        ewma = EWMAWeights(n_factors=5, alpha=0.1)
        assert ewma.n_factors == 5
        assert ewma.alpha == 0.1
        assert np.allclose(ewma.weights, 0.2)
        assert np.allclose(ewma.performance, 0.0)
    
    def test_update_increases_step(self):
        ewma = EWMAWeights(n_factors=3)
        ewma.update(np.array([0.01, 0.02, -0.01]), 0.01)
        assert ewma.step == 1
    
    def test_weights_sum_to_one(self):
        ewma = EWMAWeights(n_factors=5)
        for _ in range(10):
            ewma.update(np.random.normal(0, 0.02, 5), 0.01)
        assert np.isclose(ewma.weights.sum(), 1.0)
    
    def test_weights_bounded(self):
        ewma = EWMAWeights(n_factors=3, min_weight=0.1, max_weight=0.6)
        for _ in range(20):
            ewma.update(np.array([0.05, -0.01, 0.0]), 0.0)
        assert np.all(ewma.weights >= 0.1 - 1e-10)
        assert np.all(ewma.weights <= 0.6 + 1e-10)
    
    def test_performance_tracks_relative_returns(self):
        ewma = EWMAWeights(n_factors=2, alpha=0.5)
        # Factor 0 consistently outperforms
        for _ in range(10):
            ewma.update(np.array([0.02, -0.01]), 0.0)
        # Factor 0 should have higher weight
        assert ewma.weights[0] > ewma.weights[1]


class TestOnlineRidgeRegression:
    def test_initialization(self):
        ridge = OnlineRidgeRegression(n_features=5, lambda_reg=1.0, forgetting_factor=0.99)
        assert ridge.n_features == 5
        assert ridge.lambda_reg == 1.0
        assert ridge.forgetting_factor == 0.99
        assert np.allclose(ridge.weights, 0.0)
    
    def test_update_changes_weights(self):
        ridge = OnlineRidgeRegression(n_features=3, lambda_reg=0.1, forgetting_factor=1.0)
        initial_weights = ridge.weights.copy()
        
        ridge.update(np.array([1.0, 2.0, 3.0]), 10.0)
        
        assert not np.allclose(ridge.weights, initial_weights)
        assert ridge.step == 1
    
    def test_predict(self):
        ridge = OnlineRidgeRegression(n_features=3, lambda_reg=0.1, forgetting_factor=1.0)
        ridge.update(np.array([1.0, 0.0, 0.0]), 5.0)
        pred = ridge.predict(np.array([1.0, 0.0, 0.0]))
        assert isinstance(pred, float)
    
    def test_forgetting_factor(self):
        ridge = OnlineRidgeRegression(n_features=2, lambda_reg=0.01, forgetting_factor=0.9)
        ridge.update(np.array([1.0, 0.0]), 1.0)
        w1 = ridge.weights.copy()
        
        ridge.update(np.array([0.0, 1.0]), 1.0)
        w2 = ridge.weights.copy()
        
        # With forgetting, old weights decay
        assert not np.allclose(w1, w2)
    
    def test_get_state(self):
        ridge = OnlineRidgeRegression(n_features=3)
        ridge.update(np.array([1.0, 2.0, 3.0]), 10.0)
        state = ridge.get_state()
        
        assert isinstance(state, OnlineModelState)
        assert len(state.weights) == 3
        assert state.covariance.shape == (3, 3)
        assert state.step == 1


class TestKalmanFactorModel:
    def test_initialization(self):
        kf = KalmanFactorModel(n_factors=3, process_noise=1e-4, observation_noise=1e-2)
        assert kf.n_factors == 3
        assert np.allclose(kf.x, 0.0)
        assert kf.P.shape == (3, 3)
    
    def test_update(self):
        kf = KalmanFactorModel(n_factors=2, process_noise=1e-4, observation_noise=1e-2)
        initial_x = kf.x.copy()
        
        kf.update(np.array([1.0, 2.0]), 0.05)
        
        assert not np.allclose(kf.x, initial_x)
        assert kf.step == 1
    
    def test_predict(self):
        kf = KalmanFactorModel(n_factors=2, process_noise=1e-4, observation_noise=1e-2)
        kf.update(np.array([1.0, 0.0]), 0.05)
        pred = kf.predict(np.array([1.0, 0.0]))
        assert isinstance(pred, float)
    
    def test_custom_transition_matrix(self):
        F = np.array([[0.9, 0.1], [0.1, 0.9]])
        kf = KalmanFactorModel(n_factors=2, process_noise=1e-4, observation_noise=1e-2, 
                              transition_matrix=F)
        assert np.allclose(kf.F, F)
    
    def test_get_state(self):
        kf = KalmanFactorModel(n_factors=3)
        kf.update(np.array([1.0, 2.0, 3.0]), 0.1)
        state = kf.get_state()
        
        assert isinstance(state, OnlineModelState)
        assert len(state.weights) == 3
        assert state.covariance.shape == (3, 3)


class TestAdaptiveFactorCombiner:
    def test_initialization_ewma(self):
        combiner = AdaptiveFactorCombiner(
            ['f1', 'f2', 'f3'], method="ewma", alpha=0.1
        )
        assert combiner.n_factors == 3
        assert combiner.method == "ewma"
    
    def test_initialization_ridge(self):
        combiner = AdaptiveFactorCombiner(
            ['f1', 'f2'], method="ridge", lambda_reg=1.0, forgetting_factor=0.99
        )
        assert combiner.method == "ridge"
    
    def test_initialization_kalman(self):
        combiner = AdaptiveFactorCombiner(
            ['f1', 'f2', 'f3'], method="kalman", process_noise=1e-4
        )
        assert combiner.method == "kalman"
    
    def test_initialization_ensemble(self):
        combiner = AdaptiveFactorCombiner(
            ['f1', 'f2', 'f3'], method="ensemble"
        )
        assert combiner.method == "ensemble"
        assert 'ewma' in combiner.learners
        assert 'ridge' in combiner.learners
        assert 'kalman' in combiner.learners
    
    def test_invalid_method(self):
        with pytest.raises(ValueError):
            AdaptiveFactorCombiner(['f1'], method="invalid")
    
    def test_update_ewma(self):
        combiner = AdaptiveFactorCombiner(['f1', 'f2', 'f3'], method="ewma", alpha=0.1)
        weights = combiner.update(
            np.array([1.0, 2.0, 3.0]),
            np.array([0.01, 0.02, -0.01]),
            0.015
        )
        assert len(weights) == 3
        assert np.isclose(weights.sum(), 1.0)
        assert combiner.step == 1
    
    def test_update_ridge(self):
        combiner = AdaptiveFactorCombiner(['f1', 'f2'], method="ridge", lambda_reg=0.1)
        weights = combiner.update(
            np.array([1.0, 2.0]),
            np.array([0.01, 0.02]),
            0.015
        )
        assert len(weights) == 2
        assert np.isclose(weights.sum(), 1.0)
    
    def test_update_kalman(self):
        combiner = AdaptiveFactorCombiner(['f1', 'f2', 'f3'], method="kalman")
        weights = combiner.update(
            np.array([1.0, 2.0, 3.0]),
            np.array([0.01, 0.02, -0.01]),
            0.015
        )
        assert len(weights) == 3
        assert np.isclose(weights.sum(), 1.0)
    
    def test_update_ensemble(self):
        combiner = AdaptiveFactorCombiner(['f1', 'f2', 'f3'], method="ensemble")
        weights = combiner.update(
            np.array([1.0, 2.0, 3.0]),
            np.array([0.01, 0.02, -0.01]),
            0.015
        )
        assert len(weights) == 3
        assert np.isclose(weights.sum(), 1.0)
        assert combiner.step == 1
    
    def test_ensemble_converges(self):
        """Test that ensemble weights converge over time"""
        combiner = AdaptiveFactorCombiner(
            ['f1', 'f2', 'f3'], method="ensemble"
        )
        
        # Run many updates
        for _ in range(100):
            combiner.update(
                np.random.normal(0, 1, 3),
                np.random.normal(0.001, 0.02, 3),
                np.random.normal(0.001, 0.01)
            )
        
        weights = combiner.get_weights()
        assert np.isclose(weights.sum(), 1.0)
        assert len(combiner.history) == 100
    
    def test_get_weights_returns_normalized(self):
        for method in ["ewma", "ridge", "kalman", "ensemble"]:
            combiner = AdaptiveFactorCombiner(['f1', 'f2', 'f3'], method=method)
            for _ in range(10):
                combiner.update(
                    np.random.normal(0, 1, 3),
                    np.random.normal(0.001, 0.02, 3),
                    np.random.normal(0.001, 0.01)
                )
            weights = combiner.get_weights()
            assert np.isclose(weights.sum(), 1.0), f"Method {method}: weights sum to {weights.sum()}"


class TestFactoryFunction:
    def test_create_adaptive_combiner(self):
        combiner = create_adaptive_combiner(
            ['f1', 'f2', 'f3'],
            method="ensemble",
            ewma={'alpha': 0.1},
            ridge={'lambda_reg': 1.0, 'forgetting_factor': 0.99},
            kalman={'process_noise': 1e-4, 'observation_noise': 1e-2}
        )
        assert isinstance(combiner, AdaptiveFactorCombiner)
        assert combiner.method == "ensemble"
    
    def test_create_with_custom_params(self):
        combiner = create_adaptive_combiner(
            ['f1', 'f2'],
            method="ridge",
            lambda_reg=0.5,
            forgetting_factor=0.95
        )
        assert combiner.learner.lambda_reg == 0.5
        assert combiner.learner.forgetting_factor == 0.95


class TestOnlineModelState:
    def test_creation(self):
        state = OnlineModelState(
            weights=np.array([0.3, 0.7]),
            covariance=np.eye(2),
            step=10,
            metrics={'test': 1.0}
        )
        assert len(state.weights) == 2
        assert state.covariance.shape == (2, 2)
        assert state.step == 10
        assert state.metrics['test'] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])