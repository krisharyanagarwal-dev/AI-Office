"""
Trading Brain Module
Contains the three brains that make up the decision-making core:
- Chart Brain: maintains market state and detects patterns/regimes
- Decision Brain: makes trading decisions based on market state
- Learning Brain: learns from trade outcomes and adapts the system
"""

from .chart_brain import ChartBrain
from .decision_brain import DecisionBrain
from .learning_brain import LearningBrain
from .state_store import StateStore
from .trading_bot import TradingBot

__all__ = [
    # Brains
    'ChartBrain',
    'DecisionBrain', 
    'LearningBrain',
    'StateStore',
    'TradingBot',
]
