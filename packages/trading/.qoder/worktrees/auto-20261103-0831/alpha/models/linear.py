"""
Linear Models
Ridge, Lasso, ElasticNet regression models
"""
import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Any
from sklearn.linear_model import Ridge as SklearnRidge, Lasso as SklearnLasso, ElasticNet as SklearnElasticNet
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

from .base import BaseModel


class RidgeRegression(BaseModel):
    """
    Ridge Regression (L2 regularization)
    """
    
    def __init__(self, alpha: float = 1.0, **kwargs):
        super().__init__(name="RidgeRegression", **kwargs)
        self.alpha = alpha
        self.model = Pipeline([
            ('scaler', StandardScaler()),
            ('ridge', SklearnRidge(alpha=alpha, random_state=42))
        ])
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model"""
        # Handle missing values
        X_clean = X.fillna(0)
        y_clean = y.fillna(0)
        self.model.fit(X_clean, y_clean)
        self.is_fitted = True
        return self
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        # Handle missing values
        X_clean = X.fillna(0)
        predictions = self.model.predict(X_clean)
        return pd.Series(predictions, index=X.index)


class LassoRegression(BaseModel):
    """
    Lasso Regression (L1 regularization)
    """
    
    def __init__(self, alpha: float = 1.0, **kwargs):
        super().__init__(name="LassoRegression", **kwargs)
        self.alpha = alpha
        self.model = Pipeline([
            ('scaler', StandardScaler()),
            ('lasso', SklearnLasso(alpha=alpha, random_state=42, max_iter=2000))
        ])
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model"""
        # Handle missing values
        X_clean = X.fillna(0)
        y_clean = y.fillna(0)
        self.model.fit(X_clean, y_clean)
        self.is_fitted = True
        return self
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        # Handle missing values
        X_clean = X.fillna(0)
        predictions = self.model.predict(X_clean)
        return pd.Series(predictions, index=X.index)


class ElasticNet(BaseModel):
    """
    Elastic Net (L1 + L2 regularization)
    """
    
    def __init__(self, alpha: float = 1.0, l1_ratio: float = 0.5, **kwargs):
        super().__init__(name="ElasticNet", **kwargs)
        self.alpha = alpha
        self.l1_ratio = l1_ratio
        self.model = Pipeline([
            ('scaler', StandardScaler()),
            ('elastic_net', SklearnElasticNet(alpha=alpha, l1_ratio=l1_ratio, random_state=42, max_iter=2000))
        ])
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model"""
        # Handle missing values
        X_clean = X.fillna(0)
        y_clean = y.fillna(0)
        self.model.fit(X_clean, y_clean)
        self.is_fitted = True
        return self
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        # Handle missing values
        X_clean = X.fillna(0)
        predictions = self.model.predict(X_clean)
        return pd.Series(predictions, index=X.index)