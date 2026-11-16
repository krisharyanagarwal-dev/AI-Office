"""
Volatility Factors
Volatility-based alpha factors
"""
import pandas as pd
import numpy as np
from typing import List, Optional
from scipy import stats

from .base import FactorBase, FactorConfig


class RealizedVolFactor(FactorBase):
    """
    Realized volatility factor
    Standard deviation of returns over various lookbacks
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        lookbacks: List[int] = [10, 20, 60, 120, 252],
        annualize: bool = True,
        **params
    ):
        config = FactorConfig(
            name="RealizedVol",
            category="volatility",
            description="Realized volatility over multiple lookbacks",
            params={'lookbacks': lookbacks, 'annualize': annualize}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookbacks = self.params.get('lookbacks', [10, 20, 60, 120, 252])
        annualize = self.params.get('annualize', True)
        
        ann_factor = np.sqrt(252) if annualize else 1
        
        results = {}
        returns = prices.pct_change()
        
        for lb in lookbacks:
            vol = returns.rolling(lb).std() * ann_factor
            results[f'vol_{lb}'] = vol.stack()
        
        return pd.concat(results, axis=1)


class ParkinsonVolFactor(FactorBase):
    """
    Parkinson (1980) High-Low Volatility Estimator
    Uses high/low prices for more efficient volatility estimation
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        lookbacks: List[int] = [10, 20, 60],
        annualize: bool = True,
        **params
    ):
        config = FactorConfig(
            name="ParkinsonVol",
            category="volatility",
            description="Parkinson high-low volatility estimator",
            params={'lookbacks': lookbacks, 'annualize': annualize}
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
            # Approximate from close prices
            high = prices.rolling(2).max()
            low = prices.rolling(2).min()
        
        lookbacks = self.params.get('lookbacks', [10, 20, 60])
        annualize = self.params.get('annualize', True)
        
        # Parkinson estimator: sqrt(1/(4*ln(2)*N) * sum(ln(H/L)^2))
        # Factor: 1/(4*ln(2)) ≈ 0.361
        factor = 1.0 / (4.0 * np.log(2))
        
        ann_factor = np.sqrt(252) if self.params.get('annualize', True) else 1
        
        results = {}
        for lb in lookbacks:
            hl_ratio = np.log(high / low.replace(0, np.nan))
            hl_squared = hl_ratio ** 2
            
            parkinson_var = hl_squared.rolling(lb).mean() * factor
            parkinson_vol = np.sqrt(parkinson_var) * ann_factor
            
            results[f'parkinson_vol_{lb}'] = parkinson_vol.stack()
        
        return pd.concat(results, axis=1)


class GarmanKlassVolFactor(FactorBase):
    """
    Garman-Klass (1980) Volatility Estimator
    Uses OHLC for more efficient estimation
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        lookbacks: List[int] = [10, 20, 60],
        annualize: bool = True,
        **params
    ):
        config = FactorConfig(
            name="GarmanKlassVol",
            category="volatility",
            description="Garman-Klass OHLC volatility estimator",
            params={'lookbacks': lookbacks, 'annualize': annualize}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        high: Optional[pd.DataFrame] = None,
        low: Optional[pd.DataFrame] = None,
        open_prices: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if high is None or low is None or open_prices is None:
            return pd.DataFrame()
        
        lookbacks = self.params.get('lookbacks', [10, 20, 60])
        annualize = self.params.get('annualize', True)
        
        # Garman-Klass estimator
        # σ² = (1/N) * Σ[0.5*(ln(H/L))² - (2ln2-1)*(ln(C/O))²]
        
        results = {}
        ann_factor = np.sqrt(252) if annualize else 1
        
        for lb in lookbacks:
            term1 = 0.5 * (np.log(high / low.replace(0, np.nan))) ** 2
            term2 = (2 * np.log(2) - 1) * (np.log(prices / open_prices.replace(0, np.nan))) ** 2
            
            gk_var = (term1 - term2).rolling(lb).mean()
            gk_var = gk_var.clip(lower=0)  # Variance can't be negative
            gk_vol = np.sqrt(gk_var) * ann_factor
            
            results[f'gk_vol_{lb}'] = gk_vol.stack()
        
        return pd.concat(results, axis=1)


class YangZhangVolFactor(FactorBase):
    """
    Yang-Zhang (2000) Volatility Estimator
    Most efficient estimator using OHLC with overnight jumps
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        lookbacks: List[int] = [10, 20, 60],
        annualize: bool = True,
        **params
    ):
        config = FactorConfig(
            name="YangZhangVol",
            category="volatility",
            description="Yang-Zhang OHLC volatility with overnight jumps",
            params={'lookbacks': lookbacks, 'annualize': annualize}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        high: Optional[pd.DataFrame] = None,
        low: Optional[pd.DataFrame] = None,
        open_prices: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if high is None or low is None or open_prices is None:
            return pd.DataFrame()
        
        lookbacks = self.params.get('lookbacks', [10, 20, 60])
        annualize = self.params.get('annualize', True)
        
        # Yang-Zhang components:
        # σ² = σ²_overnight + k*σ²_open_close + (1-k)*σ²_RS
        # where k = 0.34 / (1.34 + (n+1)/(n-1))
        
        prev_close = prices.shift(1)
        
        # Overnight variance
        overnight = np.log(open_prices / prices.shift(1).replace(0, np.nan))
        
        # Open-close variance
        open_close = np.log(prices / open_prices.replace(0, np.nan))
        
        # Rogers-Satchell (high-low-open-close)
        rs = (np.log(high / low.replace(0, np.nan)) * np.log(high / open_prices.replace(0, np.nan)) +
              np.log(low / open_prices.replace(0, np.nan)) * np.log(low / low.replace(0, np.nan)))
        
        results = {}
        for lb in self.params.get('lookbacks', [10, 20, 60]):
            k = 0.34 / (1.34 + (lb + 1) / (lb - 1))
            
            var_overnight = overnight.rolling(lb).var()
            var_open_close = open_close.rolling(lb).var()
            var_rs = (open_close * np.log(high / open_prices.replace(0, np.nan)) +
                     np.log(low / open_prices.replace(0, np.nan)) * np.log(low / low.replace(0, np.nan))).rolling(lb).mean()
            
            yz_var = var_overnight + k * var_open_close + (1 - k) * var_rs
            yz_vol = np.sqrt(yz_var.clip(lower=0))
            
            if self.params.get('annualize', True):
                yz_vol = yz_vol * np.sqrt(252)
            
            results[f'yz_vol_{lb}'] = yz_vol.stack()
        
        return pd.concat(results, axis=1)


class GARCHVolFactor(FactorBase):
    """
    GARCH(1,1) Conditional Volatility
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        omega: float = 0.000001,
        alpha: float = 0.1,
        beta: float = 0.85,
        **params
    ):
        config = FactorConfig(
            name="GARCHVol",
            category="volatility",
            description="GARCH(1,1) conditional volatility",
            params={'omega': omega, 'alpha': alpha, 'beta': beta}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        omega = self.params.get('omega', 0.000001)
        alpha = self.params.get('alpha', 0.1)
        beta = self.params.get('beta', 0.85)
        
        returns = prices.pct_change().fillna(0)
        
        results = {}
        
        for ticker in prices.columns:
            ret = returns[ticker].values
            
            # Initialize variance
            var = np.zeros_like(ret)
            var[0] = np.var(ret[:30]) if len(ret) > 30 else np.var(ret)
            
            # GARCH recursion
            for t in range(1, len(ret)):
                var[t] = omega + alpha * ret[t-1]**2 + beta * var[t-1]
            
            garch_vol = pd.Series(np.sqrt(var * 252), index=prices.index)
            results[ticker] = garch_vol
        
        garch_df = pd.DataFrame(results, index=prices.index)
        return garch_df.stack().to_frame('garch_vol')


class VolatilityRiskPremium(FactorBase):
    """
    Volatility Risk Premium (VRP)
    Difference between implied and realized volatility
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        lookback: int = 60,
        **params
    ):
        config = FactorConfig(
            name="VolRiskPremium",
            category="volatility",
            description="Volatility risk premium (requires IV data)",
            params={'lookback': lookback}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        implied_vol: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        """
        VRP = IV - RV
        Positive VRP = options overpriced = sell vol
        """
        if implied_vol is None:
            # Can't compute without IV data
            return pd.DataFrame()
        
        lookback = self.params.get('lookback', 60)
        
        # Realized volatility
        rv = prices.pct_change().rolling(lookback).std() * np.sqrt(252)
        
        # VRP
        vrp = implied_vol - rv
        
        # Normalized VRP
        vrp_norm = vrp / rv.replace(0, np.nan)
        
        results = {
            'vrp': vrp.stack(),
            'vrp_normalized': vrp_norm.stack(),
            'realized_vol': rv.stack(),
            'implied_vol': implied_vol.stack(),
        }
        
        return pd.concat(results, axis=1)


class VolatilityTermStructure(FactorBase):
    """
    Volatility Term Structure
    Slope of volatility curve (short-term vs long-term vol)
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        short_lb: int = 10,
        long_lb: int = 60,
        **params
    ):
        config = FactorConfig(
            name="VolTermStructure",
            category="volatility",
            description="Volatility term structure slope",
            params={'short_lb': short_lb, 'long_lb': long_lb}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        short_lb = self.params.get('short_lb', 10)
        long_lb = self.params.get('long_lb', 60)
        
        vol_short = prices.pct_change().rolling(short_lb).std() * np.sqrt(252)
        vol_long = prices.pct_change().rolling(long_lb).std() * np.sqrt(252)
        
        # Term structure slope
        slope = (vol_short - vol_long) / vol_long.replace(0, np.nan)
        
        # Volatility curve level (average)
        level = (vol_short + vol_long) / 2
        
        # Curvature (if we had 3 points)
        results = {
            'vol_term_slope': slope.stack(),
            'vol_term_level': level.stack(),
            'vol_short': vol_short.stack(),
            'vol_long': vol_long.stack(),
        }
        
        return pd.concat(results, axis=1)


class VolatilityMeanReversion(FactorBase):
    """
    Volatility Mean Reversion
    Volatility tends to revert to its mean
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        lookback: int = 60,
        **params
    ):
        config = FactorConfig(
            name="VolMeanReversion",
            category="volatility",
            description="Volatility mean reversion signal",
            params={'lookback': lookback}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookback = self.params.get('lookback', 60)
        
        # Current volatility
        current_vol = prices.pct_change().rolling(20).std()
        
        # Historical mean and std of volatility
        vol_series = prices.pct_change().rolling(20).std()
        vol_mean = vol_series.rolling(lookback).mean()
        vol_std = vol_series.rolling(lookback).std()
        
        # Z-score of current volatility
        vol_zscore = (current_vol - vol_mean) / vol_std.replace(0, np.nan)
        
        # Mean reversion signal: high vol -> expect decrease (negative)
        mr_signal = -vol_zscore
        
        # Percentile rank
        vol_percentile = vol_series.rolling(lookback).rank(pct=True)
        
        results = {
            'vol_zscore': vol_zscore.stack(),
            'vol_mr_signal': mr_signal.stack(),
            'vol_percentile': vol_percentile.stack(),
            'current_vol': current_vol.stack(),
            'vol_mean': vol_mean.stack(),
        }
        
        return pd.concat(results, axis=1)


class RealizedSkewFactor(FactorBase):
    """
    Realized Skewness
    Negative skewness predicts higher returns (risk premium)
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        lookbacks: List[int] = [60, 120, 252],
        **params
    ):
        config = FactorConfig(
            name="RealizedSkew",
            category="volatility",
            description="Realized return skewness",
            params={'lookbacks': lookbacks}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookbacks = self.params.get('lookbacks', [60, 120, 252])
        
        returns = prices.pct_change()
        
        results = {}
        for lb in lookbacks:
            skew = returns.rolling(lb).skew()
            results[f'realized_skew_{lb}'] = skew.stack()
        
        return pd.concat(results, axis=1)


class RealizedKurtosisFactor(FactorBase):
    """
    Realized Kurtosis
    Fat tails prediction
    """
    
    @property
    def category(self) -> str:
        return "volatility"
    
    def __init__(
        self,
        lookbacks: List[int] = [60, 120, 252],
        **params
    ):
        config = FactorConfig(
            name="RealizedKurtosis",
            category="volatility",
            description="Realized return kurtosis (fat tails)",
            params={'lookbacks': lookbacks}
        )
        super().__init__(config, **params)
    
    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookbacks = self.params.get('lookbacks', [60, 120, 252])
        
        returns = prices.pct_change()
        
        results = {}
        for lb in lookbacks:
            kurt = returns.rolling(lb).kurtosis()
            results[f'realized_kurt_{lb}'] = kurt.stack()
        
        return pd.concat(results, axis=1)