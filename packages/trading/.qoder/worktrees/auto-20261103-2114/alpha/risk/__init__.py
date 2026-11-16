"""
Risk Management Module
Covariance estimation, risk budgeting, and tail risk management
"""
from .covariance import *
from .budgeting import *

__all__ = [
    # Covariance estimation
    'CovarianceEstimator',
    'SampleCovariance',
    'ExponentiallyWeightedCovariance',
    'ShrinkageCovariance',
    'LedoitWolfCovariance',
    'OracleApproximatingShrinkage',
    
    # Risk budgeting
    'RiskBudgeter',
    'EqualRiskBudgeter',
    'MaximumDiversificationBudgeter',
    'RiskParityBudgeter',
    'EqualWeightBudgeter',
    'VolatilityWeightedBudgeter',
    'MinimumVarianceBudgeter'
]