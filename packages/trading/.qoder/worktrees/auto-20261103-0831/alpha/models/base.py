"""
Base Model Class
Base class for all machine learning models in the alpha system
"""
import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod


class BaseModel(ABC):
    """
    Base class for all models
    Provides common interface and functionality
    """
    
    def __init__(self, name: str = "BaseModel", **kwargs):
        """
        Initialize base model
        
        Args:
            name: Model name for identification
            **kwargs: Additional model-specific parameters
        """
        self.name = name
        self.is_fitted = False
        self.params = kwargs
        self.model = None  # Actual model instance (sklearn, tf, torch, etc.)
    
    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> 'BaseModel':
        """
        Fit the model to training data
        
        Args:
            X: Feature DataFrame
            y: Target Series
            **kwargs: Additional fitting parameters
            
        Returns:
            self: Returns self for method chaining
        """
        pass
    
    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """
        Make predictions on new data
        
        Args:
            X: Feature DataFrame
            
        Returns:
            Predictions as Series
        """
        pass
    
    def get_params(self) -> Dict[str, Any]:
        """
        Get model parameters
        
        Returns:
            Dictionary of model parameters
        """
        return self.params.copy()
    
    def set_params(self, **params) -> 'BaseModel':
        """
        Set model parameters
        
        Args:
            **params: Parameters to set
            
        Returns:
            self: Returns self for method chaining
        """
        self.params.update(params)
        return self
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', fitted={self.is_fitted})"