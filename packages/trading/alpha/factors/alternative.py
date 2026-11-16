"""
Alternative Data Factors
Funding rates, open interest, fear/greed, whale alerts, exchange flows, macro data
"""
import pandas as pd
import numpy as np
from typing import List, Optional
import requests
from datetime import datetime, timedelta

from .base import FactorBase, FactorConfig


class FundingRateFactor(FactorBase):
    """
    Funding rate basis (perpetual futures funding rate vs spot)
    """
    
    @property
    def category(self) -> str:
        return "alternative"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="FundingRate",
            category="alternative",
            description="Perpetual futures funding rate basis",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # This would normally fetch real-time funding rates from exchanges
        # For now, we'll simulate or use placeholder data
        # In practice, this would be fetched via API calls to Binance, Bybit, etc.
        
        # Placeholder implementation - in real system, this would call external APIs
        # For now, return zeros or use price-based approximation
        
        # Simple approximation: use basis between futures and spot if we had both
        # Since we typically only have spot, we'll return neutral signal
        # Real implementation would:
        # 1. Fetch current funding rates from exchanges
        # 2. Calculate basis = futures_price - spot_price
        # 3. Annualize funding rate
        # 4. Signal = -basis (negative basis = backwardation = bullish for spot)
        
        # Return neutral signal for now
        return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('funding_rate')


class OpenInterestFactor(FactorBase):
    """
    Open interest changes and OI-weighted price
    """
    
    @property
    def category(self) -> str:
        return "alternative"
    
    def __init__(
        self,
        lookback: int = 20,
        **params
    ):
        config = FactorConfig(
            name="OpenInterest",
            category="alternative",
            description="Open interest changes and accumulation/distribution",
            params={'lookback': lookback}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        open_interest: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if open_interest is None:
            # If we don't have OI data, return neutral signal
            return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('open_interest')
        
        lookback = self.params.get('lookback', 20)
        
        results = {}
        
        # OI change
        oi_change = open_interest.pct_change(lookback)
        results['oi_change'] = oi_change.stack()
        
        # OI-weighted price (if we had volume-price data)
        # For now, just OI change
        
        # OI trend
        oi_ma = open_interest.rolling(lookback).mean()
        oi_trend = (open_interest - oi_ma) / oi_ma.replace(0, np.nan)
        results['oi_trend'] = oi_trend.stack()
        
        # OI acceleration
        oi_accel = oi_change.diff()
        results['oi_accel'] = oi_accel.stack()
        
        return pd.concat(results, axis=1)


class FearGreedFactor(FactorBase):
    """
    Fear & Greed Index as contrarian indicator
    """
    
    @property
    def category(self) -> str:
        return "alternative"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="FearGreed",
            category="alternative",
            description="Fear & Greed Index contrarian signal",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # This would fetch the actual Fear & Greed Index from API
        # For now, return neutral signal
        # Real implementation would:
        # 1. Fetch F&G index from alternative.me API
        # 2. Convert to signal (extreme fear = bullish, extreme greed = bearish)
        # 3. Apply to all crypto assets (or specific ones)
        
        # Return neutral signal for now
        return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('fear_greed')


class WhaleAlertFactor(FactorBase):
    """
    Whale alert signals - large transactions
    """
    
    @property
    def category(self) -> str:
        return "alternative"
    
    def __init__(
        self,
        lookback: int = 24,  # hours
        min_value_usd: float = 1000000,  # $1M
        **params
    ):
        config = FactorConfig(
            name="WhaleAlert",
            category="alternative",
            description="Whale alert signals for large transactions",
            params={'lookback': lookback, 'min_value_usd': min_value_usd}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # This would fetch whale alert data from API
        # For now, return neutral signal
        # Real implementation would:
        # 1. Fetch recent large transactions from whale alert API
        # 2. Group by asset and time window
        # 3. Calculate net buy/sell pressure
        # 4. Signal = net buy volume / average volume
        
        # Return neutral signal for now
        return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('whale_alert')


class ExchangeFlowFactor(FactorBase):
    """
    Exchange net flows (inflows/outflows from exchanges)
    """
    
    @property
    def category(self) -> str:
        return "alternative"
    
    def __init__(
        self,
        lookback: int = 24,  # hours
        **params
    ):
        config = FactorConfig(
            name="ExchangeFlow",
            category="alternative",
            description="Exchange net flows (inflow/outflow)",
            params={'lookback': lookback}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # This would fetch exchange flow data from APIs like Glassnode, CryptoQuant, etc.
        # For now, return neutral signal
        # Real implementation would:
        # 1. Fetch net flows from exchanges (positive = inflow to exchange = bearish)
        # 2. Signal = -net_flow (negative signal when inflow to exchange = bearish)
        # 3. Apply to relevant assets (mainly Bitcoin, Ethereum)
        
        # Return neutral signal for now
        return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('exchange_flow')


class MacroDataFactor(FactorBase):
    """
    Macro economic data factors (interest rates, inflation, etc.)
    """
    
    @property
    def category(self) -> str:
        return "alternative"
    
    def __init__(
        self,
        series: List[str] = ['DGS10', 'DGS2', 'CPIAUCSL', 'UNRATE', 'FEDFUNDS'],
        **params
    ):
        config = FactorConfig(
            name="MacroData",
            category="alternative",
            description="Macro economic data factors",
            params={'series': series}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # This would fetch macro data from FRED or similar
        # For now, return neutral signal
        # Real implementation would:
        # 1. Fetch data from FRED API
        # 2. Align with price data
        # 3. Calculate factors like term spread, credit spread, etc.
        # 4. Generate signals based on macro regime
        
        # Return neutral signal for now
        return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('macro_data')


class DollarIndexFactor(FactorBase):
    """
    US Dollar Index (DXY) as risk-on/risk-off indicator
    """
    
    @property
    def category(self) -> str:
        return "alternative"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="DollarIndex",
            category="alternative",
            description="US Dollar Index as risk-on/risk-off indicator",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # This would fetch DXY data
        # For now, return neutral signal
        # Real implementation would:
        # 1. Fetch DXY data (^DJI or similar)
        # 2. Calculate returns
        # 3. Signal = -DXY_returns (strong dollar = bearish for risk assets)
        # 4. Apply to crypto and risk assets
        
        # Return neutral signal for now
        return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('dollar_index')


class BitcoinDominanceFactor(FactorBase):
    """
    Bitcoin Dominance % as altcoin season indicator
    """
    
    @property
    def category(self) -> str:
        return "alternative"
    
    def __init__(self, **params):
        config = FactorConfig(
            name="BitcoinDominance",
            category="alternative",
            description="Bitcoin Dominance percentage",
            params={}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        # This would fetch Bitcoin dominance data
        # For now, return neutral signal
        # Real implementation would:
        # 1. Fetch Bitcoin dominance % (BTC market cap / total crypto market cap)
        # 2. Calculate changes
        # 3. Signal = -change in dominance (falling dominance = altcoin season = bullish for alts)
        # 4. Apply to altcoins (negative signal for BTC when dominance falling)
        
        # Return neutral signal for now
        return pd.DataFrame(0, index=prices.index, columns=prices.columns).stack().to_frame('btc_dominance')