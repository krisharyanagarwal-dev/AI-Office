"""
Tree-based Models
LightGBM, XGBoost, CatBoost models
"""
import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Any

from .base import BaseModel


class LightGBMModel(BaseModel):
    """
    LightGBM model
    """
    
    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = -1,
        learning_rate: float = 0.1,
        subsample: float = 1.0,
        colsample_bytree: float = 1.0,
        reg_alpha: float = 0.0,
        reg_lambda: float = 0.0,
        random_state: int = 42,
        **kwargs
    ):
        super().__init__(name="LightGBMModel", **kwargs)
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.reg_alpha = reg_alpha
        self.reg_lambda = reg_lambda
        self.random_state = random_state
        self.model = None
        self.is_fitted = False
        
        # Try to import lightgbm
        try:
            import lightgbm as lgb
            self.lgb = lgb
        except ImportError:
            raise ImportError("lightgbm not installed: pip install lightgbm")
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model"""
        # Handle missing values
        X_clean = X.fillna(0)
        y_clean = y.fillna(0)
        
        # Create LightGBM dataset
        train_data = self.lgb.Dataset(X_clean, label=y_clean)
        
        # Set parameters
        params = {
            'objective': 'regression',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 31 if self.max_depth == -1 else 2**self.max_depth - 1,
            'learning_rate': self.learning_rate,
            'feature_fraction': self.colsample_bytree,
            'bagging_fraction': self.subsample,
            'bagging_freq': 5,
            'reg_alpha': self.reg_alpha,
            'reg_lambda': self.reg_lambda,
            'verbosity': -1,
            'seed': self.random_state
        }
        
        # Train model
        self.model = self.lgb.train(
            params,
            train_data,
            num_boost_round=self.n_estimators,
            verbose_eval=False
        )
        
        self.is_fitted = True
        return self
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        
        # Handle missing values
        X_clean = X.fillna(0)
        
        # Make predictions
        predictions = self.model.predict(X_clean, num_iteration=self.model.best_iteration)
        return pd.Series(predictions, index=X.index, name=self.name)


class XGBoostModel(BaseModel):
    """
    XGBoost model
    """
    
    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 6,
        learning_rate: float = 0.1,
        subsample: float = 1.0,
        colsample_bytree: float = 1.0,
        reg_alpha: float = 0.0,
        reg_lambda: float = 0.0,
        random_state: int = 42,
        **kwargs
    ):
        super().__init__(name="XGBoostModel", **kwargs)
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.reg_alpha = reg_alpha
        self.reg_lambda = reg_lambda
        self.random_state = random_state
        self.model = None
        self.is_fitted = False
        
        # Try to import xgboost
        try:
            import xgboost as xgb
            self.xgb = xgb
        except ImportError:
            raise ImportError("xgboost not installed: pip install xgboost")
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model"""
        # Handle missing values
        X_clean = X.fillna(0)
        y_clean = y.fillna(0)
        
        # Create XGBoost dataset
        train_data = self.xgb.DMatrix(X_clean, label=y_clean)
        
        # Set parameters
        params = {
            'objective': 'reg:squarederror',
            'eval_metric': 'rmse',
            'max_depth': self.max_depth,
            'eta': self.learning_rate,
            'subsample': self.subsample,
            'colsample_bytree': self.colsample_bytree,
            'reg_alpha': self.reg_alpha,
            'reg_lambda': self.reg_lambda,
            'seed': self.random_state
        }
        
        # Train model
        self.model = self.xgb.train(
            params,
            train_data,
            num_boost_round=self.n_estimators,
            verbose_eval=False
        )
        
        self.is_fitted = True
        return self
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        
        # Handle missing values
        X_clean = X.fillna(0)
        
        # Create DMatrix for prediction
        dtest = self.xgb.DMatrix(X_clean)
        
        # Make predictions
        predictions = self.model.predict(dtest)
        return pd.Series(predictions, index=X.index, name=self.name)


class CatBoostModel(BaseModel):
    """
    CatBoost model
    """
    
    def __init__(
        self,
        iterations: int = 100,
        depth: int = 6,
        learning_rate: float = 0.1,
        l2_leaf_reg: float = 3.0,
        random_state: int = 42,
        **kwargs
    ):
        super().__init__(name="CatBoostModel", **kwargs)
        self.iterations = iterations
        self.depth = depth
        self.learning_rate = learning_rate
        self.l2_leaf_reg = l2_leaf_reg
        self.random_state = random_state
        self.model = None
        self.is_fitted = False
        
        # Try to import catboost
        try:
            from catboost import CatBoostRegressor
            self.CatBoostRegressor = CatBoostRegressor
        except ImportError:
            raise ImportError("catboost not installed: pip install catboost")
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model"""
        # Handle missing values
        X_clean = X.fillna(0)
        y_clean = y.fillna(0)
        
        # Create and train model
        self.model = self.CatBoostRegressor(
            iterations=self.iterations,
            depth=self.depth,
            learning_rate=self.learning_rate,
            l2_leaf_reg=self.l2_leaf_reg,
            random_seed=self.random_state,
            loss_function='RMSE',
            verbose=False
        )
        
        self.model.fit(X_clean, y_clean, verbose=False)
        self.is_fitted = True
        return self
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        
        # Handle missing values
        X_clean = X.fillna(0)
        
        # Make predictions
        predictions = self.model.predict(X_clean)
        return pd.Series(predictions, index=X.index, name=self.name)