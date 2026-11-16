"""
Ensemble Stacking and Blending
Advanced ensemble methods for combining model predictions
"""
import asyncio
import logging
import pickle
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.linear_model import Ridge, LogisticRegression, LinearRegression
from sklearn.ensemble import StackingRegressor, VotingRegressor
from sklearn.model_selection import cross_val_predict, KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import sys
sys.path.insert(0, '/Users/aryanagarwal/alpha-system')

from alpha.models.base import BaseModel
from alpha.models.linear import RidgeRegression, LassoRegression, ElasticNet
from alpha.models.tree import LightGBMModel, XGBoostModel
from alpha.validation.metrics import calculate_ic, calculate_sharpe

# AutoStackingTuner annotates its parameters with TuningConfig and Trial but
# never imported either, so the class raised NameError the moment it was used.
# They are referenced only from quoted annotations here, and bound at runtime by
# local imports inside __init__/optimize, so optuna stays an optional
# dependency: a module-level import would make `import alpha.models.ensemble`
# fail outright on an install without it.
if TYPE_CHECKING:
    from optuna.trial import Trial

    from alpha.optimization.optuna_tuner import TuningConfig

logger = logging.getLogger(__name__)


# ============================================================
# Data Classes
# ============================================================

@dataclass
class EnsembleConfig:
    """Configuration for ensemble models"""
    # Base models
    base_models: List[Dict] = field(default_factory=list)  # [{'name': 'lgbm', 'params': {...}}, ...]
    
    # Metalearner
    meta_learner: str = "ridge"  # ridge, lasso, elasticnet, lr, nn
    meta_learner_params: Dict = field(default_factory=dict)
    
    # CV settings
    cv_folds: int = 5
    cv_strategy: str = "purged_kfold"  # kfold, purged_kfold, comb_purged
    purge_days: int = 21
    embargo_days: int = 21
    
    # Stacking settings
    use_features_in_secondary: bool = True  # Use original features in metalearner
    passthrough_features: bool = True
    
    # Blending
    blending_method: str = "stacking"  # stacking, blending, voting
    blend_weights: Optional[Dict[str, float]] = None
    
    # Cross-validation
    n_splits: int = 5
    shuffle: bool = False
    random_state: int = 42


@dataclass
class StackingResult:
    """Results from stacking"""
    meta_learner: Any
    base_models: Dict[str, Any]
    cv_predictions: Dict[str, np.ndarray]  # oof predictions
    test_predictions: Optional[np.ndarray]
    cv_scores: Dict[str, float]
    feature_importance: Optional[pd.DataFrame] = None


# ============================================================
# Base Metalearner
# ============================================================

class BaseMetalearner(ABC):
    """Abstract base class for metalearners"""
    
    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> 'BaseMetalearner':
        pass
    
    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        pass
    
    @abstractmethod
    def get_feature_importance(self) -> Optional[pd.DataFrame]:
        pass


class RidgeMetalearner(BaseMetalearner):
    """Ridge regression metalearner"""
    
    def __init__(self, alpha: float = 1.0, **kwargs):
        self.alpha = alpha
        self.kwargs = kwargs
        self.model = None
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> 'RidgeMetalearner':
        self.model = Ridge(alpha=self.alpha, **self.kwargs)
        self.model.fit(X, y)
        return self
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)
    
    def get_feature_importance(self) -> pd.DataFrame:
        if self.model is None:
            return None
        coef = self.model.coef_
        if coef.ndim > 1:
            coef = coef[0]
        return pd.DataFrame({
            'feature': [f'base_model_{i}' for i in range(len(coef))],
            'importance': np.abs(coef)
        }).sort_values('importance', ascending=False)


class LassoMetalearner(BaseMetalearner):
    """Lasso metalearner for sparse ensemble weights"""
    
    def __init__(self, alpha: float = 1.0, **kwargs):
        self.alpha = alpha
        self.kwargs = kwargs
        self.model = None
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> 'LassoMetalearner':
        from sklearn.linear_model import Lasso
        self.model = Lasso(alpha=self.alpha, max_iter=5000, **self.kwargs)
        self.model.fit(X, y)
        return self
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)
    
    def get_feature_importance(self) -> pd.DataFrame:
        if self.model is None:
            return None
        coef = self.model.coef_
        if coef.ndim > 1:
            coef = coef[0]
        return pd.DataFrame({
            'feature': [f'base_model_{i}' for i in range(len(coef))],
            'importance': np.abs(coef)
        }).sort_values('importance', ascending=False)


class ElasticNetMetalearner(BaseMetalearner):
    """ElasticNet metalearner"""
    
    def __init__(self, alpha: float = 1.0, l1_ratio: float = 0.5, **kwargs):
        self.alpha = alpha
        self.l1_ratio = l1_ratio
        self.kwargs = kwargs
        self.model = None
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> 'ElasticNetMetalearner':
        from sklearn.linear_model import ElasticNet
        self.model = ElasticNet(alpha=self.alpha, l1_ratio=self.l1_ratio, **self.kwargs)
        self.model.fit(X, y)
        return self
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)
    
    def get_feature_importance(self) -> pd.DataFrame:
        if self.model is None:
            return None
        coef = self.model.coef_
        if coef.ndim > 1:
            coef = coef[0]
        return pd.DataFrame({
            'feature': [f'base_model_{i}' for i in range(len(coef))],
            'importance': np.abs(coef)
        }).sort_values('importance', ascending=False)


class NeuralMetalearner(BaseMetalearner):
    """Neural network metalearner (MLP)"""
    
    def __init__(self, hidden_layers: List[int] = [64, 32], 
                 dropout: float = 0.1, lr: float = 0.001, epochs: int = 100,
                 batch_size: int = 256, **kwargs):
        self.hidden_layers = hidden_layers
        self.dropout = dropout
        self.lr = lr
        self.epochs = epochs
        self.batch_size = kwargs.get('batch_size', 256)
        self.kwargs = kwargs
        self.model = None
        self.scaler = None
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> 'NeuralMetalearner':
        try:
            import torch
            import torch.nn as nn
            import torch.optim as optim
        except ImportError:
            raise ImportError("PyTorch required for NeuralMetalearner: pip install torch")
        
        n_features = X.shape[1]
        
        # Build MLP
        layers = []
        prev_size = X.shape[1]
        for hidden_size in self.hidden_layers:
            layers.append(nn.Linear(prev_size, self.hidden_layers[0] if isinstance(self.hidden_layers, list) else self.hidden_layers))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(self.dropout))
            prev_size = self.hidden_layers[0] if isinstance(self.hidden_layers, list) else self.hidden_layers
        
        layers.append(nn.Linear(prev_size, 1))
        
        self.model = nn.Sequential(*layers)
        
        # Train
        X_tensor = torch.FloatTensor(X)
        y_tensor = torch.FloatTensor(y).view(-1, 1)
        
        optimizer = optim.Adam(self.model.parameters(), lr=self.lr)
        criterion = nn.MSELoss()
        
        for epoch in range(self.kwargs.get('epochs', 100)):
            self.model.train()
            optimizer.zero_grad()
            pred = self.model(X_tensor)
            loss = nn.MSELoss()(pred, y_tensor)
            loss.backward()
            optimizer.step()
        
        self.model.eval()
        return self
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        import torch
        self.model.eval()
        with torch.no_grad():
            X_tensor = torch.FloatTensor(X)
            pred = self.model(torch.FloatTensor(X))
            return pred.detach().numpy().flatten()
    
    def get_feature_importance(self) -> Optional[pd.DataFrame]:
        # Neural nets don't have direct feature importance
        # Could use permutation importance
        return None


# ============================================================
# Base model construction (shared by every ensemble strategy)
# ============================================================

class BaseEnsemble:
    """
    Base model construction shared by stacking, blending and voting.

    Subclasses must set `self.config` and `self.base_models` before calling
    `fit`; `_create_base_models` populates `base_models` in place and returns it.
    """

    def _create_base_models(self) -> Dict[str, BaseModel]:
        """Create base models from config"""
        models = {}
        for model_config in self.config.base_models:
            name = model_config['name']
            params = model_config.get('params', {})
            
            if name == 'ridge':
                from alpha.models.linear import RidgeRegression
                self.base_models[name] = RidgeRegression(**params)
            elif name == 'lasso':
                from alpha.models.linear import LassoRegression
                self.base_models[name] = LassoRegression(**params)
            elif name == 'elasticnet':
                from alpha.models.linear import ElasticNet
                self.base_models[name] = ElasticNet(**params)
            elif name == 'lightgbm':
                from alpha.models.tree import LightGBMModel
                self.base_models[name] = LightGBMModel(**params)
            elif name == 'xgboost':
                from alpha.models.tree import XGBoostModel
                self.base_models[name] = XGBoostModel(**params)
            else:
                raise ValueError(f"Unknown base model: {name}")
        
        return self.base_models


# ============================================================
# Stacking Regressor
# ============================================================

class StackingRegressor(BaseEnsemble):
    """
    Stacking regressor with purged/embargoed CV
    """
    
    def __init__(self, config: EnsembleConfig):
        self.config = config
        self.base_models: Dict[str, BaseModel] = {}
        self.meta_learner = None
        self.cv_predictions: Dict[str, np.ndarray] = {}
        self.cv_scores: Dict[str, float] = {}
        self.feature_importance: Optional[pd.DataFrame] = None
    
    def _create_metalearner(self):
        """Create metalearner from config"""
        ml_type = self.config.meta_learner.lower()
        params = self.config.meta_learner_params
        
        if self.config.meta_learner == 'ridge':
            return RidgeMetalearner(**self.config.meta_learner_params)
        elif self.config.meta_learner == 'lasso':
            return LassoMetalearner(**self.config.meta_learner_params)
        elif self.config.meta_learner == 'elasticnet':
            return ElasticNetMetalearner(**self.config.meta_learner_params)
        elif self.config.meta_learner == 'nn':
            return NeuralMetalearner(**self.config.meta_learner_params)
        else:
            raise ValueError(f"Unknown metalearner: {self.config.meta_learner}")
    
    def _get_cv_splitter(self, X: pd.DataFrame, y: pd.Series):
        """Create CV splitter based on config"""
        if self.config.cv_strategy == 'purged_kfold':
            from alpha.validation.walkforward import purged_embargoed_cv
            return purged_embargoed_cv(
                pd.DataFrame(index=X.index),
                pd.Series(index=y.index),
                n_splits=self.config.n_splits,
                purge_days=self.config.purge_days,
                embargo_days=self.config.embargo_days
            )
        elif self.config.cv_strategy == 'kfold':
            # sklearn rejects random_state when shuffle is False
            kfold_kwargs = {'n_splits': self.config.n_splits, 'shuffle': self.config.shuffle}
            if self.config.shuffle:
                kfold_kwargs['random_state'] = self.config.random_state
            return KFold(**kfold_kwargs)
        else:
            from alpha.validation.walkforward import purged_embargoed_cv
            return purged_embargoed_cv(
                pd.DataFrame(index=X.index),
                pd.Series(index=y.index),
                n_splits=self.config.n_splits,
                purge_days=self.config.purge_days,
                embargo_days=self.config.embargo_days
            )
    
    def fit(self, X: pd.DataFrame, y: pd.Series, X_test: pd.DataFrame = None, y_test: pd.Series = None) -> 'StackingRegressor':
        """
        Fit stacking regressor with purged/embargoed CV
        
        Args:
            X: Features (dates x assets or flat)
            y: Target returns
            X_test: Optional test features
            y_test: Optional test target
        """
        logger.info("Fitting stacking regressor...")
        
        # Create base models
        self._create_base_models()
        
        # Get CV splitter
        cv_splitter = self._get_cv_splitter(self.X_train if hasattr(self, 'X_train') else X, y)
        
        # Store data
        self.X_train = X
        self.y_train = y
        
        # Generate out-of-fold predictions for each base model
        logger.info("Generating out-of-fold predictions...")
        self.cv_predictions = {}
        cv_scores = {}
        
        # Use purged/embargoed CV
        cv_splitter = self._get_cv_splitter(X, y)
        splits = cv_splitter.split(X, y) if hasattr(cv_splitter, 'split') else cv_splitter
        for fold, (train_idx, val_idx) in enumerate(splits):
            X_tr = self.X_train.iloc[train_idx] if hasattr(self, 'X_train') else self.X_train.iloc[train_idx]
            y_tr = self.y_train.iloc[train_idx] if hasattr(self, 'y_train') else self.y_train.iloc[train_idx]
            X_val = self.X_train.iloc[val_idx] if hasattr(self, 'X_train') else X.iloc[val_idx]
            y_val = self.y_train.iloc[val_idx] if hasattr(self, 'y_train') else y.iloc[val_idx]
            
            for name, model in self.base_models.items():
                model.fit(X_tr, y_tr)
                pred = model.predict(X.iloc[val_idx])
                
                # Store OOF predictions
                if name not in self.cv_predictions:
                    self.cv_predictions[name] = np.full(len(X), np.nan)
                self.cv_predictions[name][val_idx] = pred
                
                # Score
                from alpha.validation.metrics import calculate_ic
                score = calculate_ic(pred, y.iloc[val_idx] if hasattr(y, 'iloc') else y[val_idx])
                if name not in cv_scores:
                    cv_scores[name] = []
                cv_scores[name].append(score)
        
        # Average CV scores
        for name, scores in cv_scores.items():
            self.cv_scores[name] = np.mean(scores)
        
        logger.info(f"CV Scores: {self.cv_scores}")
        
        # Prepare meta-features (OOF predictions)
        # Stack base model predictions
        meta_X = np.column_stack([self.cv_predictions[name] for name in self.base_models.keys()])
        
        # Add original features if configured
        if self.config.use_features_in_secondary:
            # Need to align features with CV indices
            pass  # Simplified for now
        
        # Train metalearner on OOF predictions
        logger.info(f"Training metalearner: {self.config.meta_learner}")
        self.meta_learner = self._create_metalearner()
        self.meta_learner.fit(
            # column_stack, not a list: sklearn reads a list of per-model
            # arrays as n_models samples of n_rows features
            np.column_stack([self.cv_predictions[name] for name in self.base_models.keys()]),
            self.y_train
        )
        
        # Feature importance
        self.feature_importance = self.meta_learner.get_feature_importance()
        
        # Fit base models on full training data
        logger.info("Fitting base models on full data...")
        for name, model in self.base_models.items():
            model.fit(X, y)
        
        logger.info("Stacking regressor fitted successfully")
        return self
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate predictions using stacked model"""
        # Get base model predictions
        base_preds = {}
        for name, model in self.base_models.items():
            base_preds[name] = model.predict(X)
        
        # Stack predictions
        meta_X = np.column_stack([base_preds[name] for name in self.base_models.keys()])
        
        # Metalearner prediction
        return self.meta_learner.predict(meta_X)
    
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Predict probabilities (for classification)"""
        raise NotImplementedError("Regression only")


class BlendingRegressor(BaseEnsemble):
    """
    Simple blending (weighted average) of base models
    """
    
    def __init__(self, config: EnsembleConfig):
        self.config = config
        self.base_models: Dict[str, BaseModel] = {}
        self.weights: Dict[str, float] = {}
    
    def fit(self, X: pd.DataFrame, y: pd.Series) -> 'BlendingRegressor':
        """Fit blender with optimized weights"""
        self._create_base_models()
        
        # Simple approach: optimize weights on validation set
        # For production, would use validation set or CV
        
        # Fit all base models
        for name, model in self.base_models.items():
            model.fit(X, y)
        
        # Optimize weights (simple grid search or optimization)
        if self.config.blend_weights:
            self.weights = self.config.blend_weights
        else:
            # Equal weights
            self.weights = {name: 1.0 / len(self.base_models) for name in self.base_models}
        
        return self
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Weighted average of base model predictions"""
        preds = np.zeros(len(X))
        for name, model in self.base_models.items():
            preds += self.weights[name] * model.predict(X)
        return preds


class VotingRegressor(BaseEnsemble):
    """Voting regressor (hard/soft voting)"""
    
    def __init__(self, config: EnsembleConfig):
        self.config = config
        self.base_models: Dict[str, BaseModel] = {}
        self.weights: Dict[str, float] = {}
    
    def fit(self, X: pd.DataFrame, y: pd.Series) -> 'VotingRegressor':
        self._create_base_models()
        for name, model in self.base_models.items():
            model.fit(X, y)
        
        if self.config.blend_weights:
            self.weights = self.config.blend_weights
        else:
            self.weights = {name: 1.0 / len(self.base_models) for name in self.base_models}
        
        return self
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        preds = np.zeros(len(X))
        for name, model in self.base_models.items():
            preds += self.weights[name] * model.predict(X)
        return preds


class EnsembleFactory:
    """Factory for creating ensemble models"""
    
    @staticmethod
    def create_stacking(config: EnsembleConfig) -> StackingRegressor:
        return StackingRegressor(config)
    
    @staticmethod
    def create_blending(config: EnsembleConfig) -> BlendingRegressor:
        return BlendingRegressor(config)
    
    @staticmethod
    def create_voting(config: EnsembleConfig) -> VotingRegressor:
        return VotingRegressor(config)
    
    @staticmethod
    def create_from_config(config: Dict) -> Any:
        """Create ensemble from config dict"""
        config_obj = EnsembleConfig(**config)
        blending_method = config.get('blending_method', 'stacking')
        
        if blending_method == 'stacking':
            return EnsembleFactory.create_stacking(config_obj)
        elif blending_method == 'blending':
            return EnsembleFactory.create_blending(config_obj)
        elif blending_method == 'voting':
            return EnsembleFactory.create_voting(config_obj)
        else:
            raise ValueError(f"Unknown blending method: {blending_method}")


# ============================================================
# Dynamic Ensemble Weighting
# ============================================================

class DynamicEnsembleWeights:
    """
    Dynamically adjust ensemble weights based on recent performance
    """
    
    def __init__(self, 
                 base_models: Dict[str, BaseModel],
                 window: int = 63,  # ~3 months
                 min_weight: float = 0.05,
                 max_weight: float = 0.5,
                 decay: float = 0.95):
        self.base_models = base_models
        self.window = window
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.decay = decay
        self.weights = {name: 1.0 / len(base_models) for name in base_models}
        self.performance_history = {name: [] for name in base_models}
    
    def update_performance(self, model_name: str, metric: float):
        """Update model performance"""
        if model_name in self.performance_history:
            self.performance_history[model_name].append({
                'metric': metric,
                'timestamp': time.time()
            })
            # Keep only recent history
            cutoff = time.time() - self.window * 86400  # days to seconds
            self.performance_history[model_name] = [
                h for h in self.performance_history[model_name]
                if h['timestamp'] > cutoff
            ]
    
    def update_weights(self):
        """Update weights based on recent performance"""
        scores = {}
        for name, history in self.performance_history.items():
            if len(history) < 10:
                scores[name] = 1.0  # Default
            else:
                # Exponentially weighted performance
                recent = history[-self.window//2:] if len(history) > 10 else history
                metrics = [h['metric'] for h in recent]
                weights = np.power(self.decay, np.arange(len(metrics))[::-1])
                scores[name] = np.average(metrics, weights=weights)
        
        # Convert to weights
        if not scores:
            return
        
        # Shift to positive
        min_score = min(scores.values())
        if min_score < 0:
            scores = {k: v - min_score + 1e-6 for k, v in scores.items()}
        
        total = sum(scores.values())
        if total > 0:
            new_weights = {k: v / total for k, v in scores.items()}
        else:
            new_weights = {k: 1.0 / len(scores) for k in scores}
        
        # Apply min/max constraints via Euclidean projection onto the
        # capped simplex {sum=1, min <= w <= max}: find shift lambda such
        # that sum(clip(scores + lambda)) == 1. Naive clip + renormalize
        # can push a clipped weight back outside its bound, so we solve
        # for lambda by bisection (f is monotone in lambda).
        keys = list(new_weights.keys())
        n = len(keys)
        lower, upper = self.min_weight, self.max_weight

        # Guard against infeasible bounds for this number of models
        if n * upper < 1.0:
            upper = 1.0 / n
        if n * lower > 1.0:
            lower = 1.0 / n

        v = np.array([new_weights[k] for k in keys], dtype=float)

        def _sum_at(lam):
            return np.clip(v + lam, lower, upper).sum()

        lo = lower - v.max() - 1.0
        hi = upper - v.min() + 1.0
        for _ in range(100):
            mid = (lo + hi) / 2.0
            if _sum_at(mid) < 1.0:
                lo = mid
            else:
                hi = mid
        w = np.clip(v + (lo + hi) / 2.0, lower, upper)

        self.weights = {k: float(x) for k, x in zip(keys, w)}
    
    def get_weights(self) -> Dict[str, float]:
        return self.weights.copy()
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Weighted ensemble prediction"""
        preds = np.zeros(len(X))
        for name, model in self.models.items():
            preds += self.weights[name] * model.predict(X)
        return preds


# ============================================================
# Ensemble Factory
# ============================================================

class EnsembleFactory:
    """Factory for creating ensemble models"""
    
    @staticmethod
    def create_stacking(config: EnsembleConfig) -> StackingRegressor:
        return StackingRegressor(config)
    
    @staticmethod
    def create_blending(config: EnsembleConfig) -> BlendingRegressor:
        return BlendingRegressor(config)
    
    @staticmethod
    def create_voting(config: EnsembleConfig) -> VotingRegressor:
        return VotingRegressor(config)
    
    @staticmethod
    def create_dynamic(config: EnsembleConfig, base_models: Dict[str, BaseModel]) -> DynamicEnsembleWeights:
        return DynamicEnsembleWeights(base_models)


# ============================================================
# Auto-Stacking with Optuna
# ============================================================

class AutoStackingTuner:
    """
    Automatically tune stacking configuration with Optuna
    """
    
    def __init__(self, 
                 X: pd.DataFrame,
                 y: pd.Series,
                 base_model_classes: List[type],
                 base_param_spaces: Dict[str, Dict],
                 meta_learner_options: List[str] = None,
                 cv_splitter=None,
                 config: 'TuningConfig' = None):
        self.X = X
        self.y = y
        self.base_model_classes = base_model_classes
        self.base_param_spaces = base_param_spaces
        self.meta_learner_options = meta_learner_options or ['ridge', 'lasso', 'elasticnet']
        self.cv_splitter = cv_splitter

        # Lazy import: optuna is an optional dependency used only by this
        # class. Importing it at module scope would break
        # `import alpha.models.ensemble` on an install without optuna.
        from alpha.optimization.optuna_tuner import TuningConfig

        self.config = config or TuningConfig()
    
    def objective(self, trial: 'Trial') -> float:
        # Sample base model hyperparameters
        base_models = {}
        for name, cls in self.base_model_classes.items():
            params = {}
            for param, space in self.base_param_spaces.get(name, {}).items():
                if isinstance(space, tuple) and len(space) == 2:
                    if isinstance(space[0], int):
                        params[param] = trial.suggest_int(param, space[0], space[1])
                    else:
                        params[param] = trial.suggest_float(param, space[0], space[1])
                base_models[name] = cls(**params)
            
            # Sample metalearner
            meta_learner_type = trial.suggest_categorical('meta_learner', ['ridge', 'lasso', 'elasticnet'])
            if meta_learner_type == 'ridge':
                meta_learner = RidgeMetalearner(alpha=trial.suggest_float('meta_alpha', 1e-4, 1e2, log=True))
            elif meta_learner_type == 'lasso':
                meta_learner = LassoMetalearner(alpha=trial.suggest_float('meta_alpha', 1e-4, 1e1, log=True))
            else:
                meta_learner = ElasticNetMetalearner(
                    alpha=trial.suggest_float('meta_alpha', 1e-4, 1e1, log=True),
                    l1_ratio=trial.suggest_float('meta_l1_ratio', 0.1, 0.9)
                )
            
            # Train and evaluate with CV
            scores = []
            for train_idx, val_idx in self.cv_splitter.split(self.X, self.y):
                # Train base models
                base_preds = {}
                for name, model in base_models.items():
                    model.fit(self.X.iloc[train_idx], self.y.iloc[train_idx])
                    base_preds[name] = model.predict(self.X.iloc[val_idx])
                
                # Stack
                meta_X = np.column_stack([preds for preds in base_preds.values()])
                meta_y = self.y.iloc[val_idx]
                
                # Train metalearner
                meta_learner.fit(meta_X, meta_y)
                pred = meta_learner.predict(meta_X)
                
                # Score
                from alpha.validation.metrics import calculate_ic
                ic = calculate_ic(pred, meta_y)
                scores.append(ic)
            
            return np.mean(scores) if scores else -np.inf
    
    def optimize(self, n_trials: int = 50) -> Dict:
        # Imported here rather than at module scope: optuna is an optional
        # dependency and nothing else in this module needs it. A module-level
        # import would make `import alpha.models.ensemble` fail outright on an
        # install without optuna.
        from alpha.optimization.optuna_tuner import OptunaTuner

        tuner = OptunaTuner(self.config)
        return tuner.optimize(self.objective, n_trials=n_trials)


# ============================================================
# Utility Functions
# ============================================================

def create_stacking_ensemble(
    base_models: Dict[str, Any],
    meta_learner: str = 'ridge',
    cv_folds: int = 5,
    cv_strategy: str = 'purged_kfold',
    purge_days: int = 21,
    embargo_days: int = 21,
    **kwargs
) -> StackingRegressor:
    """Quick factory for stacking regressor"""
    config = EnsembleConfig(
        base_models=[{'name': name, 'params': {}} for name in base_models],
        meta_learner=meta_learner,
        cv_folds=cv_folds,
        cv_strategy=cv_strategy,
        purge_days=purge_days,
        embargo_days=embargo_days,
        **kwargs
    )
    return StackingRegressor(config)


def create_blending_ensemble(
    base_models: Dict[str, Any],
    weights: Dict[str, float] = None,
    **kwargs
) -> BlendingRegressor:
    """Quick factory for blending regressor"""
    config = EnsembleConfig(
        base_models=[{'name': name, 'params': {}} for name in base_models],
        blending_method='blending',
        blend_weights=weights,
        **kwargs
    )
    return BlendingRegressor(config)


def create_voting_ensemble(
    base_models: Dict[str, Any],
    weights: Dict[str, float] = None,
    **kwargs
) -> VotingRegressor:
    """Quick factory for voting regressor"""
    config = EnsembleConfig(
        base_models=[{'name': name, 'params': {}} for name in base_models],
        blending_method='voting',
        blend_weights=weights,
        **kwargs
    )
    return VotingRegressor(config)


# ============================================================
# Example Usage
# ============================================================

async def example_usage():
    """Example of stacking ensemble"""
    import numpy as np
    import pandas as pd
    
    # Generate sample data
    np.random.seed(42)
    n_samples = 1000
    n_features = 20
    
    X = pd.DataFrame(np.random.randn(n_samples, 20), 
                     index=pd.date_range('2020-01-01', periods=n_samples, freq='D'))
    y = pd.Series(np.random.randn(n_samples), index=X.index)
    
    # Create base models
    base_models = {
        'ridge': RidgeRegression(alpha=1.0),
        'lasso': LassoRegression(alpha=1.0),
        'lgbm': LightGBMModel(n_estimators=100, learning_rate=0.05),
        'xgboost': XGBoostModel(n_estimators=100, learning_rate=0.05),
    }
    
    # Create stacking ensemble
    config = EnsembleConfig(
        base_models=[{'name': k, 'params': {}} for k in ['ridge', 'lasso', 'lgbm', 'xgboost']],
        meta_learner='ridge',
        cv_folds=4,
        cv_strategy='purged_kfold',
        purge_days=21,
        embargo_days=21,
    )
    
    ensemble = StackingRegressor(config)
    # ensemble.fit(X, y)  # Would need proper data
    
    # Blending
    blending = BlendingRegressor(EnsembleConfig(
        base_models=[{'name': k, 'params': {}} for k in ['ridge', 'lasso']],
        blend_weights={'ridge': 0.6, 'lasso': 0.4}
    ))
    
    # Dynamic ensemble
    dynamic = DynamicEnsembleWeights({
        'model1': RidgeRegression(),
        'model2': LassoRegression(),
    })
    
    print("Ensemble module ready!")
    print("Available classes:")
    print("  - StackingRegressor: Purged/embargoed CV stacking")
    print("  - BlendingRegressor: Weighted blending")
    print("  - VotingRegressor: Voting ensemble")
    print("  - DynamicEnsembleWeights: Adaptive weights")
    print("  - AutoStackingTuner: Optuna tuning for stacking")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example_usage()
