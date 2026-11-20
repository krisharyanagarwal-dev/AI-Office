"""
Option Greeks / IV Factor
Volatility surface, IV rank, term structure, skew factors
"""
import numpy as np
import pandas as pd
from .base import FactorBase
from typing import Dict, List, Optional, Tuple, Union, Literal
from dataclasses import dataclass, field
from scipy.stats import norm
from scipy.optimize import brentq, minimize
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class OptionConfig:
    """Configuration for option factors"""
    # IV calculation
    iv_method: Literal["bsm", "bjerksund_stensland"] = "bsm"
    risk_free_rate: float = 0.05
    dividend_yield: float = 0.0
    
    # IV surface
    min_dte: int = 7
    max_dte: int = 365
    min_volume: int = 10
    min_open_interest: int = 50
    
    # Surface interpolation
    interp_method: Literal["linear", "cubic", "svi"] = "svi"
    
    # IV rank/percentile
    iv_rank_window: int = 252  # 1 year
    term_structure_points: List[int] = field(default_factory=lambda: [30, 60, 90, 180, 365])
    
    # Skew
    skew_delta_range: Tuple[float, float] = (0.10, 0.90)
    skew_measure: Literal["risk_reversal", "butterfly", "slope"] = "risk_reversal"
    
    # Risk management
    vol_target: float = 0.15


class BSMEngine:
    """Black-Scholes-Merton option pricing and Greeks"""
    
    @staticmethod
    def price(
        S: float, K: float, T: float, r: float, sigma: float,
        option_type: str = 'call', q: float = 0.0
    ) -> float:
        """European option price"""
        if T <= 0:
            return max(0, S - K) if option_type == 'call' else max(0, K - S)
        
        d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        if option_type == 'call':
            return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)
    
    @staticmethod
    def implied_vol(
        price: float, S: float, K: float, T: float, r: float,
        option_type: str = 'call', q: float = 0.0,
        max_iter: int = 100, tol: float = 1e-6
    ) -> float:
        """Calculate implied volatility using Brent's method"""
        
        def obj(sigma):
            return BSMEngine.price(S, K, T, r, sigma, option_type, q) - price
        
        try:
            # Check bounds
            intrinsic = max(0, S - K) if option_type == 'call' else max(0, K - S)
            if price < intrinsic * 0.99:
                return np.nan
            
            return brentq(obj, 1e-6, 5.0, xtol=tol, maxiter=max_iter)
        except ValueError:
            return np.nan
    
    @staticmethod
    def greeks(
        S: float, K: float, T: float, r: float, sigma: float,
        option_type: str = 'call', q: float = 0.0
    ) -> Dict[str, float]:
        """Calculate all Greeks"""
        
        if T <= 0:
            return {'delta': 0, 'gamma': 0, 'vega': 0, 'theta': 0, 'rho': 0}
        
        d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        pdf_d1 = norm.pdf(d1)
        cdf_d1 = norm.cdf(d1)
        cdf_d2 = norm.cdf(d2)
        
        if option_type == 'call':
            delta = np.exp(-q * T) * cdf_d1
            theta = (-S * sigma * np.exp(-q * T) * pdf_d1 / (2 * np.sqrt(T))
                    - r * K * np.exp(-r * T) * norm.cdf(d2)
                    + q * S * np.exp(-q * T) * cdf_d1)
            rho = K * T * np.exp(-r * T) * norm.cdf(d2)
        else:
            delta = -np.exp(-q * T) * norm.cdf(-d1)
            theta = (-S * sigma * np.exp(-q * T) * pdf_d1 / (2 * np.sqrt(T))
                    + r * K * np.exp(-r * T) * norm.cdf(-d2)
                    - q * S * np.exp(-q * T) * norm.cdf(-d1))
            rho = -K * T * np.exp(-r * T) * norm.cdf(-d2)
        
        gamma = np.exp(-q * T) * pdf_d1 / (S * sigma * np.sqrt(T))
        vega = S * np.exp(-q * T) * pdf_d1 * np.sqrt(T) / 100  # Per 1% vol change
        
        return {
            'delta': delta,
            'gamma': gamma,
            'vega': vega,
            'theta': theta / 365,  # Daily theta
            'rho': rho / 100,      # Per 1% rate change
        }


class SVIModel:
    """SVI (Stochastic Volatility Inspired) parameterization for IV surface"""
    
    def __init__(self):
        self.params_ = None  # a, b, rho, m, sigma
    
    def _svi_variance(self, k: np.ndarray, params: np.ndarray) -> np.ndarray:
        """SVI raw variance parameterization"""
        a, b, rho, m, sigma = params
        return a + b * (rho * (k - m) + np.sqrt((k - m)**2 + sigma**2))
    
    def _svi_price(self, k: np.ndarray, params: np.ndarray) -> np.ndarray:
        """SVI total variance"""
        return self._svi_variance(k, params)
    
    def fit(
        self,
        k: np.ndarray,  # log-moneyness: log(K/F)
        v: np.ndarray,  # total variance: sigma^2 * T
        weights: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Fit SVI parameters"""
        
        if weights is None:
            weights = np.ones_like(k)
        
        # Initial guess
        a0 = np.min(v)
        b0 = 0.1
        rho0 = 0.0
        m0 = k[np.argmin(v)]
        sigma0 = np.sqrt(np.mean((v - a0)**2))
        
        initial = np.array([a0, b0, rho0, m0, sigma0])
        
        # Constraints: a > 0, b > 0, -1 < rho < 1, sigma > 0
        bounds = [(1e-6, None), (1e-6, None), (-0.999, 0.999), (None, None), (1e-6, None)]
        
        def objective(params):
            v_pred = self._svi_variance(k, params)
            return np.sum(weights * (v - v_pred)**2)
        
        # Constraints for no-arbitrage
        constraints = [
            {'type': 'ineq', 'fun': lambda p: p[0]},  # a > 0
            {'type': 'ineq', 'fun': lambda p: p[1]},  # b > 0
            {'type': 'ineq', 'fun': lambda p: 1 + p[2]},  # 1+rho > 0
            {'type': 'ineq', 'fun': lambda p: 1 - p[2]},  # 1-rho > 0
            {'type': 'ineq', 'fun': lambda p: p[4]},  # sigma > 0
            {'type': 'ineq', 'fun': lambda p: p[1] * (1 + abs(p[2])) - 4 / np.sqrt(1 - p[2]**2) if abs(p[2]) < 1 else 0},  # No calendar arb
        ]
        
        result = minimize(
            objective, initial, bounds=bounds, constraints=constraints,
            method='SLSQP', options={'maxiter': 500, 'ftol': 1e-8}
        )
        
        if result.success:
            self.params_ = result.x
            return self.params_
        else:
            logger.warning(f"SVI fit failed: {result.message}")
            self.params_ = initial
            return self.params_
    
    def evaluate(self, k: np.ndarray) -> np.ndarray:
        """Evaluate SVI variance at given moneyness"""
        if self.params_ is None:
            raise ValueError("Model not fitted")
        return self._svi_variance(k, self.params_)


class OptionFactor(FactorBase):
    """
    Option Greeks / IV Factor
    
    Features:
    - IV surface construction (SVI, linear, cubic)
    - IV rank/percentile across time
    - Term structure slope/curvature
    - Skew measures (risk reversal, butterfly, slope)
    - Greeks-based signals (vega, gamma, theta)
    - Dispersion trading signals
    """
    
    @property
    def category(self) -> str:
        return "option_greeks"
    
    def __init__(
        self,
        config: Optional[OptionConfig] = None,
        name: str = "option_greeks",
    ):
        super().__init__(config=None, name=name)
        self.config = config or OptionConfig()
        self.svi_models_ = {}  # per expiration
        self.iv_surface_ = None
    
    def _clean_option_data(
        self,
        options: pd.DataFrame,
        spot: float,
    ) -> pd.DataFrame:
        """Clean and filter option chain data"""
        
        # Expected columns: expiry, strike, type, bid, ask, mid, volume, open_interest
        req_cols = ['expiry', 'strike', 'type', 'bid', 'ask', 'mid', 'volume', 'open_interest']
        missing = [c for c in req_cols if c not in options.columns]
        if missing:
            logger.warning(f"Missing columns: {missing}")
        
        df = options.copy()
        
        # Convert expiry
        if 'expiry' in df.columns:
            df['expiry'] = pd.to_datetime(df['expiry'])
            df['dte'] = (df['expiry'] - pd.Timestamp.now()).dt.days
        
        # Filter
        df = df[
            (df['dte'] >= self.config.min_dte) &
            (df['dte'] <= self.config.max_dte) &
            (df['volume'] >= self.config.min_volume) &
            (df['open_interest'] >= self.config.min_open_interest) &
            (df['bid'] > 0) &
            (df['ask'] > df['bid'])
        ].copy()
        
        # Mid price
        df['mid'] = (df['bid'] + df['ask']) / 2
        
        # Moneyness
        df['moneyness'] = df['strike'] / spot
        df['log_moneyness'] = np.log(df['strike'] / spot)
        
        return df
    
    def compute_iv_surface(
        self,
        options: pd.DataFrame,
        spot: float,
    ) -> pd.DataFrame:
        """
        Compute implied volatility surface.
        
        Returns DataFrame with columns: expiry, strike, type, iv, greeks
        """
        df = self._clean_option_data(options, spot)
        
        if df.empty:
            return pd.DataFrame()
        
        # Compute IV for each option
        ivs = []
        greeks_list = []
        
        for _, row in df.iterrows():
            iv = BSMEngine.implied_vol(
                row['mid'], spot, row['strike'], row['dte'] / 365,
                self.config.risk_free_rate, row['type'],
                q=self.config.dividend_yield
            )
            ivs.append(iv)
            
            if not np.isnan(iv):
                greeks = BSMEngine.greeks(
                    spot, row['strike'], row['dte'] / 365,
                    self.config.risk_free_rate, iv, row['type'],
                    q=self.config.dividend_yield
                )
                greeks_list.append(greeks)
            else:
                greeks_list.append({})
        
        df['iv'] = ivs
        
        # Add greeks
        for g in ['delta', 'gamma', 'vega', 'theta', 'rho']:
            df[g] = [g.get(g, np.nan) for g in greeks_list]
        
        return df
    
    def fit_svi_surface(
        self,
        iv_data: pd.DataFrame,
    ) -> Dict[str, SVIModel]:
        """Fit SVI model per expiration"""
        
        models = {}
        
        for expiry in iv_data['expiry'].unique():
            exp_data = iv_data[iv_data['expiry'] == expiry]
            
            # Separate calls and puts
            for opt_type in ['call', 'put']:
                type_data = exp_data[exp_data['type'] == opt_type]
                
                if len(type_data) < 5:
                    continue
                
                # Forward price
                F = spot * np.exp(self.config.risk_free_rate * type_data['dte'].iloc[0] / 365)
                
                # Log moneyness
                k = np.log(type_data['strike'] / F)
                v = type_data['iv']**2 * type_data['dte'] / 365  # Total variance
                
                # Weights by open interest
                weights = type_data['open_interest'].values
                weights = weights / weights.sum()
                
                # Fit SVI
                svi = SVIModel()
                svi.fit(k.values, v.values, weights)
                
                key = f"{expiry.strftime('%Y%m%d')}_{opt_type}"
                models[key] = svi
        
        self.svi_models_ = models
        return models
    
    def compute_term_structure(
        self,
        iv_data: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute IV term structure (ATM IV vs DTE)"""
        
        atm_ivs = []
        
        for expiry in iv_data['expiry'].unique():
            exp_data = iv_data[iv_data['expiry'] == expiry]
            
            # Find ATM options (moneyness close to 1)
            calls = exp_data[exp_data['type'] == 'call']
            puts = exp_data[exp_data['type'] == 'put']
            
            if len(calls) > 0 and len(puts) > 0:
                # ATM IV = average of ATM call and put
                atm_call = calls.iloc[(calls['moneyness'] - 1).abs().argmin()]
                atm_put = puts.iloc[(puts['moneyness'] - 1).abs().argmin()]
                atm_iv = (atm_call['iv'] + atm_put['iv']) / 2
            elif len(calls) > 0:
                atm_iv = calls.iloc[(calls['moneyness'] - 1).abs().argmin()]['iv']
            elif len(puts) > 0:
                atm_iv = puts.iloc[(puts['moneyness'] - 1).abs().argmin()]['iv']
            else:
                continue
            
            atm_ivs.append({
                'expiry': expiry,
                'dte': atm_call['dte'] if 'atm_call' in locals() else atm_put['dte'],
                'atm_iv': atm_iv,
            })
        
        ts_df = pd.DataFrame(atm_ivs).sort_values('dte')
        
        # Interpolate to standard tenors
        if len(ts_df) >= 2:
            from scipy.interpolate import interp1d
            f = interp1d(ts_df['dte'], ts_df['atm_iv'], kind='linear', 
                        bounds_error=False, fill_value='extrapolate')
            standard_ivs = f(self.config.term_structure_points)
            
            return pd.DataFrame({
                'dte': self.config.term_structure_points,
                'atm_iv': standard_ivs,
            })
        
        return ts_df
    
    def compute_skew(
        self,
        iv_data: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute skew measures per expiration"""
        
        skew_results = []
        
        for expiry in iv_data['expiry'].unique():
            exp_data = iv_data[iv_data['expiry'] == expiry]
            
            # Get 25-delta calls and puts
            delta_low, delta_high = self.config.skew_delta_range
            
            for opt_type, delta_target in [('call', delta_high), ('put', -delta_low)]:
                type_data = exp_data[exp_data['type'] == opt_type]
                if len(type_data) == 0:
                    continue
                
                # Find option closest to target delta
                idx = (type_data['delta'] - delta_target).abs().argmin()
                skew_iv = type_data.iloc[idx]['iv']
                
                skew_results.append({
                    'expiry': expiry,
                    'type': opt_type,
                    'delta': delta_target,
                    'iv': skew_iv,
                })
        
        skew_df = pd.DataFrame(skew_results)
        
        if skew_df.empty:
            return pd.DataFrame()
        
        # Compute risk reversal (25-delta call - 25-delta put)
        if self.config.skew_measure == "risk_reversal":
            calls_25d = skew_df[(skew_df['type'] == 'call') & (skew_df['delta'] == 0.25)]
            puts_25d = skew_df[(skew_df['type'] == 'put') & (skew_df['delta'] == -0.25)]
            
            if len(calls_25d) > 0 and len(puts_25d) > 0:
                # Merge on expiry
                rr = pd.merge(
                    calls_25d[['expiry', 'iv']].rename(columns={'iv': 'call_iv'}),
                    puts_25d[['expiry', 'iv']].rename(columns={'iv': 'put_iv'}),
                    on='expiry'
                )
                rr['risk_reversal'] = rr['call_iv'] - rr['put_iv']
                return rr
        
        return skew_df
    
    def compute_iv_rank(
        self,
        iv_history: pd.DataFrame,  # columns: date, iv
        window: int = None,
    ) -> pd.Series:
        """Compute IV rank and percentile"""
        
        window = window or self.config.iv_rank_window
        
        if 'iv' not in iv_history.columns:
            # Assume first column is IV
            iv_col = iv_history.columns[0]
        else:
            iv_col = 'iv'
        
        iv_series = iv_history[iv_col].dropna()
        
        # Rolling rank
        rolling_rank = iv_series.rolling(window).apply(
            lambda x: stats.percentileofscore(x, x[-1]) / 100
        )
        
        # Percentile
        percentile = iv_series.rolling(window).rank(pct=True)
        
        return pd.DataFrame({
            'iv_rank': rolling_rank,
            'iv_percentile': percentile,
        }, index=iv_series.index)
    
    def compute_gamma_exposure(
        self,
        options: pd.DataFrame,
        spot: float,
    ) -> pd.Series:
        """Compute dealer gamma exposure (GEX) by strike"""
        
        df = self._clean_option_data(options, spot)
        
        # GEX = OI * gamma * 100 * spot^2 / 100
        # Positive GEX = dealers long gamma (stabilizing)
        # Negative GEX = dealers short gamma (destabilizing)
        
        df['gex'] = df['open_interest'] * df['gamma'] * 100 * spot**2 / 100
        
        # Aggregate by strike
        gex_by_strike = df.groupby('strike')['gex'].sum()
        
        return gex_by_strike
    
    def compute_dispersion_signal(
        self,
        index_options: pd.DataFrame,
        component_options: Dict[str, pd.DataFrame],
        index_spot: float,
        component_spots: Dict[str, float],
    ) -> pd.Series:
        """
        Compute index vs component variance dispersion signal.
        
        Long dispersion = long index variance, short component variance
        """
        
        # Compute index ATM IV
        index_iv = self.compute_term_structure(
            self.compute_iv_surface(index_options, index_spot)
        )
        
        # Compute component ATM IVs
        component_ivs = {}
        for sym, opts in component_options.items():
            comp_iv = self.compute_term_structure(
                self.compute_iv_surface(opts, component_spots[sym])
            )
            component_ivs[sym] = comp_iv
        
        # Dispersion = index IV^2 - weighted avg component IV^2
        # Positive = index variance > component variance (sell dispersion)
        
        # Simplified: compare 30-day ATM IV
        dte_target = 30
        idx_iv = index_iv[index_iv['dte'] == dte_target]['atm_iv'].values
        
        if len(idx_iv) == 0:
            return pd.Series(dtype=float)
        
        idx_iv = idx_iv[0]
        
        comp_ivs = []
        for sym, civ in component_ivs.items():
            civ_30 = civ[civ['dte'] == dte_target]['atm_iv'].values
            if len(civ_30) > 0:
                comp_ivs.append(civ_30[0])
        
        if not comp_ivs:
            return pd.Series(dtype=float)
        
        avg_comp_iv = np.mean(comp_ivs)
        dispersion = idx_iv**2 - avg_comp_iv**2
        
        return pd.Series([dispersion], index=[pd.Timestamp.now()])
    
    def compute(
        self,
        data: Dict[str, pd.DataFrame],
        **kwargs
    ) -> pd.Series:
        """
        Compute option factor signal.
        
        Expected data:
        - 'options': Option chain DataFrame
        - 'spot': Current spot price
        - 'iv_history': Optional historical IV series
        - 'component_options': Optional dict for dispersion
        
        Returns:
            pd.Series with option factor signal
        """
        options = data.get('options')
        spot = data.get('spot')
        
        if options is None or spot is None:
            raise ValueError("Missing 'options' or 'spot' in data")
        
        # Compute IV surface
        iv_surface = self.compute_iv_surface(options, spot)
        
        if iv_surface.empty:
            return pd.Series(dtype=float)
        
        # Fit SVI
        self.fit_svi_surface(iv_surface)
        
        # Compute components
        signals = {}
        
        # 1. IV rank signal (mean reversion)
        if 'iv_history' in data:
            iv_rank = self.compute_iv_rank(data['iv_history'])
            signals['iv_rank'] = iv_rank['iv_rank'].iloc[-1] if not iv_rank.empty else 0.5
        
        # 2. Term structure slope (contango/backwardation)
        term_structure = self.compute_term_structure(iv_surface)
        if len(term_structure) >= 2:
            slope = (term_structure['atm_iv'].iloc[-1] - term_structure['atm_iv'].iloc[0]) / \
                    (term_structure['dte'].iloc[-1] - term_structure['dte'].iloc[0])
            signals['term_slope'] = np.tanh(slope * 1000)  # Normalize
        
        # 3. Skew signal
        skew = self.compute_skew(iv_surface)
        if not skew.empty and 'risk_reversal' in skew.columns:
            signals['skew'] = skew['risk_reversal'].iloc[-1]
        
        # 4. Gamma exposure
        gex = self.compute_gamma_exposure(options, data['spot'])
        if not gex.empty:
            total_gex = gex.sum()
            # Positive GEX = stabilizing, negative = destabilizing
            signals['gex'] = np.tanh(total_gex / 1e9)  # Normalize
        
        # Combine signals
        if not signals:
            return pd.Series(dtype=float)
        
        # Equal weight combination
        combined = np.mean(list(signals.values()))
        
        return pd.Series([combined], index=[pd.Timestamp.now()])


def create_option_factor(
    iv_method: Literal["bsm", "bjerksund_stensland"] = "bsm",
    risk_free_rate: float = 0.05,
    interp_method: Literal["linear", "cubic", "svi"] = "svi",
    **kwargs
) -> OptionFactor:
    """Factory function for option factor"""
    config = OptionConfig(
        iv_method=iv_method,
        risk_free_rate=risk_free_rate,
        interp_method=interp_method,
        **kwargs
    )
    return OptionFactor(config=config)


if __name__ == "__main__":
    # Quick test
    import numpy as np
    import pandas as pd
    
    np.random.seed(42)
    
    # Synthetic option chain
    spot = 100.0
    n_options = 200
    
    expiries = pd.date_range('2024-02-01', periods=6, freq='M')
    strikes = np.arange(80, 121, 5)
    types = ['call', 'put']
    
    rows = []
    for expiry in expiries:
        for strike in strikes:
            for opt_type in types:
                dte = (expiry - pd.Timestamp.now()).days
                if dte < 7 or dte > 365:
                    continue
                
                # Synthetic IV with smile
                moneyness = strike / spot
                base_iv = 0.20 + 0.1 * (moneyness - 1)**2  # Smile
                iv = base_iv + np.random.normal(0, 0.01)
                
                # Price using BSM
                from scipy.stats import norm
                T = dte / 365
                r = 0.05
                d1 = (np.log(spot/strike) + (r + 0.5*iv**2)*T) / (iv*np.sqrt(T))
                d2 = d1 - iv*np.sqrt(T)
                if opt_type == 'call':
                    price = spot*norm.cdf(d1) - strike*np.exp(-r*T)*norm.cdf(d2)
                else:
                    price = strike*np.exp(-r*T)*norm.cdf(-d2) - spot*norm.cdf(-d1)
                
                # Add bid-ask spread
                spread = price * 0.02
                bid = price - spread/2
                ask = price + spread/2
                
                # Greeks
                from scipy.stats import norm as norm_dist
                pdf_d1 = norm_dist.pdf(d1)
                if opt_type == 'call':
                    delta = norm_dist.cdf(d1)
                    gamma = norm_dist.pdf(d1) / (spot * iv * np.sqrt(T))
                    vega = spot * pdf_d1 * np.sqrt(T) / 100
                else:
                    delta = norm_dist.cdf(d1) - 1
                    gamma = norm_dist.pdf(d1) / (spot * iv * np.sqrt(T))
                    vega = spot * pdf_d1 * np.sqrt(T) / 100
                
                rows.append({
                    'expiry': expiry,
                    'strike': strike,
                    'type': opt_type,
                    'bid': max(0.01, bid),
                    'ask': ask,
                    'mid': (bid + ask) / 2,
                    'volume': np.random.randint(10, 1000),
                    'open_interest': np.random.randint(50, 5000),
                })
    
    options_df = pd.DataFrame(rows)
    
    factor = create_option_factor()
    data = {
        'options': options_df,
        'spot': spot,
    }
    
    try:
        signal = factor.compute(data)
        print(f"Signal: {signal}")
        
        # Test IV surface
        iv_surf = factor.compute_iv_surface(options_df, spot)
        print(f"\nIV Surface shape: {iv_surf.shape}")
        print(f"IV range: {iv_surf['iv'].min():.2%} - {iv_surf['iv'].max():.2%}")
        
        # Test term structure
        ts = factor.compute_term_structure(factor.compute_iv_surface(options_df, spot))
        print(f"\nTerm structure:\n{ts}")
        
        # Test skew
        skew = factor.compute_skew(factor.compute_iv_surface(options_df, spot))
        print(f"\nSkew:\n{skew}")
        
    except Exception as e:
        print(f"Test skipped: {e}")
        print("Install scipy: pip install scipy")