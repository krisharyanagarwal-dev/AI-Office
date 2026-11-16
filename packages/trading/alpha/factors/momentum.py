"""
Momentum Factors
Trend-following and momentum-based alpha factors
"""
import pandas as pd
import numpy as np
from typing import List, Optional
from scipy import stats

from .base import FactorBase, FactorConfig


class MomentumFactor(FactorBase):
    """
    Multi-horizon momentum factor
    Computes returns over various lookbacks with optional skip period
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(
        self,
        lookbacks: List[int] = [5, 10, 20, 60, 120, 252],
        skip: int = 21,
        **params
    ):
        config = FactorConfig(
            name="Momentum",
            category="momentum",
            description="Multi-horizon price momentum with skip period",
            params={'lookbacks': lookbacks, 'skip': skip}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookbacks = self.params.get('lookbacks', [5, 10, 20, 60, 120, 252])
        skip = self.params.get('skip', 21)
        
        results = {}
        for lb in lookbacks:
            # Skip period to avoid microstructure noise
            momentum = prices.pct_change(lb + skip).shift(skip)
            results[f'mom_{lb}_{skip}'] = momentum.stack()
        
        return pd.concat(results, axis=1)


class RateOfChangeFactor(FactorBase):
    """
    Rate of Change (ROC) - percentage price change over N periods
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(self, periods: List[int] = [5, 10, 20, 60], **params):
        config = FactorConfig(
            name="ROC",
            category="momentum",
            description="Rate of Change - percentage price change",
            params={'periods': periods}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        periods = self.params.get('periods', [5, 10, 20, 60])
        
        results = {}
        for p in periods:
            roc = prices.pct_change(p)
            results[f'roc_{p}'] = roc.stack()
        
        return pd.concat(results, axis=1)


class RSIFactor(FactorBase):
    """
    Relative Strength Index (RSI) factor.

    Production-parity note: the formula is trading-bot's
    strategies/strategies.py:53-59, which divides gain by loss WITHOUT a
    zero-division guard. This method previously inserted
    ``loss.replace(0, np.nan)``, which turned a legitimate RSI of 100 into NaN
    and silently produced an EMPTY frame on any all-gain window -- exactly the
    strong-uptrend bars a RSI signal exists to catch. The unguarded arithmetic
    is correct and is now reproduced: loss == 0 gives 100, gain == loss == 0
    gives NaN.

    See alpha/factors/rsi.py for the multi-period factor and the named Wilder
    alternative, which is never the default.
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(self, periods: List[int] = [14, 21], **params):
        config = FactorConfig(
            name="RSI",
            category="momentum",
            description="Relative Strength Index",
            params={'periods': periods}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        periods = self.params.get('periods', [14, 21])
        
        results = {}
        delta = prices.diff()
        
        for p in periods:
            gain = delta.where(delta > 0, 0).rolling(p).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(p).mean()
            
            # No .replace(0, np.nan) here: see the class docstring. Production
            # does not guard this division, and adding a guard changes the
            # result on all-gain windows.
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            results[f'rsi_{p}'] = rsi.stack()
        
        return pd.concat(results, axis=1)


class MACDFactor(FactorBase):
    """
    MACD (Moving Average Convergence Divergence) factor
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        **params
    ):
        config = FactorConfig(
            name="MACD",
            category="momentum",
            description="MACD with signal line",
            params={'fast': fast, 'slow': slow, 'signal': signal}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        fast = self.params.get('fast', 12)
        slow = self.params.get('slow', 26)
        signal = self.params.get('signal', 9)
        
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        macd_hist = macd - macd_signal
        
        results = {
            'macd': macd.stack(),
            'macd_signal': macd_signal.stack(),
            'macd_hist': macd_hist.stack(),
        }
        
        return pd.concat(results, axis=1)


class StochasticFactor(FactorBase):
    """
    Stochastic Oscillator
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(
        self,
        k_period: int = 14,
        d_period: int = 3,
        slowing: int = 3,
        **params
    ):
        config = FactorConfig(
            name="Stochastic",
            category="momentum",
            description="Stochastic Oscillator %K and %D",
            params={'k_period': k_period, 'd_period': d_period, 'slowing': slowing}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        high: Optional[pd.DataFrame] = None,
        low: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # If high/low not provided, approximate from close
        if high is None or low is None:
            # Use close as approximation (less accurate)
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        k_period = self.params.get('k_period', 14)
        d_period = self.params.get('d_period', 3)
        slowing = self.params.get('slowing', 3)
        
        lowest_low = low.rolling(k_period).min()
        highest_high = high.rolling(k_period).max()
        
        # Fast %K
        fast_k = 100 * (prices - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
        
        # Slow %K (smoothed)
        slow_k = fast_k.rolling(slowing).mean()
        
        # %D
        slow_d = slow_k.rolling(d_period).mean()
        
        results = {
            'stoch_k': slow_k.stack(),
            'stoch_d': slow_d.stack(),
        }
        
        return pd.concat(results, axis=1)


class TrendStrengthFactor(FactorBase):
    """
    Trend Strength using linear regression slope
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(
        self,
        lookbacks: List[int] = [20, 60, 120],
        **params
    ):
        config = FactorConfig(
            name="TrendStrength",
            category="momentum",
            description="Linear regression slope as trend strength",
            params={'lookbacks': lookbacks}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookbacks = self.params.get('lookbacks', [20, 60, 120])
        
        results = {}
        for lb in lookbacks:
            def slope(x):
                if len(x) < 2:
                    return np.nan
                y = x.values
                x_vals = np.arange(len(y))
                return stats.linregress(x_vals, y)[0]
            
            trend = prices.rolling(lb).apply(slope, raw=True)
            # Normalize by price level
            trend_norm = trend / prices * 100
            results[f'trend_strength_{lb}'] = trend_norm.stack()
        
        return pd.concat(results, axis=1)


class AroonFactor(FactorBase):
    """
    Aroon Indicator - measures trend strength and direction
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(self, period: int = 25, **params):
        config = FactorConfig(
            name="Aroon",
            category="momentum",
            description="Aroon Up/Down trend indicator",
            params={'period': period}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        high: Optional[pd.DataFrame] = None,
        low: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        period = self.params.get('period', 25)
        
        if high is None:
            high = prices
        if low is None:
            low = prices
        
        # Aroon Up: periods since highest high
        high_ago = high.rolling(period).apply(
            lambda x: period - np.argmax(x) - 1, raw=True
        )
        aroon_up = 100 * (period - high_ago) / period
        
        # Aroon Down: periods since lowest low
        low_ago = low.rolling(period).apply(
            lambda x: period - np.argmin(x) - 1, raw=True
        )
        aroon_down = 100 * (period - low_ago) / period
        
        # Aroon Oscillator
        aroon_osc = aroon_up - aroon_down
        
        results = {
            'aroon_up': aroon_up.stack(),
            'aroon_down': aroon_down.stack(),
            'aroon_osc': aroon_osc.stack(),
        }
        
        return pd.concat(results, axis=1)


class MomentumDecayFactor(FactorBase):
    """
    Momentum Decay - how quickly momentum is fading
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(
        self,
        short_lb: int = 20,
        long_lb: int = 120,
        **params
    ):
        config = FactorConfig(
            name="MomentumDecay",
            category="momentum",
            description="Ratio of short-term to long-term momentum",
            params={'short_lb': short_lb, 'long_lb': long_lb}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        short_lb = self.params.get('short_lb', 20)
        long_lb = self.params.get('long_lb', 120)
        
        mom_short = prices.pct_change(short_lb)
        mom_long = prices.pct_change(long_lb)
        
        # Decay ratio: >1 means momentum accelerating, <1 means decaying
        decay = mom_short / mom_long.replace(0, np.nan)
        
        results = {
            'momentum_decay': decay.stack(),
            'mom_short': mom_short.stack(),
            'mom_long': mom_long.stack(),
        }
        
        return pd.concat(results, axis=1)


class MomentumQualityFactor(FactorBase):
    """
    Momentum Quality - consistency of momentum
    """
    
    @property
    def category(self) -> str:
        return "momentum"
    
    def __init__(
        self,
        lookback: int = 252,
        sub_periods: int = 12,
        **params
    ):
        config = FactorConfig(
            name="MomentumQuality",
            category="momentum",
            description="Consistency of momentum over sub-periods",
            params={'lookback': lookback, 'sub_periods': sub_periods}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookback = self.params.get('lookback', 252)
        sub_periods = self.params.get('sub_periods', 12)
        
        # Split lookback into sub-periods
        sub_lb = lookback // sub_periods
        
        # Calculate momentum for each sub-period
        sub_moments = []
        for i in range(sub_periods):
            start = i * sub_lb
            end = (i + 1) * sub_lb
            mom = prices.pct_change(end).shift(start) - prices.pct_change(start).shift(end)
            sub_moments.append(mom)
        
        # Quality = fraction of positive sub-periods
        moments_df = pd.concat(sub_moments, axis=1)
        quality = (moments_df > 0).mean(axis=1)
        
        # Also compute momentum consistency (correlation of sub-period returns)
        consistency = moments_df.T.corr().mean(axis=1)
        
        results = {
            'mom_quality': quality.stack(),
            'mom_consistency': consistency.stack(),
        }
        
        return pd.concat(results, axis=1)