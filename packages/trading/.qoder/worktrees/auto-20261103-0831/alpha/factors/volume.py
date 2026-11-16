"""
Volume Factors
Volume-based alpha factors
"""
import pandas as pd
import numpy as np
from typing import List, Optional

from .base import FactorBase, FactorConfig


class VolumeFactor(FactorBase):
    """
    Volume-based factors
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(
        self,
        lookbacks: List[int] = [5, 10, 20, 60],
        **params
    ):
        config = FactorConfig(
            name="Volume",
            category="volume",
            description="Volume and volume trend factors",
            params={'lookbacks': lookbacks}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            raise ValueError("VolumeFactor requires volume data")
        
        lookbacks = self.params.get('lookbacks', [5, 10, 20, 60])
        
        results = {}
        for lb in lookbacks:
            # Volume moving average
            vol_ma = volumes.rolling(lb).mean()
            
            # Volume ratio (current vs average)
            vol_ratio = volumes / vol_ma.replace(0, np.nan)
            
            # Volume trend
            vol_trend = volumes.rolling(lb).apply(
                lambda x: np.polyfit(np.arange(len(x)), x, 1)[0] if len(x) == lb else np.nan,
                raw=True
            )
            
            results[f'vol_ma_{lb}'] = vol_ma.stack()
            results[f'vol_ratio_{lb}'] = vol_ratio.stack()
            results[f'vol_trend_{lb}'] = vol_trend.stack()
        
        return pd.concat(results, axis=1)


class VWAPFactor(FactorBase):
    """
    Volume Weighted Average Price (VWAP) factors
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(
        self,
        lookbacks: List[int] = [20, 50, 200],
        **params
    ):
        config = FactorConfig(
            name="VWAP",
            category="volume",
            description="Volume Weighted Average Price distance",
            params={'lookbacks': lookbacks}
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
        if volumes is None:
            raise ValueError("VWAPFactor requires volume data")
        
        lookbacks = self.params.get('lookbacks', [20, 50, 200])
        
        # Typical price if OHLC available, else use close
        if high is not None and low is not None:
            typical_price = (high + low + prices) / 3
        else:
            typical_price = prices
        
        results = {}
        for lb in lookbacks:
            # VWAP = sum(typical_price * volume) / sum(volume)
            vwap_num = (typical_price * volumes).rolling(lb).sum()
            vwap_den = volumes.rolling(lb).sum()
            vwap = vwap_num / vwap_den.replace(0, np.nan)
            
            # Distance from VWAP
            dist = (prices - vwap) / vwap.replace(0, np.nan)
            
            results[f'vwap_{lb}'] = vwap.stack()
            results[f'vwap_dist_{lb}'] = dist.stack()
        
        return pd.concat(results, axis=1)


class VolumeTrendFactor(FactorBase):
    """
    Volume trend and momentum
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(
        self,
        lookbacks: List[int] = [5, 10, 20],
        **params
    ):
        config = FactorConfig(
            name="VolumeTrend",
            category="volume",
            description="Volume trend and momentum",
            params={'lookbacks': lookbacks}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            raise ValueError("VolumeTrendFactor requires volume data")
        
        lookbacks = self.params.get('lookbacks', [5, 10, 20])
        
        results = {}
        for lb in lookbacks:
            # Volume momentum (rate of change)
            vol_roc = volumes.pct_change(lb)
            
            # Volume acceleration
            vol_accel = vol_roc.diff()
            
            # Volume relative to recent average
            vol_rel = volumes / volumes.rolling(lb).mean().replace(0, np.nan)
            
            results[f'vol_roc_{lb}'] = vol_roc.stack()
            results[f'vol_accel_{lb}'] = vol_accel.stack()
            results[f'vol_rel_{lb}'] = vol_rel.stack()
        
        return pd.concat(results, axis=1)


class DollarVolumeFactor(FactorBase):
    """
    Dollar Volume (Price * Volume) factors
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(
        self,
        lookbacks: List[int] = [20, 60],
        **params
    ):
        config = FactorConfig(
            name="DollarVolume",
            category="volume",
            description="Dollar volume and liquidity factors",
            params={'lookbacks': lookbacks}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            raise ValueError("DollarVolumeFactor requires volume data")
        
        lookbacks = self.params.get('lookbacks', [20, 60])
        
        # Dollar volume
        dollar_vol = prices * volumes
        
        results = {}
        for lb in lookbacks:
            # Average dollar volume
            avg_dollar_vol = dollar_vol.rolling(lb).mean()
            
            # Dollar volume trend
            dv_trend = dollar_vol.rolling(lb).apply(
                lambda x: np.polyfit(np.arange(len(x)), x, 1)[0] if len(x) == lb else np.nan,
                raw=True
            )
            
            # Relative dollar volume
            rel_dv = dollar_vol / avg_dollar_vol.replace(0, np.nan)
            
            results[f'dollar_vol_{lb}'] = dollar_vol.stack()
            results[f'avg_dollar_vol_{lb}'] = avg_dollar_vol.stack()
            results[f'dv_trend_{lb}'] = dv_trend.stack()
            results[f'rel_dv_{lb}'] = rel_dv.stack()
        
        return pd.concat(results, axis=1)


class OBVFactor(FactorBase):
    """
    On-Balance Volume (OBV)
    Cumulative volume adding on up days, subtracting on down days
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="OBV",
            category="volume",
            description="On-Balance Volume",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            raise ValueError("OBVFactor requires volume data")
        
        # Price direction
        price_change = prices.diff()
        direction = np.sign(price_change)
        direction = direction.fillna(0)
        
        # OBV
        obv = (volumes * direction).cumsum()
        
        # OBV moving averages
        obv_ma20 = obv.rolling(20).mean()
        obv_ma50 = obv.rolling(50).mean()
        
        # OBV signal
        obv_signal = obv - obv_ma20
        
        results = {
            'obv': obv.stack(),
            'obv_ma20': obv_ma20.stack(),
            'obv_ma50': obv_ma50.stack(),
            'obv_signal': obv_signal.stack(),
        }
        
        return pd.concat(results, axis=1)


class MFI(FactorBase):
    """
    Money Flow Index (MFI)
    Volume-weighted RSI
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(
        self,
        period: int = 14,
        **params
    ):
        config = FactorConfig(
            name="MFI",
            category="volume",
            description="Money Flow Index - volume-weighted RSI",
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
        if volumes is None:
            raise ValueError("MFI requires volume data")
        
        period = self.params.get('period', 14)
        
        # Typical price
        if high is not None and low is not None:
            typical_price = (high + low + prices) / 3
        else:
            typical_price = prices
        
        # Money flow
        money_flow = typical_price * volumes
        
        # Positive and negative money flow
        tp_change = typical_price.diff()
        pos_flow = money_flow.where(tp_change > 0, 0).rolling(period).sum()
        neg_flow = money_flow.where(tp_change < 0, 0).rolling(period).sum()
        
        # Money ratio
        mf_ratio = pos_flow / neg_flow.replace(0, np.nan)
        
        # MFI
        mfi = 100 - (100 / (1 + mf_ratio))
        
        results = {
            'mfi': mfi.stack(),
            'pos_money_flow': pos_flow.stack(),
            'neg_money_flow': neg_flow.stack(),
        }
        
        return pd.concat(results, axis=1)


class VPIN(FactorBase):
    """
    Volume-synchronized Probability of Informed Trading (VPIN)
    Approximation using volume buckets
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(
        self,
        bucket_volume: Optional[float] = None,
        n_buckets: int = 50,
        **params
    ):
        config = FactorConfig(
            name="VPIN",
            category="volume",
            description="Volume-synchronized PIN (approximation)",
            params={'bucket_volume': bucket_volume, 'n_buckets': n_buckets}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        """
        Simplified VPIN approximation:
        - Uses volume imbalance over rolling window
        - Not true VPIN but captures similar concept
        """
        if volumes is None:
            raise ValueError("VPIN requires volume data")
        
        n_buckets = self.params.get('n_buckets', 50)
        
        # Buy/sell volume approximation using price change
        price_change = prices.diff()
        buy_vol = volumes.where(price_change > 0, 0)
        sell_vol = volumes.where(price_change < 0, 0)
        
        # Rolling sums
        buy_sum = buy_vol.rolling(n_buckets).sum()
        sell_sum = sell_vol.rolling(n_buckets).sum()
        total_sum = buy_sum + sell_sum
        
        # Volume imbalance
        imbalance = (buy_sum - sell_sum) / total_sum.replace(0, np.nan)
        
        # VPIN = E[|imbalance|]
        vpin = imbalance.abs().rolling(n_buckets).mean()
        
        results = {
            'vpin': vpin.stack(),
            'buy_vol': buy_sum.stack(),
            'sell_vol': sell_sum.stack(),
            'vol_imbalance': imbalance.stack(),
        }
        
        return pd.concat(results, axis=1)


class VolumeOscillator(FactorBase):
    """
    Volume Oscillator
    Difference between short and long volume MAs
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(
        self,
        short: int = 5,
        long: int = 20,
        **params
    ):
        config = FactorConfig(
            name="VolumeOscillator",
            category="volume",
            description="Volume oscillator (short vs long MA)",
            params={'short': short, 'long': long}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            raise ValueError("VolumeOscillator requires volume data")
        
        short = self.params.get('short', 5)
        long = self.params.get('long', 20)
        
        vol_short = volumes.rolling(short).mean()
        vol_long = volumes.rolling(long).mean()
        
        # Volume oscillator
        vol_osc = (vol_short - vol_long) / vol_long.replace(0, np.nan)
        
        results = {
            'vol_osc': vol_osc.stack(),
            'vol_short_ma': vol_short.stack(),
            'vol_long_ma': vol_long.stack(),
        }
        
        return pd.concat(results, axis=1)


class AccumulationDistributionFactor(FactorBase):
    """
    Accumulation/Distribution Line
    Volume-weighted price flow
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="AccumulationDistribution",
            category="volume",
            description="Accumulation/Distribution line",
            params={}
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
        if volumes is None or high is None or low is None:
            raise ValueError("AccumulationDistribution requires volume, high, low")
        
        # Money Flow Multiplier
        mfm = ((prices - low) - (high - prices)) / (high - low).replace(0, np.nan)
        mfm = mfm.clip(-1, 1)
        
        # Money Flow Volume
        mfv = mfm * volumes
        
        # Accumulation/Distribution Line
        ad_line = mfv.cumsum()
        
        # AD moving averages
        ad_ma20 = ad_line.rolling(20).mean()
        ad_ma50 = ad_line.rolling(50).mean()
        
        results = {
            'ad_line': ad_line.stack(),
            'ad_ma20': ad_ma20.stack(),
            'ad_ma50': ad_ma50.stack(),
            'ad_signal': (ad_line - ad_ma20).stack(),
        }
        
        return pd.concat(results, axis=1)


class ChaikinMoneyFlowFactor(FactorBase):
    """
    Chaikin Money Flow (CMF)
    Volume-weighted average of accumulation/distribution
    """
    
    @property
    def category(self) -> str:
        return "volume"
    
    def __init__(
        self,
        period: int = 20,
        **params
    ):
        config = FactorConfig(
            name="ChaikinMoneyFlow",
            category="volume",
            description="Chaikin Money Flow",
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
        if volumes is None or high is None or low is None:
            raise ValueError("ChaikinMoneyFlow requires volume, high, low")
        
        period = self.params.get('period', 20)
        
        # Money Flow Multiplier
        mfm = ((prices - low) - (high - prices)) / (high - low).replace(0, np.nan)
        mfm = mfm.clip(-1, 1)
        
        # Money Flow Volume
        mfv = mfm * volumes
        
        # CMF = Sum(MFV) / Sum(Volume) over period
        cmf = mfv.rolling(period).sum() / volumes.rolling(period).sum().replace(0, np.nan)
        
        results = {
            'cmf': cmf.stack(),
            'mfv_sum': mfv.rolling(period).sum().stack(),
            'vol_sum': volumes.rolling(period).sum().stack(),
        }
        
        return pd.concat(results, axis=1)