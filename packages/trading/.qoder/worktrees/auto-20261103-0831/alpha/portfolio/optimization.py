"""
Portfolio Optimization
Mean-variance optimization and other portfolio construction methods
"""
import pandas as pd
import numpy as np
from typing import Union, Optional, Dict, Any, Tuple
from abc import ABC, abstractmethod
from scipy.optimize import minimize

# Optional CVXPY import for advanced optimization
try:
    import cvxpy as cp
    CVXPY_AVAILABLE = True
except ImportError:
    CVXPY_AVAILABLE = False
    cp = None


class PortfolioOptimizer(ABC):
    """
    Abstract base class for portfolio optimizers
    """
    
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.weights_ = None
        self.expected_return_ = None
        self.volatility_ = None
        self.sharpe_ratio_ = None
    
    @abstractmethod
    def fit(self, 
            expected_returns: Union[pd.Series, np.ndarray],
            covariance: Union[pd.DataFrame, np.ndarray],
            **kwargs) -> 'PortfolioOptimizer':
        """
        Fit the portfolio optimizer to calculate optimal weights
        
        Parameters:
        -----------
        expected_returns : array-like
            Expected returns for each asset
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        pass
    
    def get_weights(self) -> Union[pd.Series, np.ndarray]:
        """
        Get the optimal portfolio weights
        
        Returns:
        --------
        weights : array-like
            Optimal portfolio weights
        """
        return self.weights_
    
    def get_expected_return(self) -> float:
        """
        Get the expected portfolio return
        
        Returns:
        --------
        expected_return : float
            Expected portfolio return
        """
        return self.expected_return_
    
    def get_volatility(self) -> float:
        """
        Get the portfolio volatility
        
        Returns:
        --------
        volatility : float
            Portfolio volatility
        """
        return self.volatility_
    
    def get_sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        """
        Get the portfolio Sharpe ratio
        
        Parameters:
        -----------
        risk_free_rate : float
            Risk-free rate
            
        Returns:
        --------
        sharpe_ratio : float
            Portfolio Sharpe ratio
        """
        if self.volatility_ == 0:
            return 0.0
        return (self.expected_return_ - risk_free_rate) / self.volatility_


class MeanVarianceOptimizer(PortfolioOptimizer):
    """
    Mean-Variance Optimizer (Markowitz)
    Maximizes expected return for a given level of risk
    """
    
    def __init__(self, risk_aversion: float = 1.0, **kwargs):
        """
        Parameters:
        -----------
        risk_aversion : float
            Risk aversion parameter (higher = more risk averse)
        """
        super().__init__(**kwargs)
        self.risk_aversion = risk_aversion
    
    def fit(self, 
            expected_returns: Union[pd.Series, np.ndarray],
            covariance: Union[pd.DataFrame, np.ndarray],
            **kwargs) -> 'MeanVarianceOptimizer':
        """
        Fit the Mean-Variance Optimizer
        
        Parameters:
        -----------
        expected_returns : array-like
            Expected returns for each asset
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy arrays if needed
        if isinstance(expected_returns, pd.Series):
            expected_returns = expected_returns.values
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = len(expected_returns)
        
        # Define objective function: maximize utility = expected_return - risk_aversion * variance
        def objective(w):
            port_return = np.dot(w, expected_returns)
            port_variance = np.dot(w.T, np.dot(covariance, w))
            utility = port_return - self.risk_aversion * port_variance
            return -utility  # Minimize negative utility
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Bounds: weights between -1 and 1 (allowing short positions)
        bounds = tuple((-1, 1) for _ in range(n_assets))
        
        # Initial guess (equal weights)
        weights_init = np.ones(n_assets) / n_assets
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        self.expected_return_ = np.dot(self.weights_, expected_returns)
        self.volatility_ = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        
        return self


class MinVarianceOptimizer(PortfolioOptimizer):
    """
    Minimum Variance Optimizer
    Finds weights that minimize portfolio variance
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Union[pd.Series, np.ndarray],
            covariance: Union[pd.DataFrame, np.ndarray],
            **kwargs) -> 'MinVarianceOptimizer':
        """
        Fit the Minimum Variance Optimizer
        
        Parameters:
        -----------
        expected_returns : array-like
            Expected returns for each asset (not used in MinVar)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = len(expected_returns) if expected_returns is not None else covariance.shape[0]
        
        # Define objective function: minimize portfolio variance
        def objective(w):
            return np.dot(w.T, np.dot(covariance, w))
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Bounds: weights between -1 and 1 (allowing short positions)
        bounds = tuple((-1, 1) for _ in range(n_assets))
        
        # Initial guess (equal weights)
        weights_init = np.ones(n_assets) / n_assets
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        if expected_returns is not None:
            self.expected_return_ = np.dot(self.weights_, expected_returns)
        else:
            self.expected_return_ = 0.0
        self.volatility_ = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        
        return self


class MaxSharpeOptimizer(PortfolioOptimizer):
    """
    Maximum Sharpe Ratio Optimizer
    Finds weights that maximize the Sharpe ratio
    """
    
    def __init__(self, risk_free_rate: float = 0.0, **kwargs):
        """
        Parameters:
        -----------
        risk_free_rate : float
            Risk-free rate
        """
        super().__init__(**kwargs)
        self.risk_free_rate = risk_free_rate
    
    def fit(self, 
            expected_returns: Union[pd.Series, np.ndarray],
            covariance: Union[pd.DataFrame, np.ndarray],
            **kwargs) -> 'MaxSharpeOptimizer':
        """
        Fit the Maximum Sharpe Ratio Optimizer
        
        Parameters:
        -----------
        expected_returns : array-like
            Expected returns for each asset
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy arrays if needed
        if isinstance(expected_returns, pd.Series):
            expected_returns = expected_returns.values
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = len(expected_returns)
        
        # Define objective function: minimize negative Sharpe ratio
        def objective(w):
            port_return = np.dot(w, expected_returns)
            port_variance = np.dot(w.T, np.dot(covariance, w))
            port_volatility = np.sqrt(port_variance)
            
            # Avoid division by zero
            if port_volatility == 0:
                return 0.0
            
            sharpe_ratio = (port_return - self.risk_free_rate) / port_volatility
            return -sharpe_ratio  # Minimize negative Sharpe ratio
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Bounds: weights between -1 and 1 (allowing short positions)
        bounds = tuple((-1, 1) for _ in range(n_assets))
        
        # Initial guess (equal weights)
        weights_init = np.ones(n_assets) / n_assets
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        self.expected_return_ = np.dot(self.weights_, expected_returns)
        self.volatility_ = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        
        return self


class RiskParityOptimizer(PortfolioOptimizer):
    """
    Risk Parity Optimizer
    Allocates risk so that each asset contributes equally to portfolio risk
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Union[pd.Series, np.ndarray],
            covariance: Union[pd.DataFrame, np.ndarray],
            **kwargs) -> 'RiskParityOptimizer':
        """
        Fit the Risk Parity Optimizer
        
        Parameters:
        -----------
        expected_returns : array-like
            Expected returns for each asset (not used in Risk Parity)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = len(expected_returns) if expected_returns is not None else covariance.shape[0]
        
        # Define objective function: minimize sum of squared differences in risk contributions
        def objective(w):
            # Calculate portfolio volatility
            port_vol = np.sqrt(np.dot(w.T, np.dot(covariance, w)))
            
            # Avoid division by zero
            if port_vol == 0:
                return 0.0
            
            # Calculate marginal risk contributions
            mrc = np.dot(covariance, w) / port_vol
            
            # Calculate risk contributions
            rc = w * mrc
            
            # Target: equal risk contribution
            target_rc = np.sum(rc) / n_assets
            
            # Sum of squared differences from target
            return np.sum((rc - target_rc) ** 2)
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Bounds: weights between 0 and 1 (long-only)
        bounds = tuple((0, 1) for _ in range(n_assets))
        
        # Initial guess (equal weights)
        weights_init = np.ones(n_assets) / n_assets
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        if expected_returns is not None:
            self.expected_return_ = np.dot(self.weights_, expected_returns)
        else:
            self.expected_return_ = 0.0
        self.volatility_ = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        
        return self


class MaximumDiversificationOptimizer(PortfolioOptimizer):
    """
    Maximum Diversification Optimizer
    Maximizes the diversification ratio (weighted avg volatility / portfolio volatility)
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Union[pd.Series, np.ndarray],
            covariance: Union[pd.DataFrame, np.ndarray],
            **kwargs) -> 'MaximumDiversificationOptimizer':
        """
        Fit the Maximum Diversification Optimizer
        
        Parameters:
        -----------
        expected_returns : array-like
            Expected returns for each asset (not used in MaxDiv)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy arrays if needed
        if isinstance(expected_returns, pd.Series):
            expected_returns = expected_returns.values
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = len(expected_returns) if expected_returns is not None else covariance.shape[0]
        
        # Calculate weighted average volatility
        volatilities = np.sqrt(np.diag(covariance))
        
        # Define objective function: minimize negative diversification ratio
        def objective(w):
            # Calculate portfolio volatility
            port_vol = np.sqrt(np.dot(w.T, np.dot(covariance, w)))
            
            # Avoid division by zero
            if port_vol == 0:
                return 0.0
            
            # Calculate weighted average volatility
            wt_avg_vol = np.dot(w, volatilities)
            
            # Diversification ratio
            dr = wt_avg_vol / port_vol
            
            # Return negative DR for minimization
            return -dr
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Bounds: weights between 0 and 1 (long-only)
        bounds = tuple((0, 1) for _ in range(n_assets))
        
        # Initial guess (equal weights)
        weights_init = np.ones(n_assets) / n_assets
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        if expected_returns is not None:
            self.expected_return_ = np.dot(self.weights_, expected_returns)
        else:
            self.expected_return_ = 0.0
        self.volatility_ = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        
        return self


class EqualWeightOptimizer(PortfolioOptimizer):
    """
    Equal Weight Optimizer
    Allocates equal weight to each asset
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Union[pd.Series, np.ndarray],
            covariance: Union[pd.DataFrame, np.ndarray],
            **kwargs) -> 'EqualWeightOptimizer':
        """
        Fit the Equal Weight Optimizer
        
        Parameters:
        -----------
        expected_returns : array-like
            Expected returns for each asset
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            n_assets = covariance.shape[0]
        else:
            n_assets = covariance.shape[0]
        
        # Equal weights
        self.weights_ = np.ones(n_assets) / n_assets
        
        # Calculate expected return and volatility if inputs provided
        if expected_returns is not None and covariance is not None:
            if isinstance(expected_returns, pd.Series):
                expected_returns = expected_returns.values
            if isinstance(covariance, pd.DataFrame):
                covariance = covariance.values
            
            self.expected_return_ = np.dot(self.weights_, expected_returns)
            self.volatility_ = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        else:
            self.expected_return_ = 0.0
            self.volatility_ = 0.0
        
        return self


class ConstrainedOptimizer(PortfolioOptimizer):
    """
    Constrained Optimizer
    Mean-variance optimization with various constraints
    """
    
    def __init__(self, 
                 max_weight: float = 1.0,
                 min_weight: float = -1.0,
                 max_turnover: Optional[float] = None,
                 current_weights: Optional[Union[pd.Series, np.ndarray]] = None,
                 **kwargs):
        """
        Parameters:
        -----------
        max_weight : float
            Maximum weight for any asset
        min_weight : float
            Minimum weight for any asset
        max_turnover : float, optional
            Maximum portfolio turnover
        current_weights : array-like, optional
            Current portfolio weights (for turnover constraint)
        """
        super().__init__(**kwargs)
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.max_turnover = max_turnover
        self.current_weights = current_weights
    
    def fit(self, 
            expected_returns: Union[pd.Series, np.ndarray],
            covariance: Union[pd.DataFrame, np.ndarray],
            **kwargs) -> 'ConstrainedOptimizer':
        """
        Fit the Constrained Optimizer
        
        Parameters:
        -----------
        expected_returns : array-like
            Expected returns for each asset
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy arrays if needed
        if isinstance(expected_returns, pd.Series):
            expected_returns = expected_returns.values
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = len(expected_returns)
        
        # Define objective function: maximize utility = expected_return - risk_aversion * variance
        # Using risk_aversion = 1.0 as default
        risk_aversion = self.kwargs.get('risk_aversion', 1.0)
        
        def objective(w):
            port_return = np.dot(w, expected_returns)
            port_variance = np.dot(w.T, np.dot(covariance, w))
            utility = port_return - risk_aversion * port_variance
            return -utility  # Minimize negative utility
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Add turnover constraint if specified
        if self.max_turnover is not None and self.current_weights is not None:
            # Convert current_weights to numpy if needed
            if isinstance(self.current_weights, pd.Series):
                current_weights = self.current_weights.values
            else:
                current_weights = self.current_weights
            
            # Turnover constraint: sum of absolute weight changes <= max_turnover
            def turnover_constraint(w):
                return self.max_turnover - np.sum(np.abs(w - current_weights))
            
            constraints = ({
                'type': 'eq', 'fun': lambda w: np.sum(w) - 1
            }, {
                'type': 'ineq', 'fun': turnover_constraint
            })
        
        # Bounds: weights between min_weight and max_weight
        bounds = tuple((self.min_weight, self.max_weight) for _ in range(n_assets))
        
        # Initial guess (equal weights)
        weights_init = np.ones(n_assets) / n_assets
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        self.expected_return_ = np.dot(self.weights_, expected_returns)
        self.volatility_ = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        
        return self