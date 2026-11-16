"""
Tests for Ensemble Stacking & Blending
"""
import pytest
import pandas as pd
import numpy as np
from alpha.models.ensemble import (
    StackingRegressor, BlendingRegressor, VotingRegressor,
    DynamicEnsembleWeights, EnsembleFactory, EnsembleConfig
)
from alpha.models.linear import RidgeRegression, LassoRegression
from alpha.models.tree import LightGBMModel, XGBoostModel


class TestStackingRegressor:
    """Tests for StackingRegressor"""
    
    def setup_method(self):
        np.random.seed(42)
        n = 500
        dates = pd.date_range('2020-01-01', periods=n, freq='D')
        self.X = pd.DataFrame(np.random.randn(n, 10), index=dates)
        self.y = pd.Series(np.random.randn(n), index=dates)
        
        self.config = EnsembleConfig(
            base_models=[
                {'name': 'ridge', 'params': {'alpha': 1.0}},
                {'name': 'lasso', 'params': {'alpha': 1.0}},
            ],
            meta_learner='ridge',
            cv_folds=3,
            cv_strategy='kfold',
        )
        self.ensemble = StackingRegressor(self.config)
    
    def test_fit_predict(self):
        """Test basic fit and predict"""
        self.ensemble.fit(self.X, self.y)
        preds = self.ensemble.predict(self.X)
        assert len(preds) == len(self.X)
    
    def test_cv_predictions(self):
        """Test that CV predictions are generated"""
        self.ensemble.fit(self.X, self.y)
        assert hasattr(self.ensemble, 'cv_predictions')
        assert len(self.ensemble.cv_predictions) == 2  # ridge, lasso
        for name, preds in self.ensemble.cv_predictions.items():
            assert len(preds) == len(self.X)
    
    def test_cv_scores(self):
        """Test CV scores are computed"""
        self.ensemble.fit(self.X, self.y)
        assert hasattr(self.ensemble, 'cv_scores')
        assert 'ridge' in self.ensemble.cv_scores
        assert 'lasso' in self.ensemble.cv_scores


class TestBlendingRegressor:
    """Tests for BlendingRegressor"""
    
    def setup_method(self):
        np.random.seed(42)
        n = 200
        dates = pd.date_range('2020-01-01', periods=n, freq='D')
        self.X = pd.DataFrame(np.random.randn(n, 5), index=pd.date_range('2020-01-01', periods=n, freq='D'))
        self.y = pd.Series(np.random.randn(n), index=dates)
        
        self.config = EnsembleConfig(
            base_models=[
                {'name': 'ridge', 'params': {'alpha': 1.0}},
                {'name': 'lasso', 'params': {'alpha': 1.0}},
            ],
            blending_method='blending',
            blend_weights={'ridge': 0.6, 'lasso': 0.4}
        )
        self.ensemble = BlendingRegressor(self.config)
    
    def test_fit_predict(self):
        self.ensemble.fit(self.X, self.y)
        preds = self.ensemble.predict(self.X)
        assert len(preds) == len(self.X)
    
    def test_weights(self):
        self.ensemble.fit(self.X, self.y)
        assert 'ridge' in self.ensemble.weights
        assert 'lasso' in self.ensemble.weights
        assert abs(sum(self.ensemble.weights.values()) - 1.0) < 1e-6


class TestVotingRegressor:
    """Tests for VotingRegressor"""
    
    def setup_method(self):
        np.random.seed(42)
        n = 200
        dates = pd.date_range('2020-01-01', periods=n, freq='D')
        self.X = pd.DataFrame(np.random.randn(n, 5), index=dates)
        self.y = pd.Series(np.random.randn(n), index=dates)
        
        self.config = EnsembleConfig(
            base_models=[
                {'name': 'ridge', 'params': {'alpha': 1.0}},
                {'name': 'lasso', 'params': {'alpha': 1.0}},
            ],
            blending_method='voting',
            blend_weights={'ridge': 0.6, 'lasso': 0.4}
        )
        self.ensemble = VotingRegressor(EnsembleConfig(
            base_models=[{'name': 'ridge', 'params': {'alpha': 1.0}},
                        {'name': 'lasso', 'params': {'alpha': 1.0}}],
            blending_method='voting',
            blend_weights={'ridge': 0.6, 'lasso': 0.4}
        ))
        self.ensemble = VotingRegressor(EnsembleConfig(
            base_models=[{'name': 'ridge', 'params': {'alpha': 1.0}},
                        {'name': 'lasso', 'params': {'alpha': 1.0}}],
            blending_method='voting',
            blend_weights={'ridge': 0.6, 'lasso': 0.4}
        ))
    
    def test_fit_predict(self):
        self.ensemble.fit(self.X, self.y)
        preds = self.ensemble.predict(self.X)
        assert len(preds) == len(self.X)


class TestDynamicEnsembleWeights:
    """Tests for DynamicEnsembleWeights"""
    
    def setup_method(self):
        np.random.seed(42)
        n = 100
        dates = pd.date_range('2020-01-01', periods=100, freq='D')
        self.models = {
            'model1': RidgeRegression(alpha=1.0),
            'model2': LassoRegression(alpha=1.0),
        }
        self.dynamic = DynamicEnsembleWeights(
            base_models={'model1': RidgeRegression(), 'model2': LassoRegression()},
            window=30,
            min_weight=0.1,
            max_weight=0.8,
            decay=0.9
        )
    
    def test_update_performance(self):
        self.dynamic.update_performance('model1', 0.05)
        self.dynamic.update_performance('model1', -0.02)
        self.dynamic.update_performance('model2', 0.03)
        
        assert 'model1' in self.dynamic.performance_history
        assert len(self.dynamic.performance_history['model1']) == 2
    
    def test_update_weights(self):
        # Add some performance data
        for _ in range(20):
            self.dynamic.update_performance('model1', np.random.normal(0.001, 0.01))
            self.dynamic.update_performance('model2', np.random.normal(0.0005, 0.01))
        
        self.dynamic.update_weights()
        weights = self.dynamic.get_weights()
        assert sum(weights.values()) == pytest.approx(1.0, rel=1e-6)
        assert all(w >= 0.05 for w in self.dynamic.weights.values())
        assert all(w <= 0.8 for w in self.dynamic.weights.values())


class TestEnsembleFactory:
    """Tests for EnsembleFactory"""
    
    def test_create_stacking(self):
        config = EnsembleConfig(
            base_models=[{'name': 'ridge', 'params': {'alpha': 1.0}}],
            meta_learner='ridge',
            cv_folds=3,
            cv_strategy='kfold'
        )
        ensemble = EnsembleFactory.create_stacking(EnsembleConfig(
            base_models=[{'name': 'ridge', 'params': {'alpha': 1.0}}],
            meta_learner='ridge',
            cv_folds=3,
            cv_strategy='kfold'
        ))
        assert isinstance(ensemble, StackingRegressor)
    
    def test_create_blending(self):
        ensemble = EnsembleFactory.create_blending(EnsembleConfig(
            base_models=[{'name': 'ridge', 'params': {'alpha': 1.0}}],
            blending_method='blending',
            blend_weights={'ridge': 1.0}
        ))
        assert isinstance(ensemble, BlendingRegressor)
    
    def test_create_voting(self):
        ensemble = EnsembleFactory.create_voting(EnsembleConfig(
            base_models=[{'name': 'ridge', 'params': {'alpha': 1.0}}],
            blending_method='voting',
            blend_weights={'ridge': 1.0}
        ))
        assert isinstance(ensemble, VotingRegressor)


class TestDynamicEnsembleWeights:
    """Tests for DynamicEnsembleWeights"""
    
    def setup_method(self):
        np.random.seed(42)
        self.dynamic = DynamicEnsembleWeights(
            base_models={'model1': RidgeRegression(), 'model2': LassoRegression()},
            window=30,
            min_weight=0.1,
            max_weight=0.8,
            decay=0.9
        )
    
    def test_update_performance(self):
        self.dynamic.update_performance('model1', 0.05)
        self.dynamic.update_performance('model1', -0.02)
        self.dynamic.update_performance('model2', 0.03)
        
        assert 'model1' in self.dynamic.performance_history
        assert len(self.dynamic.performance_history['model1']) == 2
    
    def test_update_weights(self):
        # Add performance data
        for _ in range(20):
            self.dynamic.update_performance('model1', np.random.normal(0.001, 0.01))
            self.dynamic.update_performance('model2', np.random.normal(0.0005, 0.01))
        
        self.dynamic.update_weights()
        weights = self.dynamic.get_weights()
        assert sum(weights.values()) == pytest.approx(1.0, rel=1e-6)
        assert all(w >= 0.05 for w in self.dynamic.weights.values())
        assert all(w <= 0.8 for w in self.dynamic.weights.values())
    
    def test_predict(self):
        # Test prediction with dynamic weights
        X = pd.DataFrame(np.random.randn(10, 5), index=pd.date_range('2020-01-01', periods=10))
        self.dynamic.models = {
            'model1': RidgeRegression(alpha=1.0),
            'model2': LassoRegression(alpha=1.0)
        }
        # Fit models
        for name, model in self.dynamic.models.items():
            model.fit(pd.DataFrame(np.random.randn(100, 5)), pd.Series(np.random.randn(100)))
        
        self.dynamic.weights = {'model1': 0.6, 'model2': 0.4}
        preds = self.dynamic.predict(pd.DataFrame(np.random.randn(10, 5)))
        assert len(preds) == 10


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
