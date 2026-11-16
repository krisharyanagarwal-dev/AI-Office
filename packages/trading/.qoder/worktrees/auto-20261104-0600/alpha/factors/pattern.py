"""
Pattern Factors
Candlestick patterns, chart patterns, and support/resistance levels
"""
import pandas as pd
import numpy as np
from typing import List, Optional, Tuple, Dict, Any
from scipy.signal import argrelextrema

from .base import FactorBase, FactorConfig


class CandlestickPatternFactor(FactorBase):
    """
    Candlestick pattern recognition
    """
    
    @property
    def category(self) -> str:
        return "pattern"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="CandlestickPattern",
            category="pattern",
            description="Japanese candlestick patterns",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        high: Optional[pd.DataFrame] = None,
        low: Optional[pd.DataFrame] = None,
        open_prices: Optional[pd.DataFrame] = None,
        close_prices: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # Use provided OHLC or approximate from prices
        if open_prices is None:
            open_prices = prices
        if close_prices is None:
            close_prices = prices
        if high is None:
            high = prices
        if low is None:
            low = prices
        
        results = {}
        
        # Doji - small body relative to range
        body_size = np.abs(close_prices - open_prices)
        full_range = high - low
        doji_condition = body_size <= (0.1 * full_range)
        results['doji'] = doji_condition.astype(float).stack()
        
        # Hammer / Hanging Man - small body, long lower shadow
        lower_shadow = np.minimum(open_prices, close_prices) - low
        upper_shadow = high - np.maximum(open_prices, close_prices)
        body = np.abs(close_prices - open_prices)
        hammer_condition = (lower_shadow > 2 * body) & (upper_shadow < 0.5 * body)
        results['hammer'] = hammer_condition.astype(float).stack()
        
        # Shooting Star / Inverted Hammer - small body, long upper shadow
        shooting_star_condition = (upper_shadow > 2 * body) & (lower_shadow < 0.5 * body)
        results['shooting_star'] = shooting_star_condition.astype(float).stack()
        
        # Engulfing Patterns
        prev_open = open_prices.shift(1)
        prev_close = close_prices.shift(1)
        
        # Bullish Engulfing: previous red candle, current green candle that engulfs previous
        bullish_engulfing = (
            (prev_close < prev_open) &  # Previous candle red
            (close_prices > open_prices) &  # Current candle green
            (open_prices <= prev_close) &  # Current open <= previous close
            (close_prices >= prev_open)   # Current close >= previous open
        )
        results['bullish_engulfing'] = bullish_engulfing.astype(float).stack()
        
        # Bearish Engulfing: previous green candle, current red candle that engulfs previous
        bearish_engulfing = (
            (prev_close > prev_open) &  # Previous candle green
            (close_prices < open_prices) &  # Current candle red
            (open_prices >= prev_close) &  # Current open >= previous close
            (close_prices <= prev_open)   # Current close <= previous open
        )
        results['bearish_engulfing'] = bearish_engulfing.astype(float).stack()
        
        # Morning Star (3-candle pattern)
        # First: long red candle
        # Second: small body (gap down)
        # Third: long green candle that closes above midpoint of first
        first_body = np.abs(prev_close.shift(1) - open_prices.shift(1))
        second_body = np.abs(close_prices - open_prices)
        third_body = np.abs(close_prices.shift(-1) - open_prices.shift(-1))
        
        morning_star = (
            (prev_close.shift(1) < open_prices.shift(1)) &  # First candle red
            (second_body < 0.3 * first_body.shift(1)) &  # Second candle small body
            (close_prices.shift(-1) > open_prices.shift(-1)) &  # Third candle green
            (close_prices.shift(-1) > (open_prices.shift(1) + close_prices.shift(1)) / 2)  # Third closes above midpoint of first
        )
        results['morning_star'] = morning_star.astype(float).stack()
        
        # Evening Star (opposite of morning star)
        evening_star = (
            (prev_close.shift(1) > open_prices.shift(1)) &  # First candle green
            (second_body < 0.3 * first_body.shift(1)) &  # Second candle small body
            (close_prices.shift(-1) < open_prices.shift(-1)) &  # Third candle red
            (close_prices.shift(-1) < (open_prices.shift(1) + close_prices.shift(1)) / 2)  # Third closes below midpoint of first
        )
        results['evening_star'] = evening_star.astype(float).stack()
        
        return pd.concat(results, axis=1)


class ChartPatternFactor(FactorBase):
    """
    Chart pattern recognition (triangles, flags, head and shoulders, etc.)
    """
    
    @property
    def category(self) -> str:
        return "pattern"
    
    def __init__(
        self,
        lookback: int = 50,
        min_points: int = 5,
        **params
    ):
        config = FactorConfig(
            name="ChartPattern",
            category="pattern",
            description="Chart patterns (triangles, flags, wedges, H&S)",
            params={'lookback': lookback, 'min_points': min_points}
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
            high = prices
            low = prices
        
        lookback = self.params.get('lookback', 50)
        min_points = self.params.get('min_points', 5)
        
        results = {}
        
        # For each asset, detect patterns in the lookback window
        patterns_dict = {}
        
        for ticker in prices.columns:
            # Get price series for this ticker
            price_series = prices[ticker].dropna()
            high_series = high[ticker].reindex(price_series.index).fillna(method='ffill')
            low_series = low[ticker].reindex(price_series.index).fillna(method='ffill')
            
            if len(price_series) < lookback:
                # Not enough data
                patterns_dict[ticker] = pd.Series(0, index=price_series.index)
                continue
            
            # Take lookback window
            window_high = high_series.iloc[-lookback:]
            window_low = low_series.iloc[-lookback:]
            window_price = price_series.iloc[-lookback:]
            
            # Find local extrema (peaks and troughs)
            try:
                # Find peaks (local maxima)
                peaks, _ = argrelextrema(window_high.values, np.greater_equal, order=5)
                # Find troughs (local minima)
                troughs, _ = argrelextrema(window_low.values, np.less_equal, order=5)
                
                # Combine and sort
                extrema_indices = np.sort(np.concatenate([peaks, troughs]))
                extrema_values = []
                extrema_types = []  # 'peak' or 'trough'
                
                for idx in extrema_indices:
                    if idx in peaks and idx in troughs:
                        # Both peak and trough - unlikely but handle
                        extrema_values.append(window_high.iloc[idx])
                        extrema_types.append('both')
                    elif idx in peaks:
                        extrema_values.append(window_high.iloc[idx])
                        extrema_types.append('peak')
                    else:  # in troughs
                        extrema_values.append(window_low.iloc[idx])
                        extrema_types.append('trough')
                
                if len(extrema_indices) >= min_points:
                    # Analyze pattern based on extrema sequence
                    pattern_signal = self._analyze_pattern_sequence(
                        extrema_indices, extrema_values, extrema_types, window_price.index
                    )
                else:
                    pattern_signal = 0
                    
                # Create series with same index as prices, zero everywhere except current point
                pattern_series = pd.Series(0, index=prices.index)
                if len(price_series) > 0:
                    pattern_series.iloc[-1] = pattern_signal
                patterns_dict[ticker] = pattern_series
                
            except Exception:
                # If pattern detection fails, default to 0
                patterns_dict[ticker] = pd.Series(0, index=prices.index)
        
        if patterns_dict:
            result = pd.DataFrame(patterns_dict)
            return result.stack().to_frame('chart_pattern')
        else:
            return pd.DataFrame()
    
    def _analyze_pattern_sequence(
        self,
        indices: np.ndarray,
        values: List[float],
        types: List[str],
        index: pd.DatetimeIndex
    ) -> float:
        """Analyze sequence of extrema to detect chart patterns"""
        if len(indices) < 3:
            return 0
        
        # Normalize values to 0-1 scale for comparison
        norm_values = (np.array(values) - np.min(values)) / (np.max(values) - np.min(values) + 1e-10)
        
        # Convert to deviations from mean
        mean_val = np.mean(norm_values)
        deviations = norm_values - mean_val
        
        # Simple pattern detection based on sequence of peaks/troughs
        # This is a simplified version - real implementation would be more sophisticated
        
        # Look for alternating peaks and troughs (trend)
        alternations = 0
        for i in range(1, len(types)):
            if types[i] != types[i-1]:
                alternations += 1
        
        # High alternation = ranging/choppy market
        # Low alternation = trending market
        if len(types) > 2:
            alternation_ratio = alternations / (len(types) - 1)
            
            # Map to signal: negative for ranging (expect reversal), positive for trending (expect continuation)
            if alternation_ratio > 0.7:
                # Ranging market - look for reversal signals
                # Check if we're at extremes
                if len(deviations) >= 3:
                    recent_dev = deviations[-3:]  # Last 3 points
                    if np.all(recent_dev > 0.5):  # Recently at highs
                        return -0.5  # Expect reversal down
                    elif np.all(recent_dev < -0.5):  # Recently at lows
                        return 0.5   # Expect reversal up
            else:
                # Trending market - look for continuation
                if len(deviations) >= 3:
                    recent_dev = deviations[-3:]
                    if np.all(recent_dev > 0):  # Recently making higher highs/lows
                        return 0.3  # Expect continuation up
                    elif np.all(recent_dev < 0):  # Recently making lower highs/lows
                        return -0.3  # Expect continuation down
        
        return 0


class SupportResistanceFactor(FactorBase):
    """
    Support and resistance levels
    """
    
    @property
    def category(self) -> str:
        return "pattern"
    
    def __init__(
        self,
        lookback: int = 100,
        min_touches: int = 2,
        proximity_pct: float = 0.02,
        **params
    ):
        config = FactorConfig(
            name="SupportResistance",
            category="pattern",
            description="Dynamic support and resistance levels",
            params={'lookback': lookback, 'min_touches': min_touches, 'proximity_pct': proximity_pct}
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
            high = prices
            low = prices
        
        lookback = self.params.get('lookback', 100)
        min_touches = self.params.get('min_touches', 2)
        proximity_pct = self.params.get('proximity_pct', 0.02)
        
        results = {}
        
        # For each asset, calculate support/resistance distance
        sr_scores = {}
        
        for ticker in prices.columns:
            # Get price series for this ticker
            price_series = prices[ticker].dropna()
            high_series = high[ticker].reindex(price_series.index).fillna(method='ffill')
            low_series = low[ticker].reindex(price_series.index).fillna(method='ffill')
            
            if len(price_series) < lookback:
                sr_scores[ticker] = 0
                continue
            
            # Take lookback window
            window_high = high_series.iloc[-lookback:]
            window_low = low_series.iloc[-lookback:]
            window_close = price_series.iloc[-lookback:]
            current_price = price_series.iloc[-1] if len(price_series) > 0 else np.nan
            
            if np.isnan(current_price):
                sr_scores[ticker] = 0
                continue
            
            # Find significant levels (price levels touched multiple times)
            # Use high and low prices as potential S/R levels
            all_levels = pd.concat([window_high, window_low])
            
            # Cluster nearby levels
            levels = []
            counts = []
            
            for level in all_levels:
                if np.isnan(level):
                    continue
                # Check if this level is close to any existing level
                found = False
                for i, existing_level in enumerate(levels):
                    if abs(level - existing_level) / existing_level < proximity_pct:
                        levels[i] = (levels[i] * counts[i] + level) / (counts[i] + 1)
                        counts[i] += 1
                        found = True
                        break
                if not found:
                    levels.append(level)
                    counts.append(1)
            
            # Filter levels with enough touches
            significant_levels = [
                level for level, count in zip(levels, counts) 
                if count >= min_touches
            ]
            
            if not significant_levels:
                sr_scores[ticker] = 0
                continue
            
            # Calculate distance to nearest support/resistance
            # Support = levels below current price
            # Resistance = levels above current price
            supports = [level for level in significant_levels if level < current_price]
            resistances = [level for level in significant_levels if level > current_price]
            
            # Distance to nearest support/resistance (as % of price)
            if supports:
                nearest_support = max(supports)
                dist_to_support = (current_price - nearest_support) / current_price
            else:
                dist_to_support = np.inf
                
            if resistances:
                nearest_resistance = min(resistances)
                dist_to_resistance = (nearest_resistance - current_price) / current_price
            else:
                dist_to_resistance = np.inf
            
            # Signal: negative when near resistance (expect reversal down)
            #         positive when near support (expect reversal up)
            #         zero when far from both
            min_dist = min(dist_to_support, dist_to_resistance)
            
            if min_dist == np.inf:
                sr_scores[ticker] = 0
            elif dist_to_support < dist_to_resistance:
                # Closer to support - bullish signal
                sr_scores[ticker] = min(1.0, dist_to_support / proximity_pct)  # Closer = stronger signal
            else:
                # Closer to resistance - bearish signal
                sr_scores[ticker] = -min(1.0, dist_to_resistance / proximity_pct)  # Closer = stronger signal
        
        if sr_scores:
            result = pd.Series(sr_scores)
            return result.to_frame('support_resistance')
        else:
            return pd.DataFrame()


class PivotPointsFactor(FactorBase):
    """
    Pivot points (standard, Fibonacci, Woodie, Camarilla)
    """
    
    @property
    def category(self) -> str:
        return "pattern"
    
    def __init__(
        self,
        method: str = "standard",
        **params
    ):
        config = FactorConfig(
            name="PivotPoints",
            category="pattern",
            description="Pivot points and support/resistance levels",
            params={'method': method}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        high: Optional[pd.DataFrame] = None,
        low: Optional[pd.DataFrame] = None,
        open_prices: Optional[pd.DataFrame] = None,
        close_prices: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # Use provided OHLC or approximate from prices
        if open_prices is None:
            open_prices = prices
        if close_prices is None:
            close_prices = prices
        if high is None:
            high = prices
        if low is None:
            low = prices
        
        method = self.params.get('method', 'standard')
        
        # Calculate pivot point
        pivot = (high + low + close_prices) / 3
        
        results = {}
        
        if method == "standard":
            # Standard pivot points
            r1 = 2 * pivot - low
            s1 = 2 * pivot - high
            r2 = pivot + (high - low)
            s2 = pivot - (high - low)
            r3 = high + 2 * (pivot - low)
            s3 = low - 2 * (high - pivot)
            
            results = {
                'pivot': pivot.stack(),
                'r1': r1.stack(),
                's1': s1.stack(),
                'r2': r2.stack(),
                's2': s2.stack(),
                'r3': r3.stack(),
                's3': s3.stack(),
            }
            
            # Distance to nearest pivot level
            levels = pd.concat([pivot, r1, s1, r2, s2, r3, s3], axis=1)
            # For each asset, find closest level
            distances = []
            for ticker in prices.columns:
                if ticker in levels.columns:
                    asset_levels = levels[ticker].dropna()
                    if len(asset_levels) > 0:
                        current_price = prices[ticker].iloc[-1] if len(prices[ticker]) > 0 else np.nan
                        if not np.isnan(current_price):
                            distances.append(np.min(np.abs(asset_levels - current_price)) / current_price)
                        else:
                            distances.append(0)
                    else:
                        distances.append(0)
                else:
                    distances.append(0)
            
            results['pivot_distance'] = pd.Series(distances, index=prices.columns).stack()
            
        elif method == "fibonacci":
            # Fibonacci pivot points
            r1 = pivot + 0.382 * (high - low)
            s1 = pivot - 0.382 * (high - low)
            r2 = pivot + 0.618 * (high - low)
            s2 = pivot - 0.618 * (high - low)
            r3 = pivot + 1.000 * (high - low)
            s3 = pivot - 1.000 * (high - low)
            
            results = {
                'pivot': pivot.stack(),
                'r1': r1.stack(),
                's1': s1.stack(),
                'r2': r2.stack(),
                's2': s2.stack(),
                'r3': r3.stack(),
                's3': s3.stack(),
            }
            
        elif method == "woodie":
            # Woodie pivot points
            pivot = (high + low + 2 * open_prices) / 4
            r1 = 2 * pivot - low
            s1 = 2 * pivot - high
            r2 = pivot + (high - low)
            s2 = pivot - (high - low)
            
            results = {
                'pivot': pivot.stack(),
                'r1': r1.stack(),
                's1': s1.stack(),
                'r2': r2.stack(),
                's2': s2.stack(),
            }
            
        elif method == "camarilla":
            # Camarilla pivot points
            range_ = high - low
            r1 = close_prices + range_ * 1.1 / 12
            r2 = close_prices + range_ * 1.1 / 6
            r3 = close_prices + range_ * 1.1 / 4
            r4 = close_prices + range_ * 1.1 / 2
            s1 = close_prices - range_ * 1.1 / 12
            s2 = close_prices - range_ * 1.1 / 6
            s3 = close_prices - range_ * 1.1 / 4
            s4 = close_prices - range_ * 1.1 / 2
            
            results = {
                'pivot': close_prices.stack(),  # Camarilla uses close as pivot
                'r1': r1.stack(),
                'r2': r2.stack(),
                'r3': r3.stack(),
                'r4': r4.stack(),
                's1': s1.stack(),
                's2': s2.stack(),
                's3': s3.stack(),
                's4': s4.stack(),
            }
        
        # Add distance to nearest level for all methods
        if results:
            # Exclude pivot_distance if already added
            distance_key = [k for k in results.keys() if 'distance' in k.lower() and 'pivot' in k.lower()]
            if not distance_key:
                levels_df = pd.DataFrame(results)
                # For each asset, calculate min distance to any level
                min_distances = []
                for ticker in prices.columns:
                    if ticker in levels_df.columns:
                        asset_levels = levels_df[ticker].dropna()
                        if len(asset_levels) > 0:
                            current_price = prices[ticker].iloc[-1] if len(prices[ticker]) > 0 else np.nan
                            if not np.isnan(current_price) and len(asset_levels) > 0:
                                min_dist = np.min(np.abs(asset_levels - current_price)) / current_price
                                min_distances.append(min_dist)
                            else:
                                min_distances.append(0)
                        else:
                            min_distances.append(0)
                    else:
                        min_distances.append(0)
                
                results['pivot_distance'] = pd.Series(min_distances, index=prices.columns).stack()
        
        return pd.concat(results, axis=1) if results else pd.DataFrame()


class VolumeProfileFactor(FactorBase):
    """
    Volume Profile - volume traded at each price level
    """
    
    @property
    def category(self) -> str:
        return "pattern"
    
    def __init__(
        self,
        lookback: int = 100,
        num_bins: int = 50,
        **params
    ):
        config = FactorConfig(
            name="VolumeProfile",
            category="pattern",
            description="Volume Profile (VPOC, VAH, VAL)",
            params={'lookback': lookback, 'num_bins': num_bins}
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
            raise ValueError("VolumeProfileFactor requires volume data")
        
        if high is None or low is None:
            # Approximate from close
            high = prices
            low = prices
        
        lookback = self.params.get('lookback', 100)
        num_bins = self.params.get('num_bins', 50)
        
        results = {}
        
        # For each asset, calculate volume profile
        vp_scores = {}
        
        for ticker in prices.columns:
            # Get data for this ticker
            price_series = prices[ticker].dropna()
            volume_series = volumes[ticker].reindex(price_series.index).fillna(0)
            high_series = high[ticker].reindex(price_series.index).fillna(method='ffill')
            low_series = low[ticker].reindex(price_series.index).fillna(method='ffill')
            
            if len(price_series) < lookback:
                vp_scores[ticker] = 0
                continue
            
            # Take lookback window
            window_high = high_series.iloc[-lookback:]
            window_low = low_series.iloc[-lookback:]
            window_price = price_series.iloc[-lookback:]
            window_volume = volume_series.iloc[-lookback:]
            current_price = price_series.iloc[-1] if len(price_series) > 0 else np.nan
            
            if np.isnan(current_price):
                vp_scores[ticker] = 0
                continue
            
            # Create price bins
            price_min = window_low.min()
            price_max = window_high.max()
            
            if price_max <= price_min:
                vp_scores[ticker] = 0
                continue
            
            bin_edges = np.linspace(price_min, price_max, num_bins + 1)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
            
            # Initialize volume profile
            volume_profile = np.zeros(num_bins)
            
            # Assign each bar's volume to appropriate price bin
            # Use typical price for each bar
            typical_price = (window_high + window_low + window_price) / 3
            
            for i in range(len(typical_price)):
                price = typical_price.iloc[i]
                volume = volume_series.iloc[i]
                
                # Find bin index
                bin_idx = np.searchsorted(bin_edges, price, side='right') - 1
                if 0 <= bin_idx < num_bins:
                    volume_profile[bin_idx] += volume
            
            # Find VPOC (Volume Point of Control) - bin with highest volume
            if np.sum(volume_profile) > 0:
                vpoc_idx = np.argmax(volume_profile)
                vpoc_price = bin_centers[vpoc_idx]
                
                # Calculate Value Area (70% of volume)
                sorted_indices = np.argsort(volume_profile)[::-1]  # Descending order
                cumulative_volume = np.cumsum(volume_profile[sorted_indices])
                total_volume = np.sum(volume_profile)
                
                # Find value area (first bins that sum to >= 70% of volume)
                value_area_threshold = 0.7 * total_volume
                va_indices = []
                cum_vol = 0
                for idx in sorted_indices:
                    cum_vol += volume_profile[idx]
                    va_indices.append(idx)
                    if cum_vol >= value_area_threshold:
                        break
                
                if va_indices:
                    vah_price = bin_centers[max(va_indices)]  # Value Area High
                    val_price = bin_centers[min(va_indices)]  # Value Area Low
                    
                    # Calculate distance to value area
                    if current_price < val_price:
                        # Below value area - bullish
                        dist_to_val = (val_price - current_price) / current_price
                        vp_scores[ticker] = min(1.0, dist_to_val / 0.05)  # Closer = stronger signal
                    elif current_price > vah:
                        # Above value area - bearish
                        dist_to_vah = (current_price - vah) / current_price
                        vp_scores[ticker] = -min(1.0, dist_to_vah / 0.05)  # Closer = stronger signal
                    else:
                        # Inside value area - neutral
                        vp_scores[ticker] = 0
                else:
                    vp_scores[ticker] = 0
            else:
                vp_scores[ticker] = 0
        
        if vp_scores:
            result = pd.Series(vp_scores)
            return result.to_frame('volume_profile')
        else:
            return pd.DataFrame()