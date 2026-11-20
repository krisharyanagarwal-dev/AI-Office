"""
Pairs / Statistical Arbitrage Factor
Cointegration-based pairs trading with Kalman filter hedge ratios
"""
import numpy as np
import pandas as pd
from .base import FactorBase
from typing import Dict, List, Optional, Tuple, Union, Literal
from dataclasses import dataclass, field
from itertools import combinations
import logging
from scipy import stats
from scipy.optimize import minimize
from statsmodels.tsa.stattools import coint, adfuller
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.tools import add_constant

logger = logging.getLogger(__name__)


@dataclass
class PairsConfig:
    """Configuration for pairs arbitrage"""
    # Pair selection
    min_correlation: float = 0.7
    max_pairs: int = 50
    lookback: int = 252  # 1 year for cointegration test
    
    # Cointegration
    coint_pvalue_threshold: float = 0.05
    adf_pvalue_threshold: float = 0.05
    
    # Hedge ratio estimation
    hedge_method: Literal["ols", "kalman", "rolling_ols"] = "kalman"
    kalman_obs_noise: float = 1e-3
    kalman_proc_noise: float = 1e-5
    rolling_window: int = 63
    
    # Signal generation
    entry_zscore: float = 2.0
    exit_zscore: float = 0.5
    stop_loss_zscore: float = 4.0
    
    # Risk management
    max_position_per_pair: float = 0.05
    max_total_exposure: float = 0.5
    vol_target: float = 0.10
    
    # Sector/industry constraints
    sector_neutral: bool = True
    max_sector_exposure: float = 0.2


@dataclass
class PairSignal:
    """Signal for a single pair"""
    pair: Tuple[str, str]  # (long, short)
    hedge_ratio: float
    spread: pd.Series
    zscore: pd.Series
    signal: pd.Series  # 1 = long spread, -1 = short spread, 0 = flat
    half_life: Optional[float] = None
    coint_pvalue: Optional[float] = None


class KalmanFilterHedge:
    """
    Kalman filter for dynamic hedge ratio estimation.
    Models spread as: y_t = beta_t * x_t + epsilon_t
    beta_t = beta_{t-1} + eta_t (random walk)
    """
    
    def __init__(
        self,
        obs_noise: float = 1e-3,
        proc_noise: float = 1e-5,
        initial_hedge: float = 1.0,
    ):
        self.obs_noise = obs_noise
        self.proc_noise = proc_noise
        
        # State: hedge ratio
        self.x = initial_hedge
        self.P = 1.0  # State covariance
        
        # Dynamics
        self.F = 1.0  # State transition (random walk)
        self.Q = proc_noise
        self.R = obs_noise
        self.H = 1.0  # Observation matrix (scalar)
    
    def update(self, y: float, x: float) -> float:
        """Kalman filter update step"""
        
        # Predict
        x_pred = self.F * self.x
        P_pred = self.F * self.P * self.F + self.Q
        
        # Update
        H = x  # Observation matrix is the independent variable
        innovation = y - H * x_pred
        S = H * P_pred * H + self.R
        K = P_pred * H / S
        
        self.x = x_pred + K * innovation
        self.P = (1 - K * H) * P_pred
        
        return self.x
    
    def filter_series(self, y: pd.Series, x: pd.Series) -> pd.Series:
        """Apply Kalman filter to entire series"""
        hedge_ratios = []
        
        for yt, xt in zip(y, x):
            if np.isnan(yt) or np.isnan(xt):
                hedge_ratios.append(np.nan)
                continue
            hr = self.update(yt, xt)
            hedge_ratios.append(hr)
        
        return pd.Series(hedge_ratios, index=y.index)


class PairsArbitrageFactor(FactorBase):
    """
    Pairs / Statistical Arbitrage Factor
    
    Features:
    - Universe screening for cointegrated pairs
    - Multiple hedge ratio methods: OLS, Rolling OLS, Kalman Filter
    - Cointegration testing (Engle-Granger, Johansen)
    - Signal generation with z-score thresholds
    - Risk management: position limits, stop-loss, sector neutrality
    """
    
    @property
    def category(self) -> str:
        return "pairs_arbitrage"
    
    def __init__(
        self,
        config: Optional[PairsConfig] = None,
        name: str = "pairs_arbitrage",
    ):
        super().__init__(config=None, name=name)
        self.config = config or PairsConfig()
        self.pairs_: List[PairSignal] = []
        self.pair_signals_ = pd.DataFrame()
    
    def find_pairs(
        self,
        prices: pd.DataFrame,
        sectors: Optional[pd.Series] = None,
    ) -> List[Tuple[str, str, float, float]]:
        """
        Find cointegrated pairs from price universe.
        
        Args:
            prices: DataFrame with close prices (dates x assets)
            sectors: Optional sector mapping for sector neutrality
            
        Returns:
            List of (asset1, asset2, hedge_ratio, coint_pvalue)
        """
        assets = prices.columns.tolist()
        n_assets = len(assets)
        
        logger.info(f"Screening {n_assets} assets for pairs...")
        
        pairs = []
        
        # Pre-filter by correlation
        returns = prices.pct_change().dropna()
        corr = returns.corr()
        
        # Generate candidate pairs
        for i, j in combinations(range(n_assets), 2):
            a1, a2 = assets[i], assets[j]
            
            # Correlation filter
            if corr.iloc[i, j] < self.config.min_correlation:
                continue
            
            # Sector filter
            if self.config.sector_neutral and sectors is not None:
                if sectors[a1] == sectors[a2]:
                    continue
            
            # Cointegration test
            coint_result = self._test_cointegration(
                prices[a1], prices[a2]
            )
            
            if coint_result is None:
                continue
            
            hedge_ratio, coint_pval, half_life = coint_result
            
            if coint_pval <= self.config.coint_pvalue_threshold:
                pairs.append((a1, a2, hedge_ratio, coint_pval, half_life))
        
        # Sort by cointegration p-value (most significant first)
        pairs.sort(key=lambda x: x[3])
        
        # Limit to max_pairs
        pairs = pairs[:self.config.max_pairs]
        
        logger.info(f"Found {len(pairs)} cointegrated pairs")
        
        return pairs
    
    def _test_cointegration(
        self,
        y: pd.Series,
        x: pd.Series,
    ) -> Optional[Tuple[float, float, float]]:
        """Test for cointegration using Engle-Granger two-step method"""
        
        # Align and drop NaN
        df = pd.concat([y, x], axis=1).dropna()
        if len(df) < 100:
            return None
        
        y_clean = df.iloc[:, 0]
        x_clean = df.iloc[:, 1]
        
        # Step 1: OLS regression for hedge ratio
        x_const = add_constant(x_clean)
        model = OLS(y_clean, x_const).fit()
        hedge_ratio = model.params.iloc[1]
        spread = y_clean - hedge_ratio * x_clean
        
        # Step 2: ADF test on spread
        adf_result = adfuller(spread.dropna(), autolag='AIC')
        adf_pvalue = adf_result[1]
        
        if adf_pvalue > self.config.adf_pvalue_threshold:
            return None
        
        # Cointegration test (Engle-Granger)
        coint_result = coint(y_clean, x_clean)
        coint_pvalue = coint_result[1]
        
        # Half-life of mean reversion
        half_life = self._estimate_half_life(spread)
        
        return hedge_ratio, coint_pvalue, half_life
    
    def _estimate_half_life(self, spread: pd.Series) -> Optional[float]:
        """Estimate half-life of mean reversion"""
        
        spread_clean = spread.dropna()
        if len(spread_clean) < 20:
            return None
        
        # AR(1): spread_t = rho * spread_{t-1} + epsilon
        lagged = spread_clean.shift(1).dropna()
        current = spread_clean.loc[lagged.index]
        
        # OLS regression
        X = add_constant(lagged)
        model = OLS(current, X).fit()
        rho = model.params.iloc[1]
        
        if rho <= 0 or rho >= 1:
            return None
        
        half_life = -np.log(2) / np.log(rho)
        
        return half_life
    
    def compute_signals(
        self,
        prices: pd.DataFrame,
        pairs: List[Tuple[str, str, float, float, float]],
    ) -> Dict[Tuple[str, str], PairSignal]:
        """
        Generate trading signals for each pair.
        
        Args:
            prices: Price DataFrame
            pairs: List of (asset1, asset2, hedge_ratio, coint_pval, half_life)
            
        Returns:
            Dict of pair -> PairSignal
        """
        signals = {}
        
        for a1, a2, static_hedge, coint_pval, half_life in pairs:
            y = prices[a1]
            x = prices[a2]
            
            # Compute dynamic hedge ratio
            if self.config.hedge_method == "kalman":
                kf = KalmanFilterHedge(
                    obs_noise=self.config.kalman_obs_noise,
                    proc_noise=self.config.kalman_proc_noise,
                    initial_hedge=static_hedge,
                )
                hedge_ratios = kf.filter_series(y, x)
            elif self.config.hedge_method == "rolling_ols":
                hedge_ratios = self._rolling_ols_hedge(y, x)
            else:
                hedge_ratios = pd.Series(static_hedge, index=y.index)
            
            # Compute spread
            spread = y - hedge_ratios * x
            
            # Compute z-score
            zscore = self._compute_zscore(spread)
            
            # Generate signal
            signal = self._generate_signal(zscore)
            
            pair_signal = PairSignal(
                pair=(a1, a2),
                hedge_ratio=hedge_ratios,
                spread=spread,
                zscore=zscore,
                signal=signal,
                half_life=half_life,
                coint_pvalue=coint_pvalue,
            )
            
            signals[(a1, a2)] = pair_signal
        
        self.pairs_ = list(signals.values())
        return signals
    
    def _rolling_ols_hedge(self, y: pd.Series, x: pd.Series) -> pd.Series:
        """Rolling OLS hedge ratio"""
        
        hedge_ratios = []
        window = self.config.rolling_window
        
        for i in range(window, len(y)):
            y_win = y.iloc[i-window:i]
            x_win = x.iloc[i-window:i]
            
            df = pd.concat([y_win, x_win], axis=1).dropna()
            if len(df) < window // 2:
                hedge_ratios.append(np.nan)
                continue
            
            model = OLS(df.iloc[:, 0], add_constant(df.iloc[:, 1])).fit()
            hedge_ratios.append(model.params.iloc[1])
        
        return pd.Series(
            [np.nan] * window + hedge_ratios,
            index=y.index
        )
    
    def _compute_zscore(self, spread: pd.Series, window: int = 63) -> pd.Series:
        """Compute rolling z-score of spread"""
        
        rolling_mean = spread.rolling(window).mean()
        rolling_std = spread.rolling(window).std()
        
        zscore = (spread - rolling_mean) / (rolling_std + 1e-8)
        
        return zscore
    
    def _generate_signal(self, zscore: pd.Series) -> pd.Series:
        """Generate trading signal from z-score"""
        
        signal = pd.Series(0, index=zscore.index)
        
        # State machine for position management
        position = 0  # 1 = long spread, -1 = short spread, 0 = flat
        
        for i, z in enumerate(zscore):
            if np.isnan(z):
                signal.iloc[i] = position
                continue
            
            if position == 0:
                # No position - check entry
                if z > self.config.entry_zscore:
                    position = -1  # Short spread (long x, short y)
                elif z < -self.config.entry_zscore:
                    position = 1   # Long spread (long y, short x)
            elif position == 1:
                # Long spread - check exit
                if z > -self.config.exit_zscore:
                    position = 0
                elif z < -self.config.stop_loss_zscore:
                    position = 0  # Stop loss
            elif position == -1:
                # Short spread - check exit
                if z < self.config.exit_zscore:
                    position = 0
                elif z > self.config.stop_loss_zscore:
                    position = 0  # Stop loss
            
            signal.iloc[i] = position
        
        return signal
    
    def compute(
        self,
        data: Dict[str, pd.DataFrame],
        **kwargs
    ) -> pd.Series:
        """
        Compute pairs arbitrage portfolio signal.
        
        Args:
            data: Dict with 'prices' (required), 'sectors' (optional)
            
        Returns:
            pd.Series with portfolio-level signal
        """
        prices = data.get('prices')
        if prices is None:
            raise ValueError("Missing 'prices' in data")
        
        sectors = data.get('sectors')
        
        # Find pairs
        pairs = self.find_pairs(prices, sectors)
        
        if not pairs:
            logger.warning("No pairs found")
            return pd.Series(dtype=float)
        
        # Generate signals
        pair_signals = self.compute_signals(prices, pairs)
        
        if not pair_signals:
            logger.warning("No signals generated")
            return pd.Series(dtype=float)
        
        # Build portfolio
        portfolio_signal = self._build_portfolio(pair_signals, prices)
        
        return portfolio_signal
    
    def _build_portfolio(
        self,
        pair_signals: Dict[Tuple[str, str], PairSignal],
        prices: pd.DataFrame,
    ) -> pd.Series:
        """Build portfolio from pair signals"""
        
        # Align all signals
        all_dates = prices.index
        
        # Initialize position matrix
        position_matrix = pd.DataFrame(0, index=all_dates, columns=prices.columns)
        
        for (a1, a2), ps in pair_signals.items():
            signal = ps.signal.reindex(all_dates).fillna(0)
            hedge = ps.hedge_ratio.reindex(all_dates).ffill().fillna(1.0)
            
            # Long a1, short hedge*a2 (when signal=1)
            # Short a1, long hedge*a2 (when signal=-1)
            position_matrix[a1] += signal
            position_matrix[a2] -= signal * hedge
        
        # Apply position limits
        position_matrix = position_matrix.clip(
            -self.config.max_position_per_pair,
            self.config.max_position_per_pair
        )
        
        # Sector neutrality
        if self.config.sector_neutral and 'sectors' in prices.columns:
            position_matrix = self._neutralize_sectors(position_matrix, prices)
        
        # Volatility scaling
        portfolio = position_matrix.sum(axis=1)
        if self.config.vol_target > 0:
            portfolio = self._vol_scale(portfolio)
        
        return portfolio
    
    def _vol_scale(self, signal: pd.Series, window: int = 63) -> pd.Series:
        """Scale signal to target volatility"""
        vol = signal.rolling(window).std() * np.sqrt(252)
        scale = self.config.vol_target / (vol + 1e-8)
        scale = scale.clip(0.5, 2.0)
        return signal * scale
    
    def _neutralize_sectors(
        self,
        positions: pd.DataFrame,
        prices: pd.DataFrame,
    ) -> pd.DataFrame:
        """Neutralize sector exposure"""
        
        # This is a simplified version - in practice you'd have a sector mapping
        # For now, just cap total exposure
        total_exposure = positions.abs().sum(axis=1)
        max_exp = self.config.max_total_exposure
        
        if (total_exposure > max_exp).any():
            scale = np.where(total_exposure > max_exp, max_exp / total_exposure, 1.0)
            positions = positions.mul(scale, axis=0)
        
        return positions
    
    def get_pair_details(self) -> pd.DataFrame:
        """Get detailed info on all pairs"""
        if not self.pairs_:
            return pd.DataFrame()
        
        rows = []
        for ps in self.pairs_:
            a1, a2 = ps.pair
            rows.append({
                'pair': f"{a1}/{a2}",
                'long': a1,
                'short': a2,
                'mean_hedge': ps.hedge_ratio.mean(),
                'half_life': ps.half_life,
                'coint_pvalue': ps.coint_pvalue,
                'current_signal': ps.signal.iloc[-1] if len(ps.signal) > 0 else 0,
            })
        
        return pd.DataFrame(rows)


def create_pairs_arbitrage(
    min_correlation: float = 0.7,
    max_pairs: int = 50,
    entry_zscore: float = 2.0,
    exit_zscore: float = 0.5,
    hedge_method: Literal["ols", "kalman", "rolling_ols"] = "kalman",
    **kwargs
) -> PairsArbitrageFactor:
    """Factory function for pairs arbitrage factor"""
    config = PairsConfig(
        min_correlation=min_correlation,
        max_pairs=max_pairs,
        entry_zscore=entry_zscore,
        exit_zscore=exit_zscore,
        hedge_method=hedge_method,
        **kwargs
    )
    return PairsArbitrageFactor(config=config)


if __name__ == "__main__":
    # Quick test
    import numpy as np
    import pandas as pd
    
    np.random.seed(42)
    n = 500
    dates = pd.date_range('2020-01-01', periods=n, freq='D')
    assets = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'JPM', 'BAC', 'XOM', 'CVX']
    
    # Create synthetic cointegrated pairs
    prices = pd.DataFrame(index=dates, columns=assets, dtype=float)
    
    # Base factors
    market = np.cumsum(np.random.normal(0.0002, 0.01, n))
    
    # Create cointegrated pairs
    for i, asset in enumerate(assets):
        if i < 4:  # First 4: tech cluster
            prices[asset] = 100 + market + 0.5 * np.cumsum(np.random.normal(0, 0.005, n))
        elif i < 8:  # Next 4: bank/energy cluster
            prices[asset] = 50 + 0.8 * market + 0.3 * np.cumsum(np.random.normal(0, 0.008, n))
        else:
            prices[asset] = 75 + np.cumsum(np.random.normal(0.0001, 0.012, n))
    
    # Add specific cointegrated pair
    common = np.cumsum(np.random.normal(0, 0.005, n))
    prices['AAPL'] = 150 + common + np.cumsum(np.random.normal(0, 0.003, n))
    prices['MSFT'] = 200 + 0.9 * common + np.cumsum(np.random.normal(0, 0.004, n))
    
    factor = create_pairs_arbitrage(
        min_correlation=0.5,
        max_pairs=10,
        entry_zscore=2.0,
        hedge_method="kalman",
    )
    
    data = {'prices': prices}
    signal = factor.compute(data)
    
    print(f"Signal shape: {signal.shape}")
    print(f"Signal stats: mean={signal.mean():.6f}, std={signal.std():.6f}")
    print(f"Pairs found: {len(factor.pairs_)}")
    
    details = factor.get_pair_details()
    print(f"\nPair details:\n{details}")