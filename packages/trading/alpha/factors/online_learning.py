"""
Online Learning / Adaptive Factors Module
Implements EWMA, Kalman filter, online ridge regression for adaptive factor weights
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union, Literal
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import logging
from scipy.linalg import cho_factor, cho_solve

logger = logging.getLogger(__name__)


@dataclass
class OnlineModelState:
    """State of an online learning model"""
    weights: np.ndarray
    covariance: Optional[np.ndarray] = None
    step: int = 0
    metrics: Dict = field(default_factory=dict)


class OnlineLearner(ABC):
    """Abstract base class for online learners"""
    
    @abstractmethod
    def update(self, x: np.ndarray, y: float) -> None:
        """Update model with new observation"""
        pass
    
    @abstractmethod
    def predict(self, x: np.ndarray) -> float:
        """Make prediction"""
        pass
    
    @abstractmethod
    def get_state(self) -> OnlineModelState:
        """Get current model state"""
        pass


class EWMAWeights:
    """
    Exponentially Weighted Moving Average for factor weights.
    Adapts factor weights based on recent performance.
    """
    
    def __init__(
        self,
        n_factors: int,
        alpha: float = 0.1,  # Decay factor (0.1 = 10-day half-life approx)
        min_weight: float = 0.0,
        max_weight: float = 1.0,
        normalize: bool = True,
    ):
        self.n_factors = n_factors
        self.alpha = alpha
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.normalize = normalize
        self.weights = np.ones(n_factors) / n_factors
        self.performance = np.zeros(n_factors)
        self.step = 0
    
    def update(self, factor_returns: np.ndarray, portfolio_return: float) -> np.ndarray:
        """
        Update weights based on factor performance.
        
        Args:
            factor_returns: Returns of each factor (n_factors,)
            portfolio_return: Overall portfolio return
        
        Returns:
            Updated weights
        """
        # Compute factor performance relative to portfolio
        relative_perf = factor_returns - portfolio_return
        
        # Update exponential moving average of performance
        self.performance = (1 - self.alpha) * self.performance + self.alpha * relative_perf
        
        # Softmax weights based on performance
        exp_perf = np.exp(self.performance)
        self.weights = exp_perf / exp_perf.sum()
        
        # Apply bounds
        self.weights = np.clip(self.weights, self.min_weight, self.max_weight)
        
        if self.normalize:
            self.weights = self.weights / self.weights.sum()
        
        self.step += 1
        return self.weights.copy()
    
    def get_weights(self) -> np.ndarray:
        return self.weights.copy()


class OnlineRidgeRegression(OnlineLearner):
    """
    Online Ridge Regression using Recursive Least Squares (RLS) with forgetting factor.
    Equivalent to ridge regression with exponentially decaying weights.
    """
    
    def __init__(
        self,
        n_features: int,
        lambda_reg: float = 1.0,  # Ridge regularization
        forgetting_factor: float = 0.99,  # Forgetting factor (1.0 = no forgetting)
        initial_cov: float = 1000.0,  # Initial covariance diagonal
    ):
        self.n_features = n_features
        self.lambda_reg = lambda_reg
        self.forgetting_factor = forgetting_factor
        
        # Initialize RLS state
        self.weights = np.zeros(n_features)
        self.P = np.eye(n_features) * initial_cov  # Inverse covariance
        self.step = 0
    
    def update(self, x: np.ndarray, y: float) -> None:
        """
        Update model with new observation using RLS.
        
        Args:
            x: Feature vector (n_features,)
            y: Target value
        """
        x = np.asarray(x).reshape(-1)
        assert len(x) == self.n_features
        
        # RLS update with forgetting factor
        # P = (1/ff) * (P - P x x^T P / (ff + x^T P x))
        Px = self.P @ x
        denominator = self.forgetting_factor + x @ Px
        
        if denominator > 1e-10:
            self.P = (self.P - np.outer(Px, Px) / denominator) / self.forgetting_factor
        
        # Add ridge regularization to P diagonal
        self.P += np.eye(self.n_features) * self.lambda_reg / (self.step + 1)
        
        # Update weights
        prediction = self.weights @ x
        error = y - prediction
        self.weights += self.P @ x * error
        
        self.step += 1
    
    def predict(self, x: np.ndarray) -> float:
        """Make prediction"""
        x = np.asarray(x).reshape(-1)
        return float(self.weights @ x)
    
    def get_state(self) -> OnlineModelState:
        return OnlineModelState(
            weights=self.weights.copy(),
            covariance=self.P.copy(),
            step=self.step,
            metrics={'lambda_reg': self.lambda_reg, 'forgetting_factor': self.forgetting_factor}
        )


class KalmanFactorModel(OnlineLearner):
    """
    Kalman Filter for dynamic factor model.
    Models factor weights as hidden state with linear dynamics.
    """
    
    def __init__(
        self,
        n_factors: int,
        process_noise: float = 1e-4,  # Q: process noise covariance
        observation_noise: float = 1e-2,  # R: observation noise
        transition_matrix: Optional[np.ndarray] = None,  # F: state transition
    ):
        self.n_factors = n_factors
        
        # State: factor weights
        self.x = np.zeros(n_factors)  # State estimate
        self.P = np.eye(n_factors) * 100.0  # State covariance
        
        # Dynamics
        self.F = transition_matrix if transition_matrix is not None else np.eye(n_factors)
        self.Q = np.eye(n_factors) * process_noise
        self.R = observation_noise
        
        self.step = 0
    
    def update(self, factor_values: np.ndarray, portfolio_return: float) -> np.ndarray:
        """
        Kalman filter update.
        
        Args:
            factor_values: Current factor values (n_factors,)
            portfolio_return: Observed portfolio return
        
        Returns:
            Updated factor weights
        """
        factor_values = np.asarray(factor_values).reshape(-1)
        assert len(factor_values) == self.n_factors
        
        # Predict step
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        
        # Update step
        # H = factor_values^T (observation matrix)
        H = factor_values.reshape(1, -1)
        y = portfolio_return - H @ self.x  # Innovation
        S = H @ self.P @ H.T + self.R  # Innovation covariance
        K = self.P @ H.T / S  # Kalman gain
        
        self.x = self.x + K.flatten() * y
        self.P = (np.eye(self.n_factors) - K @ H) @ self.P
        
        self.step += 1
        return self.x.copy()
    
    def predict(self, factor_values: np.ndarray) -> float:
        """Predict portfolio return given factor values"""
        factor_values = np.asarray(factor_values).reshape(-1)
        return float(factor_values @ self.x)
    
    def get_state(self) -> OnlineModelState:
        return OnlineModelState(
            weights=self.x.copy(),
            covariance=self.P.copy(),
            step=self.step,
            metrics={'process_noise': np.trace(self.Q), 'observation_noise': self.R}
        )


class AdaptiveFactorCombiner:
    """
    Combines multiple factors using online learning.
    Supports multiple combination methods: EWMA, Ridge, Kalman, or ensemble.
    """
    
    def __init__(
        self,
        factor_names: List[str],
        method: Literal["ewma", "ridge", "kalman", "ensemble"] = "ensemble",
        **kwargs
    ):
        self.factor_names = factor_names
        self.n_factors = len(factor_names)
        self.method = method
        
        if method == "ewma":
            self.learner = EWMAWeights(self.n_factors, **kwargs)
        elif method == "ridge":
            self.learner = OnlineRidgeRegression(self.n_factors, **kwargs)
        elif method == "kalman":
            self.learner = KalmanFactorModel(self.n_factors, **kwargs)
        elif method == "ensemble":
            self.learners = {
                'ewma': EWMAWeights(self.n_factors, **kwargs.get('ewma', {})),
                'ridge': OnlineRidgeRegression(self.n_factors, **kwargs.get('ridge', {})),
                'kalman': KalmanFactorModel(self.n_factors, **kwargs.get('kalman', {})),
            }
            self.ensemble_weights = np.ones(3) / 3
        else:
            raise ValueError(f"Unknown method: {method}")
        
        self.step = 0
        self.history = []
    
    def update(
        self,
        factor_values: np.ndarray,
        factor_returns: np.ndarray,
        portfolio_return: float,
    ) -> np.ndarray:
        """
        Update all learners and return combined weights.
        
        Args:
            factor_values: Current factor values (n_factors,)
            factor_returns: Recent returns of each factor (n_factors,)
            portfolio_return: Portfolio return
        
        Returns:
            Combined factor weights
        """
        factor_values = np.asarray(factor_values).reshape(-1)
        factor_returns = np.asarray(factor_returns).reshape(-1)
        
        if self.method == "ensemble":
            weights_list = []
            
            # EWMA update
            ewma_w = self.learners['ewma'].update(factor_returns, portfolio_return)
            weights_list.append(ewma_w)
            
            # Ridge update (using factor values as features, portfolio return as target)
            self.learners['ridge'].update(factor_values, portfolio_return)
            ridge_w = np.abs(self.learners['ridge'].weights)
            if ridge_w.sum() > 0:
                ridge_w = ridge_w / ridge_w.sum()
            else:
                ridge_w = np.ones(self.n_factors) / self.n_factors
            weights_list.append(ridge_w)
            
            # Kalman update
            kalman_w = self.learners['kalman'].update(factor_values, portfolio_return)
            kalman_w = np.abs(kalman_w)
            if kalman_w.sum() > 0:
                kalman_w = kalman_w / kalman_w.sum()
            else:
                kalman_w = np.ones(self.n_factors) / self.n_factors
            weights_list.append(kalman_w)
            
            # Average ensemble
            combined = np.mean(weights_list, axis=0)
            combined = combined / combined.sum()
            
        else:
            if self.method == "ewma":
                combined = self.learner.update(factor_returns, portfolio_return)
            elif self.method == "ridge":
                self.learner.update(factor_values, portfolio_return)
                combined = np.abs(self.learner.weights)
                if combined.sum() > 0:
                    combined = combined / combined.sum()
                else:
                    combined = np.ones(self.n_factors) / self.n_factors
            elif self.method == "kalman":
                combined = self.learner.update(factor_values, portfolio_return)
                combined = np.abs(combined)
                if combined.sum() > 0:
                    combined = combined / combined.sum()
                else:
                    combined = np.ones(self.n_factors) / self.n_factors
        
        self.step += 1
        self.history.append({
            'step': self.step,
            'weights': combined.copy(),
            'factor_values': factor_values.copy(),
            'portfolio_return': portfolio_return,
        })
        
        return combined
    
    def get_weights(self) -> np.ndarray:
        if self.method == "ensemble":
            weights_list = [
                self.learners['ewma'].get_weights(),
                np.abs(self.learners['ridge'].weights),
                np.abs(self.learners['kalman'].x),
            ]
            # Normalize each
            weights_list = [w / w.sum() if w.sum() > 0 else np.ones(self.n_factors) / self.n_factors 
                          for w in weights_list]
            return np.mean(weights_list, axis=0)
        elif self.method == "ewma":
            return self.learner.get_weights()
        elif self.method == "ridge":
            w = np.abs(self.learner.weights)
            return w / w.sum() if w.sum() > 0 else np.ones(self.n_factors) / self.n_factors
        elif self.method == "kalman":
            w = np.abs(self.learner.x)
            return w / w.sum() if w.sum() > 0 else np.ones(self.n_factors) / self.n_factors
    
    def get_state(self) -> Dict:
        if self.method == "ensemble":
            return {
                'ewma': self.learners['ewma'].performance,
                'ridge': self.learners['ridge'].get_state().__dict__,
                'kalman': self.learners['kalman'].get_state().__dict__,
            }
        else:
            return self.learner.get_state().__dict__


def create_adaptive_combiner(
    factor_names: List[str],
    method: str = "ensemble",
    **kwargs
) -> AdaptiveFactorCombiner:
    """Factory function for adaptive factor combiner"""
    return AdaptiveFactorCombiner(factor_names, method, **kwargs)


if __name__ == "__main__":
    # Quick test
    np.random.seed(42)
    n_factors = 5
    n_periods = 200
    factor_names = [f'factor_{i}' for i in range(n_factors)]
    
    # Create adaptive combiner
    combiner = AdaptiveFactorCombiner(
        factor_names,
        method="ensemble",
        ewma={'alpha': 0.1},
        ridge={'lambda_reg': 1.0, 'forgetting_factor': 0.99},
        kalman={'process_noise': 1e-4, 'observation_noise': 1e-2},
    )
    
    # Simulate factor values and returns
    for t in range(n_periods):
        factor_vals = np.random.normal(0, 1, n_factors)
        factor_rets = np.random.normal(0.001, 0.02, n_factors)
        portfolio_ret = np.sum(factor_vals * factor_rets) * 0.5 + np.random.normal(0, 0.01)
        
        weights = combiner.update(factor_vals, factor_rets, portfolio_ret)
    
    print("Final weights:", combiner.get_weights())
    print("EWMA performance:", combiner.learners['ewma'].performance)
    print("Ridge weights:", combiner.learners['ridge'].weights)
    print("Kalman state:", combiner.learners['kalman'].x)