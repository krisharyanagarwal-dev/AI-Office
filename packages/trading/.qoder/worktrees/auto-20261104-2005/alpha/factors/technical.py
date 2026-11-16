"""
Technical Indicators
Classic technical analysis factors for momentum and trend
"""
import pandas as pd
import numpy as np
from typing import List, Optional
from scipy import stats

from .base import FactorBase, FactorConfig


class BollingerFactor(FactorBase):
    """
    Bollinger Bands - volatility bands placed above/below moving average
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 20,
        std_dev: float = 2.0,
        **params
    ):
        config = FactorConfig(
            name="Bollinger",
            category="technical",
            description="Bollinger Bands position and width",
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
        
        # Moving average
        ma = prices.rolling(period).mean()
        
        # Standard deviation
        std = prices.rolling(period).std()
        
        # Upper and lower bands
        upper = ma + (std_dev * std)
        lower = ma - (std_dev * std)
        
        # Band width
        width = (upper - lower) / ma.replace(0, np.nan)
        
        # Position within bands (%B)
        # 0 = at lower band, 0.5 = middle, 1 = at upper band
        percent_b = (prices - lower) / (upper - lower).replace(0, np.nan)
        
        results = {
            'bb_upper': upper.stack(),
            'bb_middle': ma.stack(),
            'bb_lower': lower.stack(),
            'bb_width': width.stack(),
            'bb_percent_b': percent_b.stack(),
        }
        
        return pd.concat(results, axis=1)


class KeltnerFactor(FactorBase):
    """
    Keltner Channel - volatility-based envelopes set above/below EMA
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 20,
        atr_period: int = 10,
        multiplier: float = 2.0,
        **params
    ):
        config = FactorConfig(
            name="Keltner",
            category="technical",
            description="Keltner Channel (EMA with ATR bands)",
            params={'period': period, 'atr_period': atr_period, 'multiplier': multiplier}
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        period = self.params.get('period', 20)
        atr_period = self.params.get('atr_period', 10)
        multiplier = self.params.get('multiplier', 2.0)
        
        # EMA
        ema = prices.ewm(span=period, adjust=False).mean()
        
        # True Range
        tr1 = high - low
        tr2 = np.abs(high - prices.shift(1))
        tr3 = np.abs(low - prices.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(atr_period).mean()
        
        # Keltner Channels
        upper = ema + (multiplier * atr)
        lower = ema - (multiplier * atr)
        
        # Channel width
        width = (upper - lower) / ema.replace(0, np.nan)
        
        # Position within channels
        percent_k = (prices - lower) / (upper - lower).replace(0, np.nan)
        
        results = {
            'kel_upper': upper.stack(),
            'kel_middle': ema.stack(),
            'kel_lower': lower.stack(),
            'kel_width': width.stack(),
            'kel_percent_k': percent_k.stack(),
        }
        
        return pd.concat(results, axis=1)


class ATRFactor(FactorBase):
    """
    Average True Range - volatility measure
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 14,
        **params
    ):
        config = FactorConfig(
            name="ATR",
            category="technical",
            description="Average True Range volatility measure",
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        period = self.params.get('period', 14)
        
        # True Range
        tr1 = high - low
        tr2 = np.abs(high - prices.shift(1))
        tr3 = np.abs(low - prices.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # ATR
        atr = tr.rolling(period).mean()
        
        # Normalized ATR (as percentage of price)
        atr_pct = atr / prices.replace(0, np.nan)
        
        results = {
            'atr': atr.stack(),
            'atr_pct': atr_pct.stack(),
        }
        
        return pd.concat(results, axis=1)


class ADXFactor(FactorBase):
    """
    Average Directional Index - trend strength indicator
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 14,
        **params
    ):
        config = FactorConfig(
            name="ADX",
            category="technical",
            description="Average Directional Index trend strength",
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        period = self.params.get('period', 14)
        
        # True Range
        tr1 = high - low
        tr2 = np.abs(high - prices.shift(1))
        tr3 = np.abs(low - prices.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        plus_dm = pd.Series(plus_dm, index=prices.index)
        minus_dm = pd.Series(minus_dm, index=prices.index)
        
        # Smoothed values
        tr_smooth = tr.rolling(period).mean()
        plus_dm_smooth = plus_dm.rolling(period).mean()
        minus_dm_smooth = minus_dm.rolling(period).mean()
        
        # Directional Indicators
        plus_di = 100 * (plus_dm_smooth / tr_smooth.replace(0, np.nan))
        minus_di = 100 * (minus_dm_smooth / tr_smooth.replace(0, np.nan))
        
        # Directional Index
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
        
        # ADX
        adx = dx.rolling(period).mean()
        
        results = {
            'adx': adx.stack(),
            'plus_di': plus_di.stack(),
            'minus_di': minus_di.stack(),
        }
        
        return pd.concat(results, axis=1)


class CCIFactor(FactorBase):
    """
    Commodity Channel Index - identifies cyclical trends
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 20,
        constant: float = 0.015,
        **params
    ):
        config = FactorConfig(
            name="CCI",
            category="technical",
            description="Commodity Channel Index",
            params={'period': period, 'constant': constant}
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        period = self.params.get('period', 20)
        constant = self.params.get('constant', 0.015)
        
        # Typical Price
        tp = (high + low + prices) / 3
        
        # Moving Average of TP
        tp_ma = tp.rolling(period).mean()
        
        # Mean Deviation
        md = tp.rolling(period).apply(
            lambda x: np.mean(np.abs(x - x.mean())), raw=True
        )
        
        # CCI
        cci = (tp - tp_ma) / (constant * md).replace(0, np.nan)
        
        results = {
            'cci': cci.stack(),
        }
        
        return pd.concat(results, axis=1)


class WilliamsRFactor(FactorBase):
    """
    Williams %R - momentum oscillator
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 14,
        **params
    ):
        config = FactorConfig(
            name="WilliamsR",
            category="technical",
            description="Williams %R momentum oscillator",
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        period = self.params.get('period', 14)
        
        # Highest High and Lowest Low over period
        highest_high = high.rolling(period).max()
        lowest_low = low.rolling(period).min()
        
        # Williams %R
        willr = -100 * (highest_high - prices) / (highest_high - lowest_low).replace(0, np.nan)
        
        results = {
            'williams_r': willr.stack(),
        }
        
        return pd.concat(results, axis=1)


class IchimokuFactor(FactorBase):
    """
    Ichimoku Cloud - comprehensive indicator
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_period: int = 52,
        chikou_period: int = 26,
        **params
    ):
        config = FactorConfig(
            name="Ichimoku",
            category="technical",
            description="Ichimoku Cloud indicator",
            params={
                'tenkan_period': tenkan_period,
                'kijun_period': kijun_period,
                'senkou_period': senkou_period,
                'chikou_period': chikou_period
            }
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        tenkan = self.params.get('tenkan_period', 9)
        kijun = self.params.get('kijun_period', 26)
        senkou = self.params.get('senkou_period', 52)
        chikou = self.params.get('chikou_period', 26)
        
        # Tenkan-sen (Conversion Line): (period high + period low)/2
        period1_high = high.rolling(tenkan).max()
        period1_low = low.rolling(tenkan).min()
        tenkan_sen = (period1_high + period1_low) / 2
        
        # Kijun-sen (Base Line): (period high + period low)/2
        period2_high = high.rolling(kijun).max()
        period2_low = low.rolling(kijun).min()
        kijun_sen = (period2_high + period2_low) / 2
        
        # Senkou Span A (Leading Span A): (Tenkan + Kijun)/2
        senkou_span_a = (tenkan_sen + kijun_sen) / 2
        
        # Senkou Span B (Leading Span B): (period high + period low)/2
        period3_high = high.rolling(senkou).max()
        period3_low = low.rolling(senkou).min()
        senkou_span_b = (period3_high + period3_low) / 2
        
        # Chikou Span (Lagging Span): Close plotted chikou periods behind
        chikou_span = prices.shift(-chikou)
        
        results = {
            'ichimoku_tenkan': tenkan_sen.stack(),
            'ichimoku_kijun': kijun_sen.stack(),
            'ichimoku_senkou_a': senkou_span_a.stack(),
            'ichimoku_senkou_b': senkou_span_b.stack(),
            'ichimoku_chikou': chikou_span.stack(),
        }
        
        return pd.concat(results, axis=1)


class SuperTrendFactor(FactorBase):
    """
    SuperTrend - trend following indicator based on ATR
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 10,
        multiplier: float = 3.0,
        **params
    ):
        config = FactorConfig(
            name="SuperTrend",
            category="technical",
            description="SuperTrend trend following indicator",
            params={'period': period, 'multiplier': multiplier}
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        period = self.params.get('period', 10)
        multiplier = self.params.get('multiplier', 3.0)
        
        # True Range
        tr1 = high - low
        tr2 = np.abs(high - prices.shift(1))
        tr3 = np.abs(low - prices.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # ATR
        atr = tr.rolling(period).mean()
        
        # Upper and Lower Basic Bands
        upper_basic = (high + low) / 2 + (multiplier * atr)
        lower_basic = (high + low) / 2 - (multiplier * atr)
        
        # Final Upper Band
        upper_band = upper_basic.copy()
        lower_band = lower_basic.copy()
        
        for i in range(1, len(prices)):
            if upper_basic.iloc[i] < upper_band.iloc[i-1] or prices.iloc[i-1] > upper_band.iloc[i-1]:
                upper_band.iloc[i] = upper_basic.iloc[i]
            else:
                upper_band.iloc[i] = upper_band.iloc[i-1]
                
            if lower_basic.iloc[i] > lower_band.iloc[i-1] or prices.iloc[i-1] < lower_band.iloc[i-1]:
                lower_band.iloc[i] = lower_basic.iloc[i]
            else:
                lower_band.iloc[i] = lower_band.iloc[i-1]
        
        # SuperTrend
        supertrend = pd.Series(index=prices.index, dtype=float)
        direction = pd.Series(index=prices.index, dtype=int)  # 1 for up, -1 for down
        
        for i in range(len(prices)):
            if i == 0:
                supertrend.iloc[i] = upper_basic.iloc[i]
                direction.iloc[i] = 1
            else:
                if supertrend.iloc[i-1] == upper_band.iloc[i-1]:
                    if prices.iloc[i] <= upper_band.iloc[i]:
                        supertrend.iloc[i] = upper_basic.iloc[i]
                        direction.iloc[i] = 1
                    else:
                        supertrend.iloc[i] = lower_basic.iloc[i]
                        direction.iloc[i] = -1
                else:
                    if prices.iloc[i] >= lower_band.iloc[i]:
                        supertrend.iloc[i] = lower_basic.iloc[i]
                        direction.iloc[i] = -1
                    else:
                        supertrend.iloc[i] = upper_basic.iloc[i]
                        direction.iloc[i] = 1
        
        # SuperTrend direction (1 = uptrend, -1 = downtrend)
        # Distance to SuperTrend
        distance_to_st = (prices - supertrend) / prices.replace(0, np.nan)
        
        results = {
            'supertrend': supertrend.stack(),
            'supertrend_direction': direction.stack(),
            'distance_to_supertrend': distance_to_st.stack(),
        }
        
        return pd.concat(results, axis=1)


class ParabolicSARFactor(FactorBase):
    """
    Parabolic SAR - trend following stop and reverse system
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        start: float = 0.02,
        increment: float = 0.02,
        maximum: float = 0.2,
        **params
    ):
        config = FactorConfig(
            name="ParabolicSAR",
            category="technical",
            description="Parabolic SAR stop and reverse system",
            params={'start': start, 'increment': increment, 'maximum': maximum}
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        start = self.params.get('start', 0.02)
        increment = self.params.get('increment', 0.02)
        maximum = self.params.get('maximum', 0.2)
        
        # Initialize
        length = len(prices)
        sar = pd.Series(index=prices.index, dtype=float)
        trend = pd.Series(index=prices.index, dtype=int)  # 1 for up, -1 for down
        af = pd.Series(index=prices.index, dtype=float)  # acceleration factor
        ep = pd.Series(index=prices.index, dtype=float)  # extreme point
        
        # Initialize first values
        sar.iloc[0] = low.iloc[0]
        trend.iloc[0] = 1
        af.iloc[0] = start
        ep.iloc[0] = high.iloc[0]
        
        # Calculate SAR
        for i in range(1, length):
            if trend.iloc[i-1] == 1:  # Uptrend
                sar.iloc[i] = sar.iloc[i-1] + af.iloc[i-1] * (ep.iloc[i-1] - sar.iloc[i-1])
                
                # Reverse if price < SAR
                if low.iloc[i] < sar.iloc[i]:
                    trend.iloc[i] = -1
                    sar.iloc[i] = ep.iloc[i-1]
                    af.iloc[i] = start
                    ep.iloc[i] = low.iloc[i]
                else:
                    trend.iloc[i] = 1
                    if high.iloc[i] > ep.iloc[i-1]:
                        ep.iloc[i] = high.iloc[i]
                        af.iloc[i] = min(af.iloc[i-1] + increment, maximum)
                    else:
                        ep.iloc[i] = ep.iloc[i-1]
                        af.iloc[i] = min(af.iloc[i-1] + increment, maximum)
            else:  # Downtrend
                sar.iloc[i] = sar.iloc[i-1] - af.iloc[i-1] * (sar.iloc[i-1] - ep.iloc[i-1])
                
                # Reverse if price > SAR
                if high.iloc[i] > sar.iloc[i]:
                    trend.iloc[i] = 1
                    sar.iloc[i] = ep.iloc[i-1]
                    af.iloc[i] = start
                    ep.iloc[i] = high.iloc[i]
                else:
                    trend.iloc[i] = -1
                    if low.iloc[i] < ep.iloc[i-1]:
                        ep.iloc[i] = low.iloc[i]
                        af.iloc[i] = min(af.iloc[i-1] + increment, maximum)
                    else:
                        ep.iloc[i] = ep.iloc[i-1]
                        af.iloc[i] = min(af.iloc[i-1] + increment, maximum)
        
        # Distance to SAR
        distance_to_sar = (prices - sar) / prices.replace(0, np.nan)
        
        results = {
            'parabolic_sar': sar.stack(),
            'psar_trend': trend.stack(),
            'psar_acceleration': af.stack(),
            'psar_extreme_point': ep.stack(),
            'distance_to_psar': distance_to_sar.stack(),
        }
        
        return pd.concat(results, axis=1)


class DonchianChannelFactor(FactorBase):
    """
    Donchian Channel - highest high and lowest low over N periods
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 20,
        **params
    ):
        config = FactorConfig(
            name="DonchianChannel",
            category="technical",
            description="Donchian Channel (highest high/lowest low)",
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        period = self.params.get('period', 20)
        
        # Upper band: highest high
        upper = high.rolling(period).max()
        
        # Lower band: lowest low
        lower = low.rolling(period).min()
        
        # Middle band: average of upper and lower
        middle = (upper + lower) / 2
        
        # Channel width
        width = (upper - lower) / prices.replace(0, np.nan)
        
        # Position within channel
        position = (prices - lower) / (upper - lower).replace(0, np.nan)
        
        results = {
            'donchian_upper': upper.stack(),
            'donchian_middle': middle.stack(),
            'donchian_lower': lower.stack(),
            'donchian_width': width.stack(),
            'donchian_position': position.stack(),
        }
        
        return pd.concat(results, axis=1)


class AroonFactor(FactorBase):
    """
    Aroon Indicator - measures trend strength and direction
    """
    
    @property
    def category(self) -> str:
        return "technical"
    
    def __init__(
        self,
        period: int = 25,
        **params
    ):
        config = FactorConfig(
            name="Aroon",
            category="technical",
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
        if high is None or low is None:
            # Approximate from close
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        period = self.params.get('period', 25)
        
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