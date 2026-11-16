"""
Cross-sectional and Microstructure Factors
Ranking, neutralization, and market microstructure factors
"""
import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Any
from scipy import stats

from .base import FactorBase, FactorConfig


class CrossSectionalRankFactor(FactorBase):
    """
    Cross-sectional ranking (percentile ranking) of factors
    """
    
    @property
    def category(self) -> str:
        return "cross_sectional"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="CrossSectionalRank",
            category="cross_sectional",
            description="Cross-sectional percentile ranking",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        factor_data: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if factor_data is None:
            # If no factor data provided, use returns as default factor
            factor_data = prices.pct_change()
        
        # Cross-sectional rank (percentile) for each date
        ranked = factor_data.groupby(level=0).rank(pct=True) - 0.5
        return stacked_factor(ranked)


class CrossSectionalZScoreFactor(FactorBase):
    """
    Cross-sectional z-score normalization
    """
    
    @property
    def category(self) -> str:
        return "cross_sectional"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="CrossSectionalZScore",
            category="cross_sectional",
            description="Cross-sectional z-score normalization",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        factor_data: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if factor_data is None:
            factor_data = prices.pct_change()
        
        # Cross-sectional z-score for each date
        def zscore(x):
            return (x - x.mean()) / x.std().replace(0, np.nan)
        
        zscored = factor_data.groupby(level=0).apply(zscore)
        return stacked_factor(zscored)


class SectorNeutralizeFactor(FactorBase):
    """
    Sector neutralization factor
    """
    
    @property
    def category(self) -> str:
        return "cross_sectional"
    
    def __init__(
        self,
        sector_map: Optional[Dict[str, str]] = None,
        **params
    ):
        config = FactorConfig(
            name="SectorNeutralize",
            category="cross_sectional",
            description="Sector neutralization",
            params={'sector_map': sector_map or {}}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        factor_data: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if factor_data is None:
            factor_data = prices.pct_change()
        
        sector_map = self.params.get('sector_map', {})
        
        if not sector_map:
            # No sector map, so fall back to market neutralization: subtract the
            # per-date cross-sectional mean. This is the same operation, and the
            # same idiom, that FactorBase._neutralize ('market') and
            # MarketNeutralizeFactor.compute both use -- groupby(level=0).mean()
            # then sub(..., level=0).
            #
            # It is spelled out rather than delegated because `market_neutralize`
            # is not defined or imported anywhere in the repo; calling it raised
            # NameError for every caller that passed no sector map, which is a
            # legitimate configuration. Note the demean axis matters: mean(axis=1)
            # would demean across the factor columns instead, leaving each
            # date's cross-section summing to +/-1.5 rather than to zero.
            market_mean = factor_data.groupby(level=0).mean()
            neutralized = factor_data.sub(market_mean, axis=0, level=0)
            return stacked_factor(neutralized)
        
        # Group by sector and neutralize within each sector
        neutralized = factor_data.copy()
        
        # Reverse the sector map: ticker -> sector
        ticker_to_sector = {ticker: sector for sector, tickers in sector_map.items() 
                           for ticker in tickers}
        
        # Group by sector
        sectors = {}
        for ticker in factor_data.columns:
            sector = ticker_to_sector.get(ticker, 'UNKNOWN')
            if sector not in sectors:
                sectors[sector] = []
            sectors[sector].append(ticker)
        
        # Neutralize within each sector
        for sector, tickers in sectors.items():
            if tickers:
                sector_data = factor_data[tickers]
                sector_mean = sector_data.mean(axis=1)
                neutralized[tickers] = sector_data.sub(sector_mean, axis=0)
        
        return stacked_factor(neutralized)


class MarketNeutralizeFactor(FactorBase):
    """
    Market neutralization factor
    """
    
    @property
    def category(self) -> str:
        return "cross_sectional"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="MarketNeutralize",
            category="cross_sectional",
            description="Market neutralization (subtract cross-sectional mean)",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        factor_data: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if factor_data is None:
            factor_data = prices.pct_change()
        
        # Market neutral: subtract cross-sectional mean for each date
        market_mean = factor_data.groupby(level=0).mean()
        neutralized = factor_data.sub(market_mean, axis=0, level=0)
        return stacked_factor(neutralized)


def stacked_factor(data: pd.DataFrame) -> pd.DataFrame:
    """Helper function to stack factor data and return as single column DataFrame"""
    if isinstance(data.index, pd.MultiIndex):
        # Already stacked
        return data.stack().to_frame(data.columns[0] if len(data.columns) == 1 else 'factor')
    else:
        # Need to stack
        stacked = data.stack()
        # If multiple columns, we need to handle this
        if isinstance(stacked, pd.DataFrame):
            return stacked
        else:
            return stacked.to_frame('factor')


class VPINFactor(FactorBase):
    """
    Volume-synchronized Probability of Informed Trading (VPIN)
    Approximation using volume-synchronized sampling
    """
    
    @property
    def category(self) -> str:
        return "microstructure"
    
    def __init__(
        self,
        bucket_volume: Optional[float] = None,
        n_buckets: int = 50,
        lookback: int = 50,
        **params
    ):
        config = FactorConfig(
            name="VPIN",
            category="microstructure",
            description="Volume-synchronized PIN (approximation)",
            params={'bucket_volume': bucket_volume, 'n_buckets': n_buckets, 'lookback': lookback}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            # If we don't have volume data, return neutral signal
            return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('vpin')
        
        lookback = self.params.get('lookback', 50)
        n_buckets = self.params.get('n_buckets', 50)
        bucket_volume = self.params.get('bucket_volume')
        
        results = {}
        
        # For each asset, calculate VPIN approximation
        vpin_scores = {}
        
        for ticker in prices.columns:
            # Get data for this ticker
            price_series = prices[ticker].dropna()
            volume_series = volumes[ticker].reindex(price_series.index).fillna(0)
            
            if len(price_series) < lookback:
                vpin_scores[ticker] = 0
                continue
            
            # Take lookback window
            window_price = price_series.iloc[-lookback:]
            window_volume = volume_series.iloc[-lookback:]
            
            if bucket_volume is None:
                # Calculate average volume per bucket
                avg_volume = window_volume.mean()
                bucket_volume = avg_volume / n_buckets
            
            # Initialize variables
            cumulative_volume = 0
            bucket_imbalances = []
            current_bucket_buy = 0
            current_bucket_sell = 0
            
            # Process each bar
            for i in range(len(window_price)):
                price = window_price.iloc[i]
                volume = window_volume.iloc[i]
                
                # Determine buy/sell volume based on price change
                if i == 0:
                    price_change = 0
                else:
                    price_change = price - window_price.iloc[i-1]
                
                if price_change > 0:
                    # Up tick - consider as buy volume
                    current_bucket_buy += volume
                elif price_change < 0:
                    # Down tick - consider as sell volume
                    current_bucket_sell += volume
                # For zero price change, could use tick rule or ignore
                
                cumulative_volume += volume
                
                # Check if we've filled a bucket
                if cumulative_volume >= bucket_volume:
                    # Calculate imbalance for this bucket
                    total_volume_bucket = current_bucket_buy + current_bucket_sell
                    if total_volume_bucket > 0:
                        imbalance = (current_bucket_buy - current_bucket_sell) / total_volume_bucket
                    else:
                        imbalance = 0
                    bucket_imbalances.append(imbalance)
                    
                    # Reset counters
                    cumulative_volume = 0
                    current_bucket_buy = 0
                    current_bucket_sell = 0
            
            # Calculate VPIN as average absolute imbalance
            if bucket_imbalances:
                vpin = np.mean(np.abs(bucket_imbalances))
                vpin_scores[ticker] = vpin
            else:
                vpin_scores[ticker] = 0
        
        if vpin_scores:
            result = pd.Series(vpin_scores)
            return result.to_frame('vpin')
        else:
            return pd.DataFrame()


class OrderFlowToxicityFactor(FactorBase):
    """
    Order flow toxicity (VPIN-like measures)
    """
    
    @property
    def category(self) -> str:
        return "microstructure"
    
    def __init__(
        self,
        lookback: int = 20,
        **params
    ):
        config = FactorConfig(
            name="OrderFlowToxicity",
            category="microstructure",
            description="Order flow toxicity measures",
            params={'lookback': lookback}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('toxicity')
        
        lookback = self.params.get('lookback', 20)
        
        results = {}
        
        # Calculate volume-synchronized probability of informed trading approximation
        # Using price change direction as proxy for trade direction
        price_change = prices.diff()
        
        # Buy/sell volume approximation
        buy_volume = volumes.where(price_change > 0, 0)
        sell_volume = volumes.where(price_change < 0, 0)
        
        # Rolling sums
        buy_sum = buy_volume.rolling(lookback).sum()
        sell_sum = sell_volume.rolling(lookback).sum()
        total_volume = buy_sum + sell_sum
        
        # Volume imbalance
        volume_imbalance = (buy_sum - sell_sum) / total_volume.replace(0, np.nan)
        
        # Toxicity = E[|imbalance|] over lookback period
        toxicity = volume_imbalance.abs().rolling(lookback).mean()
        
        results['toxicity'] = toxicity.stack()
        
        # Also include raw imbalance
        results['volume_imbalance'] = volume_imbalance.stack()
        
        return pd.concat(results, axis=1)


class LiquidityFactor(FactorBase):
    """
    Liquidity factors (spread, depth, resilience)
    """
    
    @property
    def category(self) -> str:
        return "microstructure"
    
    def __init__(
        self,
        lookback: int = 20,
        **params
    ):
        config = FactorConfig(
            name="Liquidity",
            category="microstructure",
            description="Liquidity factors",
            params={'lookback': lookback}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        bid: Optional[pd.DataFrame] = None,
        ask: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # If we don't have bid/ask data, approximate from OHLC
        if bid is None or ask is None:
            # Approximate spread from high-low
            if high := kwargs.get('high'):
                if low := kwargs.get('low'):
                    # Use high-low as proxy for spread
                    spread_proxy = (high - low) / prices.replace(0, np.nan)
                else:
                    spread_proxy = pd.DataFrame(0, index=prices.index, columns=prices.columns)
            else:
                spread_proxy = pd.DataFrame(0, index=prices.index, columns=prices.columns)
        else:
            # Actual bid-ask spread
            spread_proxy = (ask - bid) / ((ask + bid) / 2).replace(0, np.nan)
        
        lookback = self.params.get('lookback', 20)
        
        results = {}
        
        # Spread
        results['spread'] = spread_proxy.stack()
        
        # Spread change
        spread_change = spread_proxy.diff()
        results['spread_change'] = stack_series(spread_change)
        
        # Spread volatility
        spread_vol = spread_proxy.rolling(lookback).std()
        results['spread_vol'] = stack_series(spread_vol)
        
        # Liquidity ratio (inverse of spread)
        liquidity = 1 / spread_proxy.replace(0, np.nan)
        results['liquidity'] = stack_series(liquidity)
        
        # Liquidity change
        liquidity_change = liquidity.diff()
        results['liquidity_change'] = stack_series(liquidity_change)
        
        return pd.concat(results, axis=1) if results else pd.DataFrame()


def stack_series(series: pd.Series) -> pd.DataFrame:
    """Helper function to convert Series to DataFrame with single column"""
    if isinstance(series, pd.Series):
        return series.to_frame(series.name if series.name else 'factor')
    return series