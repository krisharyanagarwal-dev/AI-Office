"""
Covariance Estimation
Various methods for estimating covariance matrices
"""
import pandas as pd
import numpy as np
from typing import Union, Optional, Dict, Any
from sklearn.covariance import LedoitWolf, OAS
from abc import ABC, abstractmethod


class CovarianceEstimator(ABC):
    """
    Abstract base class for covariance estimators
    """
    
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.covariance_ = None
        self.precision_ = None
    
    @abstractmethod
    def fit(self, X: Union[pd.DataFrame, np.ndarray]) -> 'CovarianceEstimator':
        """
        Fit the covariance estimator to data
        
        Parameters:
        -----------
        X : array-like
            Data matrix (observations x features)
            
        Returns:
        --------
        self : object
            Returns self
        """
        pass
    
    def get_covariance(self) -> Union[pd.DataFrame, np.ndarray]:
        """
        Get the estimated covariance matrix
        
        Returns:
        --------
        covariance : array-like
            Estimated covariance matrix
        """
        return self.covariance_
    
    def get_precision(self) -> Union[pd.DataFrame, np.ndarray]:
        """
        Get the estimated precision matrix (inverse covariance)
        
        Returns:
        --------
        precision : array-like
            Estimated precision matrix
        """
        return self.precision_


class SampleCovariance(CovarianceEstimator):
    """
    Sample covariance estimator
    """
    
    def __init__(self, bias: bool = False, **kwargs):
        """
        Parameters:
        -----------
        bias : bool
            If True, use biased estimator (divide by n)
            If False, use unbiased estimator (divide by n-1)
        """
        super().__init__(**kwargs)
        self.bias = bias
    
    def fit(self, X: Union[pd.DataFrame, np.ndarray]) -> 'SampleCovariance':
        """
        Fit the sample covariance estimator
        
        Parameters:
        -----------
        X : array-like
            Data matrix (observations x features)
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy array if needed
        if isinstance(X, pd.DataFrame):
            X = X.values
        
        # Calculate sample covariance
        if self.bias:
            # Biased estimator (divide by n)
            self.covariance_ = np.cov(X.T, bias=True)
        else:
            # Unbiased estimator (divide by n-1)
            self.covariance_ = np.cov(X.T, bias=False)
        
        # Calculate precision matrix (pseudo-inverse for stability)
        try:
            self.precision_ = np.linalg.inv(self.covariance_)
        except np.linalg.LinAlgError:
            # Use pseudo-inverse if matrix is singular
            self.precision_ = np.linalg.pinv(self.covariance_)
        
        return self


class ExponentiallyWeightedCovariance(CovarianceEstimator):
    """
    Exponentially weighted covariance estimator
    """
    
    def __init__(self, span: int = 60, **kwargs):
        """
        Parameters:
        -----------
        span : int
            Span for exponential decay (halflife in periods)
        """
        super().__init__(**kwargs)
        self.span = span
    
    def fit(self, X: Union[pd.DataFrame, np.ndarray]) -> 'ExponentiallyWeightedCovariance':
        """
        Fit the exponentially weighted covariance estimator
        
        Parameters:
        -----------
        X : array-like
            Data matrix (observations x features)
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to pandas DataFrame if needed for ewm
        if isinstance(X, np.ndarray):
            X = pd.DataFrame(X)
        
        # Calculate exponentially weighted covariance
        ewm_cov = X.ewm(span=self.span).cov()
        
        # Extract the most recent covariance matrix
        # The ewm.cov() returns a MultiIndex DataFrame with (date, asset) index
        # We want the last date's covariance matrix
        dates = X.index
        if len(dates) > 0:
            last_date = dates[-1]
            # Get covariance matrix for the last date
            self.covariance_ = ewm_cov.loc[last_date].values
        else:
            # Fallback to sample covariance if no data
            self.covariance_ = np.cov(X.T)
        
        # Calculate precision matrix
        try:
            self.precision_ = np.linalg.inv(self.covariance_)
        except np.linalg.LinAlgError:
            self.precision_ = np.linalg.pinv(self.covariance_)
        
        return self


class ShrinkageCovariance(CovarianceEstimator):
    """
    Shrinkage covariance estimator towards a target matrix
    """
    
    def __init__(self, shrinkage: float = 0.1, target: str = 'identity', **kwargs):
        """
        Parameters:
        -----------
        shrinkage : float
            Shrinkage intensity (0 = sample covariance, 1 = target)
        target : str
            Target matrix ('identity', 'constant_correlation', 'diagonal')
        """
        super().__init__(**kwargs)
        self.shrinkage = shrinkage
        self.target = target
    
    def fit(self, X: Union[pd.DataFrame, np.ndarray]) -> 'ShrinkageCovariance':
        """
        Fit the shrinkage covariance estimator
        
        Parameters:
        -----------
        X : array-like
            Data matrix (observations x features)
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy array if needed
        if isinstance(X, pd.DataFrame):
            X = X.values
        
        # Calculate sample covariance
        sample_cov = np.cov(X.T)
        
        # Calculate target matrix
        n_features = sample_cov.shape[0]
        
        if self.target == 'identity':
            target = np.eye(n_features)
        elif self.target == 'constant_correlation':
            # Constant correlation target
            avg_corr = np.sum(sample_cov * np.eye(n_features, k=1)) / (n_features * (n_features - 1))
            target = np.full((n_features, n_features), avg_corr)
            np.fill_diagonal(target, np.diag(sample_cov))
        elif self.target == 'diagonal':
            # Diagonal target (variances only)
            target = np.diag(np.diag(sample_cov))
        else:
            raise ValueError(f"Unknown target: {self.target}")
        
        # Apply shrinkage
        self.covariance_ = (1 - self.shrinkage) * sample_cov + self.shrinkage * target
        
        # Calculate precision matrix
        try:
            self.precision_ = np.linalg.inv(self.covariance_)
        except np.linalg.LinAlgError:
            self.precision_ = np.linalg.pinv(self.covariance_)
        
        return self


class LedoitWolfCovariance(CovarianceEstimator):
    """
    Ledoit-Wolf shrinkage covariance estimator
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.estimator = LedoitWolf(**kwargs)
    
    def fit(self, X: Union[pd.DataFrame, np.ndarray]) -> 'LedoitWolfCovariance':
        """
        Fit the Ledoit-Wolf covariance estimator
        
        Parameters:
        -----------
        X : array-like
            Data matrix (observations x features)
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy array if needed
        if isinstance(X, pd.DataFrame):
            X = X.values
        
        # Fit Ledoit-Wolf estimator
        self.estimator.fit(X)
        
        # Store covariance and precision matrices
        self.covariance_ = self.estimator.covariance_
        self.precision_ = self.estimator.precision_
        
        return self


class OracleApproximatingShrinkage(CovarianceEstimator):
    """
    Oracle Approximating Shrinkage covariance estimator
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.estimator = OAS(**kwargs)
    
    def fit(self, X: Union[pd.DataFrame, np.ndarray]) -> 'OracleApproximatingShrinkage':
        """
        Fit the OAS covariance estimator
        
        Parameters:
        -----------
        X : array-like
            Data matrix (observations x features)
            
        Returns:
        --------
        self : object
            Returns self
        """
        # Convert to numpy array if needed
        if isinstance(X, pd.DataFrame):
            X = X.values
        
        # Fit OAS estimator
        self.estimator.fit(X)
        
        # Store covariance and precision matrices
        self.covariance_ = self.estimator.covariance_
        self.precision_ = self.estimator.precision_
        
        return self