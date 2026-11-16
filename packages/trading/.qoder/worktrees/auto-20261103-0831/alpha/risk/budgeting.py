"""
Risk Budgeting
Methods for allocating risk across assets in a portfolio
"""
import pandas as pd
import numpy as np
from typing import Union, Optional, Dict, Any
from abc import ABC, abstractmethod
from scipy.optimize import minimize


class RiskBudgeter(ABC):
    """
    Abstract base class for risk budgeting methods
    """
    
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.weights_ = None
        self.marginal_risk_contributions_ = None
        self.risk_contributions_ = None
    
    @abstractmethod
    def fit(self, 
            expected_returns: Optional[Union[pd.Series, np.ndarray]] = None,
            covariance: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            **kwargs) -> 'RiskBudgeter':
        """
        Fit the risk budgeting method to calculate optimal weights
        
        Parameters:
        -----------
        expected_returns : array-like, optional
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
    
    def get_marginal_risk_contributions(self) -> Union[pd.Series, np.ndarray]:
        """
        Get the marginal risk contributions of each asset
        
        Returns:
        --------
        mrc : array-like
            Marginal risk contributions
        """
        return self.marginal_risk_contributions_
    
    def get_risk_contributions(self) -> Union[pd.Series, np.ndarray]:
        """
        Get the risk contributions of each asset
        
        Returns:
        --------
        rc : array-like
            Risk contributions
        """
        return self.risk_contributions_


class EqualRiskBudgeter(RiskBudgeter):
    """
    Equal Risk Budgeting (ERC) - allocates equal risk to each asset
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Optional[Union[pd.Series, np.ndarray]] = None,
            covariance: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            **kwargs) -> 'EqualRiskBudgeter':
        """
        Fit the Equal Risk Budgeting method
        
        Parameters:
        -----------
        expected_returns : array-like, optional
            Expected returns for each asset (not used in ERC)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        if covariance is None:
            raise ValueError("Covariance matrix must be provided")
        
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = covariance.shape[0]
        
        # Initialize weights (equal weights as starting point)
        weights_init = np.ones(n_assets) / n_assets
        
        # Define objective function for ERC: sum of squared differences in risk contributions
        def objective(w):
            # Calculate portfolio volatility
            port_vol = np.sqrt(np.dot(w.T, np.dot(covariance, w)))
            
            # Calculate marginal risk contributions
            mrc = np.dot(covariance, w) / port_vol
            
            # Calculate risk contributions
            rc = w * mrc
            
            # Target risk contribution (equal for all assets)
            target_rc = port_vol / n_assets
            
            # Sum of squared differences from target
            return np.sum((rc - target_rc) ** 2)
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Bounds: weights between 0 and 1 (long-only)
        bounds = tuple((0, 1) for _ in range(n_assets))
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        
        # Calculate marginal and risk contributions
        port_vol = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        self.marginal_risk_contributions_ = np.dot(covariance, self.weights_) / port_vol
        self.risk_contributions_ = self.weights_ * self.marginal_risk_contributions_
        
        return self


class MaximumDiversificationBudgeter(RiskBudgeter):
    """
    Maximum Diversification Portfolio - maximizes diversification ratio
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Optional[Union[pd.Series, np.ndarray]] = None,
            covariance: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            **kwargs) -> 'MaximumDiversificationBudgeter':
        """
        Fit the Maximum Diversification Budgeting method
        
        Parameters:
        -----------
        expected_returns : array-like, optional
            Expected returns for each asset (not used in MaxDiv)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        if covariance is None:
            raise ValueError("Covariance matrix must be provided")
        
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = covariance.shape[0]
        
        # Calculate weighted average volatility
        volatilities = np.sqrt(np.diag(covariance))
        
        # Initialize weights (equal weights as starting point)
        weights_init = np.ones(n_assets) / n_assets
        
        # Define objective function for MaxDiv: negative diversification ratio
        def objective(w):
            # Calculate portfolio volatility
            port_vol = np.sqrt(np.dot(w.T, np.dot(covariance, w)))
            
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
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        
        # Calculate marginal and risk contributions
        port_vol = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        self.marginal_risk_contributions_ = np.dot(covariance, self.weights_) / port_vol
        self.risk_contributions_ = self.weights_ * self.marginal_risk_contributions_
        
        return self


class RiskParityBudgeter(RiskBudgeter):
    """
    Risk Parity Budgeting - allocates risk so that each asset contributes equally to portfolio risk
    (Similar to Equal Risk Budgeting but formulated differently)
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Optional[Union[pd.Series, np.ndarray]] = None,
            covariance: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            **kwargs) -> 'RiskParityBudgeter':
        """
        Fit the Risk Parity Budgeting method
        
        Parameters:
        -----------
        expected_returns : array-like, optional
            Expected returns for each asset (not used in Risk Parity)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        if covariance is None:
            raise ValueError("Covariance matrix must be provided")
        
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = covariance.shape[0]
        
        # Initialize weights (equal weights as starting point)
        weights_init = np.ones(n_assets) / n_assets
        
        # Define objective function for Risk Parity: sum of squared differences in log risk contributions
        def objective(w):
            # Calculate portfolio volatility
            port_vol = np.sqrt(np.dot(w.T, np.dot(covariance, w)))
            
            # Calculate marginal risk contributions
            mrc = np.dot(covariance, w) / port_vol
            
            # Calculate risk contributions
            rc = w * mrc
            
            # Target: equal risk contribution in log space
            # Avoid log(0) by adding small epsilon
            eps = 1e-8
            log_rc = np.log(rc + eps)
            target_log_rc = np.mean(log_rc)
            
            # Sum of squared differences from target
            return np.sum((log_rc - target_log_rc) ** 2)
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Bounds: weights between 0 and 1 (long-only)
        bounds = tuple((0, 1) for _ in range(n_assets))
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        
        # Calculate marginal and risk contributions
        port_vol = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        self.marginal_risk_contributions_ = np.dot(covariance, self.weights_) / port_vol
        self.risk_contributions_ = self.weights_ * self.marginal_risk_contributions_
        
        return self


class EqualWeightBudgeter(RiskBudgeter):
    """
    Equal Weight Budgeting - allocates equal weight to each asset
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Optional[Union[pd.Series, np.ndarray]] = None,
            covariance: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            **kwargs) -> 'EqualWeightBudgeter':
        """
        Fit the Equal Weight Budgeting method
        
        Parameters:
        -----------
        expected_returns : array-like, optional
            Expected returns for each asset (not used in Equal Weight)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        if covariance is None:
            raise ValueError("Covariance matrix must be provided")
        
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            n_assets = covariance.shape[0]
        else:
            n_assets = covariance.shape[0]
        
        # Equal weights
        self.weights_ = np.ones(n_assets) / n_assets
        
        # Calculate marginal and risk contributions if covariance provided
        if covariance is not None:
            if isinstance(covariance, pd.DataFrame):
                covariance = covariance.values
            
            port_vol = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
            self.marginal_risk_contributions_ = np.dot(covariance, self.weights_) / port_vol
            self.risk_contributions_ = self.weights_ * self.marginal_risk_contributions_
        
        return self


class VolatilityWeightedBudgeter(RiskBudgeter):
    """
    Volatility Weighted Budgeting - allocates weights inversely proportional to volatility
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Optional[Union[pd.Series, np.ndarray]] = None,
            covariance: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            **kwargs) -> 'VolatilityWeightedBudgeter':
        """
        Fit the Volatility Weighted Budgeting method
        
        Parameters:
        -----------
        expected_returns : array-like, optional
            Expected returns for each asset (not used in Volatility Weighted)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        if covariance is None:
            raise ValueError("Covariance matrix must be provided")
        
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            volatilities = np.sqrt(np.diag(covariance.values))
        else:
            volatilities = np.sqrt(np.diag(covariance))
        
        # Avoid division by zero
        volatilities = np.where(volatilities == 0, 1e-8, volatilities)
        
        # Inverse volatility weights
        weights = 1.0 / volatilities
        
        # Normalize to sum to 1
        self.weights_ = weights / np.sum(weights)
        
        # Calculate marginal and risk contributions
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        port_vol = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        self.marginal_risk_contributions_ = np.dot(covariance, self.weights_) / port_vol
        self.risk_contributions_ = self.weights_ * self.marginal_risk_contributions_
        
        return self


class MinimumVarianceBudgeter(RiskBudgeter):
    """
    Minimum Variance Budgeting - finds weights that minimize portfolio variance
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def fit(self, 
            expected_returns: Optional[Union[pd.Series, np.ndarray]] = None,
            covariance: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            **kwargs) -> 'MinimumVarianceBudgeter':
        """
        Fit the Minimum Variance Budgeting method
        
        Parameters:
        -----------
        expected_returns : array-like, optional
            Expected returns for each asset (not used in MinVar)
        covariance : array-like
            Covariance matrix of asset returns
            
        Returns:
        --------
        self : object
            Returns self
        """
        if covariance is None:
            raise ValueError("Covariance matrix must be provided")
        
        # Convert to numpy array if needed
        if isinstance(covariance, pd.DataFrame):
            covariance = covariance.values
        
        n_assets = covariance.shape[0]
        
        # Initialize weights (equal weights as starting point)
        weights_init = np.ones(n_assets) / n_assets
        
        # Define objective function: portfolio variance
        def objective(w):
            return np.dot(w.T, np.dot(covariance, w))
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        
        # Bounds: weights between 0 and 1 (long-only)
        bounds = tuple((0, 1) for _ in range(n_assets))
        
        # Optimize
        result = minimize(objective, weights_init, method='SLSQP', 
                         bounds=bounds, constraints=constraints)
        
        # Store results
        self.weights_ = result.x
        
        # Calculate marginal and risk contributions
        port_vol = np.sqrt(np.dot(self.weights_.T, np.dot(covariance, self.weights_)))
        self.marginal_risk_contributions_ = np.dot(covariance, self.weights_) / port_vol
        self.risk_contributions_ = self.weights_ * self.marginal_risk_contributions_
        
        return self