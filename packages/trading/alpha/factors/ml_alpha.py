"""
ML Alpha Model Factor
LightGBM/XGBoost with walkforward validation, feature importance, SHAP
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union, Literal, Any
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import logging
import warnings
import pickle
import json
from pathlib import Path

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    lgb = None

try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    xgb = None

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    shap = None

from .base import FactorBase

logger = logging.getLogger(__name__)


@dataclass
class MLModelConfig:
    """Configuration for ML alpha model"""
    # Model type
    model_type: Literal["lightgbm", "xgboost", "ensemble"] = "lightgbm"
    
    # Training
    n_estimators: int = 500
    max_depth: int = 5
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    min_child_samples: int = 20
    reg_alpha: float = 0.1
    reg_lambda: float = 0.1
    random_state: int = 42
    
    # Walkforward validation
    train_window: int = 504  # 2 years
    test_window: int = 63   # 1 quarter
    step: int = 21          # 1 month
    min_train_size: int = 252
    
    # Feature engineering
    target_horizon: int = 21  # 1 month forward return
    target_type: Literal["return", "direction", "quantile"] = "return"
    quantile_bins: int = 5
    
    # Feature selection
    max_features: Optional[int] = 50
    feature_importance_threshold: float = 0.0
    
    # Ensemble
    ensemble_weights: Optional[Dict[str, float]] = None
    
    # Paths
    model_path: Optional[str] = None
    feature_names: Optional[List[str]] = None


class BaseMLModel(ABC):
    """Abstract base for ML models"""
    
    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None:
        pass
    
    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        pass
    
    @abstractmethod
    def get_feature_importance(self) -> np.ndarray:
        pass
    
    @abstractmethod
    def save(self, path: str) -> None:
        pass
    
    @abstractmethod
    def load(self, path: str) -> None:
        pass


class LightGBMModel(BaseMLModel):
    """LightGBM model wrapper"""
    
    def __init__(self, config: MLModelConfig):
        if not LIGHTGBM_AVAILABLE:
            raise ImportError("LightGBM not available. Install with: pip install lightgbm")
        self.config = config
        self.model = None
        self.feature_importance_ = None
        self.best_iteration = None
    
    def fit(self, X: np.ndarray, y: np.ndarray, 
            eval_set: Optional[Tuple[np.ndarray, np.ndarray]] = None,
            **kwargs) -> None:
        """Train LightGBM model"""
        
        params = {
            'objective': 'regression' if self.config.target_type == 'return' else 'binary',
            'metric': 'rmse' if self.config.target_type == 'return' else 'auc',
            'num_leaves': 2 ** self.config.max_depth - 1,
            'learning_rate': self.config.learning_rate,
            'feature_fraction': self.config.colsample_bytree,
            'bagging_fraction': self.config.subsample,
            'bagging_freq': 1,
            'min_child_samples': self.config.min_child_samples,
            'lambda_l1': self.config.reg_alpha,
            'lambda_l2': self.config.reg_lambda,
            'verbosity': -1,
            'random_state': self.config.random_state,
            'n_jobs': -1,
        }
        
        train_data = lgb.Dataset(X, label=y)
        
        if eval_set is not None:
            eval_data = lgb.Dataset(eval_set[0], label=eval_set[1], reference=train_data)
            self.model = lgb.train(
                params,
                train_data,
                num_boost_round=self.config.n_estimators,
                valid_sets=[eval_data],
                callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
            )
            self.best_iteration = self.model.best_iteration
        else:
            self.model = lgb.train(
                params,
                train_data,
                num_boost_round=self.config.n_estimators,
            )
            self.best_iteration = self.config.n_estimators
        
        self.feature_importance_ = self.model.feature_importance(importance_type='gain')
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise ValueError("Model not fitted")
        return self.model.predict(X, num_iteration=self.best_iteration)
    
    def get_feature_importance(self) -> np.ndarray:
        if self.feature_importance_ is None:
            return np.array([])
        return self.feature_importance_
    
    def save(self, path: str) -> None:
        if self.model is None:
            raise ValueError("Model not fitted")
        self.model.save_model(path)
    
    def load(self, path: str) -> None:
        self.model = lgb.Booster(model_file=path)
        self.best_iteration = self.model.best_iteration
        self.feature_importance_ = self.model.feature_importance(importance_type='gain')


class XGBoostModel(BaseMLModel):
    """XGBoost model wrapper"""
    
    def __init__(self, config: MLModelConfig):
        if not XGBOOST_AVAILABLE:
            raise ImportError("XGBoost not available. Install with: pip install xgboost")
        self.config = config
        self.model = None
        self.feature_importance_ = None
    
    def fit(self, X: np.ndarray, y: np.ndarray,
            eval_set: Optional[Tuple[np.ndarray, np.ndarray]] = None,
            **kwargs) -> None:
        """Train XGBoost model"""
        
        params = {
            'objective': 'reg:squarederror' if self.config.target_type == 'return' else 'binary:logistic',
            'eval_metric': 'rmse' if self.config.target_type == 'return' else 'auc',
            'max_depth': self.config.max_depth,
            'learning_rate': self.config.learning_rate,
            'subsample': self.config.subsample,
            'colsample_bytree': self.config.colsample_bytree,
            'min_child_weight': self.config.min_child_samples,
            'reg_alpha': self.config.reg_alpha,
            'reg_lambda': self.config.reg_lambda,
            'random_state': self.config.random_state,
            'n_jobs': -1,
            'verbosity': 0,
        }
        
        self.model = xgb.XGBRegressor(**params) if self.config.target_type == 'return' \
                     else xgb.XGBClassifier(**params)
        
        if eval_set is not None:
            self.model.fit(
                X, y,
                eval_set=[eval_set],
                early_stopping_rounds=50,
                verbose=False
            )
            self.best_iteration = self.model.best_iteration
        else:
            self.model.fit(X, y)
        
        self.feature_importance_ = self.model.feature_importances_
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise ValueError("Model not fitted")
        return self.model.predict(X)
    
    def get_feature_importance(self) -> np.ndarray:
        if self.feature_importance_ is None:
            return np.array([])
        return self.feature_importance_
    
    def save(self, path: str) -> None:
        if self.model is None:
            raise ValueError("Model not fitted")
        self.model.save_model(path)
    
    def load(self, path: str) -> None:
        if self.config.target_type == 'return':
            self.model = xgb.XGBRegressor()
        else:
            self.model = xgb.XGBClassifier()
        self.model.load_model(path)
        self.feature_importance_ = self.model.feature_importances_


class EnsembleModel(BaseMLModel):
    """Ensemble of LightGBM and XGBoost"""
    
    def __init__(self, config: MLModelConfig):
        self.config = config
        self.models = {}
        self.weights = config.ensemble_weights or {'lightgbm': 0.5, 'xgboost': 0.5}
        
        if LIGHTGBM_AVAILABLE:
            self.models['lightgbm'] = LightGBMModel(config)
        if XGBOOST_AVAILABLE:
            self.models['xgboost'] = XGBoostModel(config)
        
        if not self.models:
            raise ImportError("Neither LightGBM nor XGBoost available")
    
    def fit(self, X: np.ndarray, y: np.ndarray,
            eval_set: Optional[Tuple[np.ndarray, np.ndarray]] = None,
            **kwargs) -> None:
        for name, model in self.models.items():
            logger.info(f"Training {name}...")
            model.fit(X, y, eval_set=eval_set)
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        preds = np.zeros(len(X))
        for name, model in self.models.items():
            preds += self.weights.get(name, 1.0) * model.predict(X)
        return preds
    
    def get_feature_importance(self) -> np.ndarray:
        importances = []
        for name, model in self.models.items():
            imp = model.get_feature_importance()
            if len(imp) > 0:
                importances.append(imp * self.weights.get(name, 1.0))
        if importances:
            return np.mean(importances, axis=0)
        return np.array([])
    
    def save(self, path: str) -> None:
        path = Path(path)
        for name, model in self.models.items():
            model.save(str(path / f"{name}_model"))
    
    def load(self, path: str) -> None:
        path = Path(path)
        for name, model in self.models.items():
            model.load(str(path / f"{name}_model"))


class MLAlphaFactor(FactorBase):
    """
    ML-based Alpha Factor
    
    Features:
    - LightGBM / XGBoost / Ensemble
    - Walkforward validation (expanding/sliding window)
    - Feature engineering from market data
    - Feature importance & SHAP explanations
    - Model persistence
    """
    
    def __init__(
        self,
        config: Optional[MLModelConfig] = None,
        name: str = "ml_alpha",
    ):
        super().__init__(name)
        self.config = config or MLModelConfig()
        self.model: Optional[BaseMLModel] = None
        self.feature_names_ = None
        self.is_fitted_ = False
        self.cv_results_ = {}
        self.feature_importance_ = None
    
    def _create_model(self) -> BaseMLModel:
        """Create model based on config"""
        if self.config.model_type == "lightgbm":
            return LightGBMModel(self.config)
        elif self.config.model_type == "xgboost":
            return XGBoostModel(self.config)
        elif self.config.model_type == "ensemble":
            return EnsembleModel(self.config)
        else:
            raise ValueError(f"Unknown model_type: {self.config.model_type}")
    
    def _prepare_features(self, data: Dict[str, pd.DataFrame]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare features and target from market data.
        
        Expected data keys:
        - 'prices': DataFrame with close prices (assets x dates)
        - 'volume': Optional volume data
        - 'factors': Optional pre-computed factors
        """
        prices = data.get('prices')
        if prices is None:
            raise ValueError("Missing 'prices' in data")
        
        # Compute returns
        returns = prices.pct_change().dropna()
        
        # Feature engineering
        features_list = []
        feature_names = []
        
        # 1. Momentum features
        for window in [5, 10, 21, 63, 126]:
            mom = prices.pct_change(window).shift(1)  # Skip most recent
            features_list.append(mom.values.T)  # (assets, time)
            feature_names.extend([f'mom_{window}_{c}' for c in prices.columns])
        
        # 2. Volatility features
        for window in [10, 21, 63]:
            vol = prices.pct_change().rolling(window).std().shift(1)
            features_list.append(vol.values.T)
            feature_names.extend([f'vol_{window}_{c}' for c in prices.columns])
        
        # 3. Technical features
        # RSI
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        features_list.append(rsi.shift(1).values.T)
        feature_names.extend([f'rsi_14_{c}' for c in prices.columns])
        
        # Moving averages
        for window in [10, 21, 50, 200]:
            ma = prices.rolling(window).mean().shift(1)
            features_list.append(ma.values.T)
            feature_names.extend([f'ma_{window}_{c}' for c in prices.columns])
        
        # 4. Cross-sectional features
        # Rank within each time period
        returns_rank = returns.rank(axis=1, pct=True).shift(1)
        features_list.append(returns_rank.values.T)
        feature_names.extend([f'rank_ret_{c}' for c in prices.columns])
        
        # 5. Volume features (if available)
        if 'volume' in data:
            vol_data = data['volume']
            for window in [5, 21]:
                vol_ma = vol_data.rolling(window).mean().shift(1)
                features_list.append(vol_ma.values.T)
                feature_names.extend([f'vol_ma_{window}_{c}' for c in vol_data.columns])
        
        # Combine features
        X = np.concatenate(features_list, axis=1)
        
        # Target: forward returns
        target = prices.pct_change(self.config.target_horizon).shift(-self.config.target_horizon)
        y = target.values.T  # (assets, time)
        
        # Align and clean
        # Find valid indices (no NaN in X or y)
        valid = ~np.any(np.isnan(X), axis=1) & ~np.any(np.isnan(y), axis=1)
        
        X_clean = X[valid]
        y_clean = y[valid]
        
        # Generate feature names if not provided
        if self.config.feature_names is None:
            self.config.feature_names = feature_names[:X_clean.shape[1]]
        
        self.feature_names_ = self.config.feature_names
        
        return X_clean, y_clean
    
    def _walkforward_split(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
        """Generate walkforward train/test splits"""
        
        n_samples = len(X)
        splits = []
        
        start = 0
        while start + self.config.train_window + self.config.test_window <= n_samples:
            train_end = start + self.config.train_window
            test_end = train_end + self.config.test_window
            
            if train_end - start < self.config.min_train_size:
                start += self.config.step
                continue
            
            train_idx = np.arange(start, train_end)
            test_idx = np.arange(train_end, test_end)
            
            splits.append((
                X[train_idx], y[train_idx],
                X[test_idx], y[test_idx]
            ))
            
            start += self.config.step
        
        return splits
    
    def fit(
        self,
        data: Dict[str, pd.DataFrame],
        walkforward: bool = True,
        **kwargs
    ) -> 'MLAlphaFactor':
        """
        Fit the ML alpha model.
        
        Args:
            data: Market data dict with 'prices', optional 'volume', 'factors'
            walkforward: If True, use walkforward validation; else fit on all data
        """
        # Prepare features
        X, y = self._prepare_features(data)
        
        logger.info(f"Prepared features: X={X.shape}, y={y.shape}")
        
        # Create model
        self.model = self._create_model()
        
        if walkforward and len(X) > self.config.train_window + self.config.test_window:
            # Walkforward validation
            self.cv_results_ = self._walkforward_validate(X, y)
            
            # Retrain on full data for final model
            self.model.fit(X, y)
        else:
            # Simple train/test split
            split = int(0.8 * len(X))
            if self.config.model_type == "lightgbm" and LIGHTGBM_AVAILABLE:
                self.model.fit(X[:split], y[:split], eval_set=(X[split:], y[split:]))
            else:
                self.model.fit(X[:split], y[:split])
        
        # Store feature importance
        self.feature_importance_ = self.model.get_feature_importance()
        self.is_fitted_ = True
        
        # Save model if path provided
        if self.config.model_path:
            self.save(self.config.model_path)
        
        return self
    
    def _walkforward_validate(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ) -> Dict:
        """Perform walkforward validation"""
        
        splits = self._walkforward_split(X, y)
        
        if not splits:
            logger.warning("Insufficient data for walkforward validation")
            return {}
        
        results = {
            'predictions': [],
            'actuals': [],
            'test_indices': [],
            'ic_scores': [],
            'ir_scores': [],
        }
        
        for fold, (X_train, y_train, X_test, y_test) in enumerate(splits):
            logger.info(f"Walkforward fold {fold + 1}/{len(splits)}: "
                       f"train={len(X_train)}, test={len(X_test)}")
            
            # Create fresh model for each fold
            fold_model = self._create_model()
            fold_model.fit(X_train, y_train)
            
            # Predict
            y_pred = fold_model.predict(X_test)
            
            # Store results
            results['predictions'].append(y_pred)
            results['actuals'].append(y_test)
            results['test_indices'].append(
                np.arange(len(X_train) + sum(len(s[2]) for s in splits[:fold]),
                         len(X_train) + sum(len(s[2]) for s in splits[:fold]) + len(X_test))
            )
            
            # IC for this fold
            ic = np.corrcoef(y_pred.flatten(), y_test.flatten())[0, 1]
            results['ic_scores'].append(ic)
            
            logger.info(f"  Fold IC: {ic:.4f}")
        
        # Aggregate
        results['mean_ic'] = np.nanmean(results['ic_scores'])
        results['ic_std'] = np.nanstd(results['ic_scores'])
        results['ir'] = results['mean_ic'] / results['ic_std'] if results['ic_std'] > 0 else 0
        
        logger.info(f"Walkforward: Mean IC={results['mean_ic']:.4f}, "
                   f"IC Std={results['ic_std']:.4f}, IR={results['ir']:.2f}")
        
        return results
    
    def compute(self, data: Dict[str, pd.DataFrame], **kwargs) -> pd.Series:
        """
        Compute alpha signal from fitted model.
        
        Returns:
            pd.Series with alpha predictions (index = dates)
        """
        if not self.is_fitted_:
            raise ValueError("Model not fitted. Call fit() first.")
        
        X, _ = self._prepare_features(data)
        
        if len(X) == 0:
            return pd.Series(dtype=float)
        
        # Predict
        predictions = self.model.predict(X)
        
        # Convert to Series with proper index
        # Need to align with original data index
        prices = data['prices']
        
        # Get last N dates where we have predictions
        n_preds = len(predictions)
        pred_dates = prices.index[-n_preds:]
        
        # Average across assets for portfolio-level signal
        if X.ndim == 2:
            # Reshape predictions to (time, assets) then average
            n_assets = len(data['prices'].columns)
            n_time = len(predictions) // n_assets
            if n_time * n_assets == len(predictions):
                pred_matrix = predictions.reshape(n_time, n_assets)
                portfolio_signal = np.mean(pred_matrix, axis=1)
            else:
                portfolio_signal = predictions
        else:
            portfolio_signal = predictions
        
        return pd.Series(portfolio_signal, index=pred_dates[-len(portfolio_signal):])
    
    def get_feature_importance_df(self) -> pd.DataFrame:
        """Get feature importance as DataFrame"""
        if self.feature_importance_ is None or self.feature_names_ is None:
            return pd.DataFrame()
        
        n_features = min(len(self.feature_importance_), len(self.feature_names_))
        
        return pd.DataFrame({
            'feature': self.feature_names_[:n_features],
            'importance': self.feature_importance_[:n_features],
        }).sort_values('importance', ascending=False)
    
    def explain_shap(
        self,
        data: Dict[str, pd.DataFrame],
        max_samples: int = 1000,
    ) -> Optional[Any]:
        """
        Compute SHAP values for model interpretability.
        
        Returns:
            SHAP explainer object with values
        """
        if not SHAP_AVAILABLE:
            logger.warning("SHAP not available. Install with: pip install shap")
            return None
        
        if self.model is None:
            raise ValueError("Model not fitted")
        
        X, _ = self._prepare_features(data)
        
        if len(X) > max_samples:
            # Subsample for speed
            idx = np.random.choice(len(X), max_samples, replace=False)
            X = X[idx]
        
        # Get underlying model for SHAP
        if hasattr(self.model, 'models'):
            # Ensemble
            # Use first model for SHAP (or compute for each)
            base_model = list(self.model.models.values())[0].model
        else:
            base_model = self.model.model
        
        explainer = shap.TreeExplainer(base_model)
        shap_values = explainer.shap_values(X)
        
        return {
            'explainer': explainer,
            'values': shap_values,
            'features': X,
            'feature_names': self.feature_names_,
        }
    
    def save(self, path: str) -> None:
        """Save model to disk"""
        if self.model is None:
            raise ValueError("Model not fitted")
        
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        
        # Save model
        self.model.save(path)
        
        # Save config and metadata
        meta = {
            'config': {
                'model_type': self.config.model_type,
                'n_estimators': self.config.n_estimators,
                'max_depth': self.config.max_depth,
                'learning_rate': self.config.learning_rate,
                'target_horizon': self.config.target_horizon,
                'target_type': self.config.target_type,
                'train_window': self.config.train_window,
                'test_window': self.config.test_window,
                'step': self.config.step,
                'feature_names': self.feature_names_,
            },
            'cv_results': {
                k: v.tolist() if isinstance(v, np.ndarray) else v
                for k, v in self.cv_results_.items()
                if isinstance(v, (list, np.ndarray))
            },
            'feature_importance': self.feature_importance_.tolist() if self.feature_importance_ is not None else None,
        }
        
        with open(path / 'meta.json', 'w') as f:
            json.dump(meta, f, indent=2)
    
    def load(self, path: str) -> 'MLAlphaFactor':
        """Load model from disk"""
        path = Path(path)
        
        with open(path / 'meta.json', 'r') as f:
            meta = json.load(f)
        
        # Restore config
        self.config = MLModelConfig(**meta['config'])
        
        # Create and load model
        self.model = self._create_model()
        self.model.load(path)
        
        # Restore metadata
        self.feature_names_ = meta['config']['feature_names']
        self.feature_importance_ = np.array(meta['feature_importance']) if meta['feature_importance'] else None
        self.cv_results_ = meta['cv_results']
        self.is_fitted_ = True
        
        return self


def create_ml_alpha_factor(
    model_type: Literal["lightgbm", "xgboost", "ensemble"] = "lightgbm",
    target_horizon: int = 21,
    train_window: int = 504,
    test_window: int = 63,
    step: int = 21,
    **kwargs
) -> MLAlphaFactor:
    """Factory function for ML alpha factor"""
    config = MLModelConfig(
        model_type=model_type,
        target_horizon=target_horizon,
        train_window=train_window,
        test_window=test_window,
        step=step,
        **kwargs
    )
    return MLAlphaFactor(config=config)


if __name__ == "__main__":
    # Quick test
    import numpy as np
    import pandas as pd
    
    np.random.seed(42)
    n = 1000
    dates = pd.date_range('2020-01-01', periods=n, freq='D')
    assets = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META']
    
    # Synthetic prices with some predictable pattern
    prices = pd.DataFrame(index=dates, columns=assets, dtype=float)
    for i, asset in enumerate(assets):
        # Add some predictable component
        trend = np.linspace(0, 0.5, n)
        noise = np.random.normal(0, 0.01, n)
        seasonal = 0.001 * np.sin(np.arange(n) * 2 * np.pi / 252)
        returns = 0.0002 + 0.1 * np.roll(returns if 'returns' in locals() else np.zeros(n), 5) + noise + seasonal
        prices[asset] = 100 * np.exp(np.cumsum(returns))
    
    data = {'prices': prices}
    
    factor = create_ml_alpha_factor(
        model_type="lightgbm",
        target_horizon=21,
        train_window=300,
        test_window=50,
    )
    
    # Note: This is a quick test - in practice you'd want more data
    try:
        factor.fit(data, walkforward=True)
        signal = factor.compute(data)
        print(f"Signal shape: {signal.shape}")
        print(f"Signal stats: mean={signal.mean():.6f}, std={signal.std():.6f}")
        
        # Feature importance
        fi = factor.get_feature_importance_df()
        print(f"\nTop 10 features:")
        print(fi.head(10))
    except Exception as e:
        print(f"Test skipped: {e}")
        print("Install lightgbm: pip install lightgbm")