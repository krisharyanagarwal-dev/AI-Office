"""
Walk-forward Validation
Walk-forward, purged K-fold, and combinatorial purged K-fold cross-validation
"""
import pandas as pd
import numpy as np
from typing import List, Tuple, Iterator, Optional, Any
from sklearn.base import BaseEstimator
from sklearn.model_selection import KFold
import itertools


class WalkForwardValidator:
    """
    Walk-forward validation (rolling window)
    """
    
    def __init__(
        self,
        n_splits: int = 5,
        window_size: Optional[int] = None,
        test_size: Optional[int] = None,
        max_train_size: Optional[int] = None,
        gap: int = 0
    ):
        self.n_splits = n_splits
        self.window_size = window_size
        self.test_size = test_size
        self.max_train_size = max_train_size
        self.gap = gap
    
    def split(self, X: pd.DataFrame, y: Optional[pd.Series] = None, groups=None) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """
        Generate indices to split data into training and test set.
        
        Parameters:
        -----------
        X : pd.DataFrame
            Training data, where n_samples is the number of samples
            and n_features is the number of features.
        y : pd.Series, optional
            Always ignored, exists for compatibility.
        groups : array-like, optional
            Always ignored, exists for compatibility.
            
        Yields:
        -------
        train : ndarray
            The training set indices for that split.
        test : ndarray
            The testing set indices for that split.
        """
        n_samples = len(X)
        
        # Set defaults
        if self.test_size is None:
            self.test_size = n_samples // (self.n_splits + 1)
        if self.window_size is None:
            self.window_size = n_samples - self.test_size * self.n_splits
        if self.max_train_size is None:
            self.max_train_size = self.window_size
        
        # Validate parameters
        if self.window_size + self.gap + self.test_size > n_samples:
            raise ValueError(
                f"Window size ({self.window_size}) + gap ({self.gap}) + "
                f"test size ({self.test_size}) exceeds number of samples ({n_samples})"
            )
        
        # Generate splits
        for i in range(self.n_splits):
            start = i * self.test_size
            end = start + self.test_size
            
            if start + self.window_size + self.gap > n_samples:
                break
            
            train_start = max(0, start - self.window_size)
            train_end = start - self.gap
            test_start = start
            test_end = end
            
            # Adjust for max_train_size
            if self.max_train_size is not None and self.max_train_size < self.window_size:
                train_start = train_end - self.max_train_size
            
            # Ensure indices are within bounds
            train_start = max(0, train_start)
            train_end = max(train_start, train_end)
            test_start = max(test_start, test_end)
            test_end = min(n_samples, test_end)
            
            if train_end <= train_start or test_end <= test_start:
                continue
                
            yield np.arange(train_start, train_end), np.arange(test_start, test_end)


class PurgedKFold(KFold):
    """
    Purged K-fold cross-validation
    Removes samples that are within the gap of the test set from the training set
    to avoid leakage due to overlapping observations.
    """
    
    def __init__(
        self,
        n_splits: int = 5,
        gap: int = 0
    ):
        super().__init__(n_splits=n_splits, shuffle=False, random_state=None)
        self.gap = gap
    
    def split(self, X: pd.DataFrame, y: Optional[pd.Series] = None, groups=None):
        """
        Generate indices to split data into training and test set.
        
        Parameters:
        -----------
        X : pd.DataFrame
            Training data, where n_samples is the number of samples
            and n_features is the number of features.
        y : pd.Series, optional
            Always ignored, exists for compatibility.
        groups : array-like, optional
            Always ignored, exists for compatibility.
            
        Yields:
        -------
        train : ndarray
            The training set indices for that split.
        test : ndarray
            The testing set indices for that split.
        """
        n_samples = len(X)
        indices = np.arange(n_samples)
        
        for train_indices, test_indices in super().split(X, y, groups):
            # Calculate the start and end of the test set
            test_start = test_indices[0]
            test_end = test_indices[-1] + 1
            
            # Calculate purge regions
            purge_start = max(0, test_start - self.gap)
            purge_end = min(n_samples, test_end + self.gap)
            
            # Create mask for training samples (exclude purge region)
            mask = np.ones(n_samples, dtype=bool)
            mask[purge_start:purge_end] = False
            
            # Apply mask to training indices
            train_indices = train_indices[mask[train_indices]]
            
            yield train_indices, test_indices


class CombinatorialPurgedKFold(PurgedKFold):
    """
    Combinatorial Purged K-fold cross-validation
    An extension of Purged K-fold that allows for multiple test sets per fold
    to increase the number of test samples while maintaining the purge gap.
    """
    
    def __init__(
        self,
        n_splits: int = 5,
        n_test_splits: int = 5,
        gap: int = 0
    ):
        super().__init__(n_splits=n_splits, gap=gap)
        self.n_test_splits = n_test_splits
    
    def split(self, X: pd.DataFrame, y: Optional[pd.Series] = None, groups=None):
        """
        Generate indices to split data into training and test set.
        
        Parameters:
        -----------
        X : pd.DataFrame
            Training data, where n_samples is the number of samples
            and n_features is the number of features.
        y : pd.Series, optional
            Always ignored, exists for compatibility.
        groups : array-like, optional
            Always ignored, exists for compatibility.
            
        Yields:
        -------
        train : ndarray
            The training set indices for that split.
        test : ndarray
            The testing set indices for that split.
        """
        n_samples = len(X)
        indices = np.arange(n_samples)
        
        # Calculate fold sizes
        fold_sizes = np.full(self.n_splits, n_samples // self.n_splits, dtype=int)
        fold_sizes[:n_samples % self.n_splits] += 1
        
        current = 0
        for fold_idx, fold_size in enumerate(fold_sizes):
            start, stop = current, current + fold_size
            
            # Calculate test set splits within this fold
            test_fold_size = fold_size // self.n_test_splits
            test_fold_sizes = np.full(self.n_test_splits, test_fold_size, dtype=int)
            test_fold_sizes[:fold_size % self.n_test_splits] += 1
            
            test_current = start
            for test_fold_idx, test_fold_size in enumerate(test_fold_sizes):
                t_start, t_stop = test_current, test_current + test_fold_size
                
                # Calculate purge regions
                purge_start = max(0, t_start - self.gap)
                purge_end = min(n_samples, t_stop + self.gap)
                
                # Create mask for training samples (exclude purge region)
                mask = np.ones(n_samples, dtype=bool)
                mask[purge_start:purge_end] = False
                
                # Get all indices not in purge region
                train_indices = indices[mask]
                
                # Get test indices
                test_indices = indices[t_start:t_stop]
                
                yield train_indices, test_indices
                
                test_current = t_stop
            
            current = stop


def walk_forward_split(
    X: pd.DataFrame,
    y: Optional[pd.Series] = None,
    window_size: int = 100,
    test_size: int = 20,
    gap: int = 5
) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    """
    Simple walk-forward split generator
    
    Parameters:
    -----------
    X : pd.DataFrame
        Training data
    y : pd.Series, optional
        Target variable
    window_size : int
        Size of training window
    test_size : int
        Size of test set
    gap : int
        Gap between training and test set
        
    Yields:
    -------
    train : ndarray
        Training set indices
    test : ndarray
        Test set indices
    """
    n_samples = len(X)
    
    for i in range(window_size, n_samples - test_size + 1, test_size):
        train_start = max(0, i - window_size)
        train_end = i - gap
        test_start = i
        test_end = i + test_size
        
        if train_end <= train_start or test_end > n_samples:
            break
            
        yield np.arange(train_start, train_end), np.arange(test_start, test_end)