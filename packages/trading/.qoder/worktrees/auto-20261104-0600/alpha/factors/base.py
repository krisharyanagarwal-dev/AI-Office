"""
Base Factor Classes
Core infrastructure for factor computation and pipelines
"""
import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from functools import lru_cache
import warnings
warnings.filterwarnings('ignore')


@dataclass
class FactorConfig:
    """Configuration for a factor"""
    name: str
    category: str
    description: str = ""
    params: Dict = field(default_factory=dict)
    lookback: Optional[int] = None
    frequency: str = "1d"
    enabled: bool = True
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class FactorBase(ABC):
    """
    Abstract base class for all factors
    """
    
    def __init__(self, config: Optional[FactorConfig] = None, **params):
        if config is None:
            config = FactorConfig(
                name=self.__class__.__name__,
                category=self.category,
                params=params
            )
        self.config = config
        self.params = {**config.params, **params}
        self._cache = {}
    
    @property
    @abstractmethod
    def category(self) -> str:
        """Factor category"""
        pass
    
    @abstractmethod
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        """
        Compute factor values
        
        Args:
            prices: Price DataFrame (dates x tickers)
            volumes: Optional volume DataFrame
            
        Returns:
            Factor DataFrame (dates x tickers)
        """
        pass
    
    def __call__(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        """Allow factor to be called directly"""
        return self.compute(prices, volumes, **kwargs)
    
    def validate_input(self, prices: pd.DataFrame, volumes: Optional[pd.DataFrame] = None):
        """Validate input data"""
        if prices.empty:
            raise ValueError("Prices DataFrame is empty")
        
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise ValueError("Prices index must be DatetimeIndex")
        
        if volumes is not None:
            if not volumes.index.equals(prices.index):
                raise ValueError("Volumes index must match prices index")
            if not volumes.columns.equals(prices.columns):
                raise ValueError("Volumes columns must match prices columns")
    
    def get_params(self) -> Dict:
        """Get factor parameters"""
        return self.params.copy()
    
    def set_params(self, **params):
        """Set factor parameters"""
        self.params.update(params)
        self._cache.clear()


class FactorPipeline:
    """
    Pipeline for computing multiple factors efficiently
    """
    
    def __init__(
        self,
        factors: List[FactorBase],
        cross_sectional: bool = True,
        normalization: str = 'rank',  # rank, zscore, none
        neutralize: Optional[List[str]] = None,  # market, sector, industry
        fill_method: str = 'ffill'
    ):
        self.factors = factors
        self.cross_sectional = cross_sectional
        self.normalization = normalization
        self.neutralize = neutralize or []
        self.fill_method = fill_method
        self._computed_factors = {}
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        """
        Compute all factors in pipeline
        
        Returns:
            Multi-index DataFrame (date, ticker) with factor values
        """
        results = {}
        
        for factor in self.factors:
            if not factor.config.enabled:
                continue
            
            try:
                factor_name = factor.config.name
                print(f"Computing {factor_name}...")
                
                factor_data = factor.compute(prices, volumes, **kwargs)
                results[factor_name] = factor_data
                
            except Exception as e:
                print(f"Error computing {factor.config.name}: {e}")
                continue
        
        if not results:
            return pd.DataFrame()
        
        # Combine into panel
        combined = self._combine_factors(results)
        
        # Cross-sectional normalization
        if self.cross_sectional:
            combined = self._cross_sectional_normalize(combined)
        
        # Neutralization
        if self.neutralize:
            combined = self._neutralize(combined, prices, **kwargs)
        
        return combined
    
    def _combine_factors(self, results: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Combine factor results into panel"""
        # Stack each factor
        stacked = {}
        for name, df in results.items():
            # Ensure proper format
            if isinstance(df.index, pd.MultiIndex):
                stacked[name] = df
            else:
                stacked[name] = df.stack()
                stacked[name].name = name
        
        # Combine
        combined = pd.concat(stacked, axis=1)
        combined.index.names = ['date', 'ticker']
        
        return combined
    
    def _cross_sectional_normalize(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply cross-sectional normalization"""
        if self.normalization == 'rank':
            return data.groupby(level=0).rank(pct=True) - 0.5
        elif self.normalization == 'zscore':
            return data.groupby(level=0).transform(
                lambda x: (x - x.mean()) / x.std().replace(0, np.nan)
            )
        elif self.normalization == 'none':
            return data
        else:
            raise ValueError(f"Unknown normalization: {self.normalization}")
    
    def _neutralize(
        self,
        data: pd.DataFrame,
        prices: pd.DataFrame,
        sectors: Optional[pd.Series] = None,
        **kwargs
    ) -> pd.DataFrame:
        """Neutralize factors to market/sector/industry"""
        neutralized = data.copy()
        
        for neutralizer in self.neutralize:
            if neutralizer == 'market':
                # Market neutral: subtract cross-sectional mean
                market_mean = neutralized.groupby(level=0).mean()
                neutralized = neutralized.sub(market_mean, axis=0, level=0)
                
            elif neutralizer == 'sector' and sectors is not None:
                # Sector neutral
                for date in neutralized.index.get_level_values(0).unique():
                    date_data = neutralized.xs(date, level=0)
                    date_sectors = sectors.reindex(date_data.index).dropna()
                    
                    for sector in date_sectors.unique():
                        sector_mask = date_sectors == sector
                        sector_data = date_data[sector_mask]
                        if len(sector_data) > 1:
                            sector_mean = sector_data.mean()
                            neutralized.loc[(date, sector_mask)] = sector_data.sub(sector_mean)
                            
            elif neutralizer == 'industry':
                # Industry neutral (requires industry mapping)
                pass
        
        return neutralized
    
    def get_factor_names(self) -> List[str]:
        """Get names of all factors in pipeline"""
        return [f.config.name for f in self.factors if f.config.enabled]
    
    def add_factor(self, factor: FactorBase):
        """Add factor to pipeline"""
        self.factors.append(factor)
    
    def remove_factor(self, name: str):
        """Remove factor from pipeline"""
        self.factors = [f for f in self.factors if f.config.name != name]
    
    def get_factor(self, name: str) -> Optional[FactorBase]:
        """Get factor by name"""
        for f in self.factors:
            if f.config.name == name:
                return f
        return None


def create_factor_pipeline(config) -> FactorPipeline:
    """Create factor pipeline from configuration"""
    from . import (
        MomentumFactor, RSIFactor, MACDFactor, RateOfChangeFactor,
        ShortTermReversalFactor, MediumTermReversalFactor,
        RealizedVolFactor, ParkinsonVolFactor,
        VolumeFactor, VWAPFactor, VolumeTrendFactor,
        BollingerFactor, KeltnerFactor, ATRFactor,
        FundingRateFactor, OpenInterestFactor, FearGreedFactor,
    )
    
    factors = []
    
    # Momentum
    if config.factors.momentum.enabled:
        factors.append(MomentumFactor(lookbacks=config.factors.momentum.lookbacks))
        factors.append(RSIFactor(periods=config.factors.technical.rsi))
        factors.append(MACDFactor())
        factors.append(RateOfChangeFactor())
    
    # Reversal
    if config.factors.reversal.enabled:
        factors.append(ShortTermReversalFactor(lookbacks=config.factors.reversal.lookbacks))
        factors.append(MediumTermReversalFactor())
    
    # Volatility
    if config.factors.volatility.enabled:
        factors.append(RealizedVolFactor(lookbacks=config.factors.volatility.lookbacks))
        if config.factors.volatility.parkinson:
            factors.append(ParkinsonVolFactor())
    
    # Volume
    if config.factors.volume.enabled:
        factors.append(VolumeFactor(lookbacks=config.factors.volume.lookbacks))
        if config.factors.volume.vwap:
            factors.append(VWAPFactor())
    
    # Technical
    if config.factors.technical.enabled:
        if config.factors.technical.bollinger:
            factors.append(BollingerFactor())
        if config.factors.technical.keltner:
            factors.append(KeltnerFactor())
        if config.factors.technical.atr:
            factors.append(ATRFactor())
    
    # Alternative
    if config.factors.alternative.enabled:
        if config.factors.alternative.funding_basis:
            factors.append(FundingRateFactor())
        if config.factors.alternative.oi_change:
            factors.append(OpenInterestFactor())
        if config.factors.alternative.fear_greed:
            factors.append(FearGreedFactor())
    
    return FactorPipeline(
        factors=factors,
        cross_sectional=config.factors.cross_sectional.rank,
        normalization='rank' if config.factors.cross_sectional.rank else 'none',
        neutralize=['market'] if config.factors.cross_sectional.market_neutral else [],
    )