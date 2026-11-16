"""
Reversal Factors
Mean reversion and contrarian alpha factors
"""
import pandas as pd
import numpy as np
from typing import List, Optional

from .base import FactorBase, FactorConfig


class ShortTermReversalFactor(FactorBase):
    """
    Short-term reversal (1-21 days)
    Stocks that dropped recently tend to bounce
    """
    
    @property
    def category(self) -> str:
        return "reversal"
    
    def __init__(
        self,
        lookbacks: List[int] = [1, 2, 3, 5, 10, 21],
        **params
    ):
        config = FactorConfig(
            name="ShortTermReversal",
            category="reversal",
            description="Short-term mean reversion over 1-21 days",
            params={'lookbacks': lookbacks}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookbacks = self.params.get('lookbacks', [1, 2, 3, 5, 10, 21])
        
        results = {}
        for lb in lookbacks:
            # Negative return = oversold = positive signal
            reversal = -prices.pct_change(lb)
            results[f'rev_{lb}d'] = reversal.stack()
        
        return pd.concat(results, axis=1)


class MediumTermReversalFactor(FactorBase):
    """
    Medium-term reversal (1-3 months)
    """
    
    @property
    def category(self) -> str:
        return "reversal"
    
    def __init__(
        self,
        lookbacks: List[int] = [21, 42, 63],
        skip: int = 5,
        **params
    ):
        config = FactorConfig(
            name="MediumTermReversal",
            category="reversal",
            description="Medium-term mean reversion (1-3 months)",
            params={'lookbacks': lookbacks, 'skip': skip}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookbacks = self.params.get('lookbacks', [21, 42, 63])
        skip = self.params.get('skip', 5)
        
        results = {}
        for lb in lookbacks:
            # Skip recent period to avoid momentum contamination
            reversal = -prices.pct_change(lb + skip).shift(skip)
            results[f'rev_{lb}d_skip{skip}'] = reversal.stack()
        
        return pd.concat(results, axis=1)


class LongTermReversalFactor(FactorBase):
    """
    Long-term reversal (3-5 years)
    Based on De Bondt & Thaler (1985)
    """
    
    @property
    def category(self) -> str:
        return "reversal"
    
    def __init__(
        self,
        formation_period: int = 252 * 3,  # 3 years
        holding_period: int = 252,  # 1 year
        **params
    ):
        config = FactorConfig(
            name="LongTermReversal",
            category="reversal",
            description="Long-term reversal (3-5 year formation)",
            params={'formation_period': formation_period, 'holding_period': holding_period}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        formation = self.params.get('formation_period', 252 * 3)
        holding = self.params.get('holding_period', 252)
        
        # Formation period return
        formation_ret = prices.pct_change(formation).shift(holding)
        
        # Negative formation return = oversold = positive signal
        reversal = -formation_ret
        
        results = {
            'long_reversal': reversal.stack(),
        }
        
        return pd.concat(results, axis=1)


class OverboughtOversoldFactor(FactorBase):
    """
    Overbought/Oversold using Bollinger Bands position
    """
    
    @property
    def category(self) -> str:
        return "reversal"
    
    def __init__(
        self,
        period: int = 20,
        std_dev: float = 2.0,
        **params
    ):
        config = FactorConfig(
            name="OverboughtOversold",
            category="reversal",
            description="Bollinger Band position for mean reversion",
            params={'period': period, 'std_dev': std_dev}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        period = self.params.get('period', 20)
        std_dev = self.params.get('std_dev', 2.0)
        
        # Bollinger Bands
        ma = prices.rolling(period).mean()
        std = prices.rolling(period).std()
        
        upper = ma + std_dev * std
        lower = ma - std_dev * std
        
        # Position within bands: -1 = lower, 0 = middle, 1 = upper
        bb_pos = (prices - ma) / (std_dev * std).replace(0, np.nan)
        
        # Reversal signal: negative when overbought, positive when oversold
        reversal_signal = -bb_pos
        
        # Distance from bands (normalized)
        dist_from_upper = (upper - prices) / (upper - lower).replace(0, np.nan)
        dist_from_lower = (prices - lower) / (upper - lower).replace(0, np.nan)
        
        results = {
            'bb_position': bb_pos.stack(),
            'reversal_signal': reversal_signal.stack(),
            'dist_from_upper': dist_from_upper.stack(),
            'dist_from_lower': dist_from_lower.stack(),
        }
        
        return pd.concat(results, axis=1)


class RSReversalFactor(FactorBase):
    """
    RSI-based reversal (extreme RSI levels)
    """
    
    @property
    def category(self) -> str:
        return "reversal"
    
    def __init__(
        self,
        period: int = 14,
        overbought: float = 70,
        oversold: float = 30,
        **params
    ):
        config = FactorConfig(
            name="RSReversal",
            category="reversal",
            description="RSI extreme levels reversal",
            params={'period': period, 'overbought': overbought, 'oversold': oversold}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        period = self.params.get('period', 14)
        overbought = self.params.get('overbought', 70)
        oversold = self.params.get('oversold', 30)
        
        # Calculate RSI
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        # Reversal signal
        # Overbought (>70) -> negative signal
        # Oversold (<30) -> positive signal
        # Linear interpolation between 30-70
        signal = pd.DataFrame(0, index=prices.index, columns=prices.columns)
        
        signal[rsi > overbought] = -(rsi - overbought) / (100 - overbought)
        signal[rsi < oversold] = (oversold - rsi) / oversold
        
        # Normalize to -1 to 1
        signal = signal.clip(-1, 1)
        
        results = {
            'rsi': rsi.stack(),
            'rsi_reversal': signal.stack(),
        }
        
        return pd.concat(results, axis=1)


class VolumeReversalFactor(FactorBase):
    """
    Volume-weighted reversal
    High volume reversals are more significant
    """
    
    @property
    def category(self) -> str:
        return "reversal"
    
    def __init__(
        self,
        lookback: int = 20,
        volume_lookback: int = 20,
        **params
    ):
        config = FactorConfig(
            name="VolumeReversal",
            category="reversal",
            description="Volume-weighted short-term reversal",
            params={'lookback': lookback, 'volume_lookback': volume_lookback}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            raise ValueError("VolumeReversal requires volume data")
        
        lookback = self.params.get('lookback', 20)
        vol_lb = self.params.get('volume_lookback', 20)
        
        # Price reversal
        price_rev = -prices.pct_change(lookback)
        
        # Volume confirmation
        avg_volume = volumes.rolling(vol_lb).mean()
        volume_ratio = volumes / avg_volume.replace(0, np.nan)
        
        # Weight reversal by volume ratio
        vol_weighted_rev = price_rev * np.log1p(volume_ratio)
        
        results = {
            'vol_reversal': vol_weighted_rev.stack(),
            'price_reversal': price_rev.stack(),
            'volume_ratio': volume_ratio.stack(),
        }
        
        return pd.concat(results, axis=1)


class IntradayReversalFactor(FactorBase):
    """
    Intraday reversal (requires intraday data)
    """
    
    @property
    def category(self) -> str:
        return "reversal"
    
    def __init__(
        self,
        morning_cutoff: str = "11:00",
        **params
    ):
        config = FactorConfig(
            name="IntradayReversal",
            category="reversal",
            description="Morning reversal pattern",
            params={'morning_cutoff': morning_cutoff}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        open_prices: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        """
        Compute intraday reversal:
        - Morning return (open to cutoff)
        - Afternoon reversal signal
        """
        if open_prices is None:
            # Can't compute without open prices
            return pd.DataFrame()
        
        cutoff = self.params.get('morning_cutoff', '11:00')
        
        # Morning return
        morning_ret = (prices - open_prices) / open_prices.replace(0, np.nan)
        
        # Reversal: negative morning -> positive afternoon expected
        reversal_signal = -morning_ret
        
        results = {
            'intraday_reversal': reversal_signal.stack(),
            'morning_return': morning_ret.stack(),
        }
        
        return pd.concat(results, axis=1)


class GapReversalFactor(FactorBase):
    """
    Overnight gap reversal
    Gaps tend to fill
    """
    
    @property
    def category(self) -> str:
        return "reversal"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="GapReversal",
            category="reversal",
            description="Overnight gap fill tendency",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        open_prices: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if open_prices is None:
            return pd.DataFrame()
        
        # Overnight gap
        prev_close = prices.shift(1)
        gap = (open_prices - prev_close) / prev_close.replace(0, np.nan)
        
        # Gap fill signal: gap up -> expect down, gap down -> expect up
        fill_signal = -gap
        
        # Gap size
        gap_size = gap.abs()
        
        results = {
            'gap': gap.stack(),
            'gap_fill_signal': fill_signal.stack(),
            'gap_size': gap_size.stack(),
        }
        
        return pd.concat(results, axis=1)