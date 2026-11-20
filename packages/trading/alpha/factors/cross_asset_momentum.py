"""
Cross-Asset Momentum Factor
Equity + Crypto + FX momentum signals with carry overlay
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class CrossAssetConfig:
    """Configuration for cross-asset momentum factor"""
    lookback_windows: List[int] = None  # e.g., [21, 63, 126, 252]
    skip_months: int = 1  # Skip most recent month to avoid reversal
    weight_method: str = "equal"  # equal, volatility, ic, sharpe
    carry_weight: float = 0.3  # Weight for carry component (0-1)
    vol_scaling: bool = True
    vol_target: float = 0.10  # Annual vol target
    min_obs: int = 63
    
    def __post_init__(self):
        if self.lookback_windows is None:
            self.lookback_windows = [21, 63, 126, 252]


class CrossAssetMomentumFactor:
    """
    Cross-Asset Momentum Factor
    
    Combines momentum signals across:
    - Equities (global indices, sectors, factors)
    - Crypto (BTC, ETH, major alts)
    - FX (G10 currencies vs USD)
    
    With optional carry overlay from:
    - Equity dividend yield
    - Crypto funding rates / staking yields
    - FX carry (interest rate differentials)
    """
    
    def __init__(
        self,
        config: Optional = None,
        name: str = "cross_asset_momentum",
    ):
        self.config = config or CrossAssetConfig()
        self.asset_classes = ['equity', 'crypto', 'fx']
    
    def compute(
        self,
        data: Dict[str, pd.DataFrame],
        **kwargs
    ) -> pd.Series:
        """
        Compute cross-asset momentum signal.
        
        Args:
            data: Dict with keys 'equity', 'crypto', 'fx', each containing
                  DataFrame with columns ['close', 'carry'] or just ['close']
                  Index should be datetime
            
        Returns:
            pd.Series with combined momentum signal
        """
        # Validate inputs
        for ac in self.asset_classes:
            if ac not in data:
                logger.warning(f"Missing asset class: {ac}")
        
        # Compute momentum for each asset class
        momentum_signals = {}
        carry_signals = {}
        
        for ac in self.asset_classes:
            if ac in data:
                mom, carry = self._compute_asset_momentum(data[ac], ac)
                momentum_signals[ac] = mom
                if carry is not None:
                    carry_signals[ac] = carry
        
        # Combine across asset classes
        combined_momentum = self._combine_asset_classes(momentum_signals, carry_signals)
        
        return combined_momentum
    
    def _compute_asset_momentum(
        self,
        df: pd.DataFrame,
        asset_class: str,
    ) -> Tuple[pd.Series, Optional[pd.Series]]:
        """Compute momentum and carry for single asset class"""
        
        if 'close' not in df.columns:
            raise ValueError(f"Missing 'close' column for {asset_class}")
        
        close = df['close']
        
        # Handle multi-asset (columns = assets)
        if isinstance(close, pd.DataFrame):
            # Compute momentum for each asset
            asset_momentums = []
            for asset in close.columns:
                asset_mom = self._single_asset_momentum(close[asset])
                asset_momentums.append(asset_mom)
            momentum = pd.concat(asset_momentums, axis=1).mean(axis=1)
        else:
            momentum = self._single_asset_momentum(close)
        
        # Carry signal
        carry = None
        if 'carry' in df.columns:
            carry_data = df['carry']
            if isinstance(carry_data, pd.DataFrame):
                carry = carry_data.mean(axis=1)
            else:
                carry = carry_data
        elif asset_class == 'fx' and 'rate_diff' in df.columns:
            # FX carry from rate differential
            carry = df['rate_diff']
        elif asset_class == 'crypto' and 'funding_rate' in df.columns:
            # Crypto carry from funding rate
            carry = df['funding_rate']
        
        return momentum, carry
    
    def _single_asset_momentum(self, prices: pd.Series) -> pd.Series:
        """Compute momentum for single price series"""
        
        # Skip most recent period to avoid lookback bias
        skip = self.config.skip_months * 21
        
        # Multiple lookback windows
        momentums = []
        for window in self.config.lookback_windows:
            if len(prices) < window + skip:
                continue
            
            # Return over window, skipping recent period
            ret = prices.shift(skip) / prices.shift(skip + window) - 1
            momentums.append(ret)
        
        if not momentums:
            return pd.Series(index=prices.index, dtype=float)
        
        # Combine windows
        mom_df = pd.concat(momentums, axis=1)
        
        if self.config.weight_method == 'equal':
            weights = np.ones(len(momentums)) / len(momentums)
        elif self.config.weight_method == 'volatility':
            # Inverse volatility weighting
            vols = mom_df.rolling(63).std()
            weights = 1 / (vols + 1e-8)
            weights = weights.div(weights.sum(axis=1), axis=0)
        elif self.config.weight_method == 'sharpe':
            # Sharpe-based weighting
            means = mom_df.rolling(126).mean()
            stds = mom_df.rolling(126).std()
            weights = means / (stds + 1e-8)
            weights = weights.clip(lower=0).div(weights.clip(lower=0).sum(axis=1), axis=0)
        else:
            weights = np.ones(len(momentums)) / len(momentums)
        
        if isinstance(weights, pd.DataFrame):
            combined = (mom_df * weights).sum(axis=1)
        else:
            combined = (mom_df * weights).sum(axis=1)
        
        # Volatility scaling
        if self.config.vol_scaling:
            combined = self._vol_scale(combined)
        
        return combined
    
    def _vol_scale(self, signal: pd.Series) -> pd.Series:
        """Scale signal to target volatility"""
        vol = signal.rolling(63).std() * np.sqrt(252)
        scale = self.config.vol_target / (vol + 1e-8)
        scale = scale.clip(0.5, 2.0)  # Cap scaling
        return signal * scale
    
    def _combine_asset_classes(
        self,
        momentum_signals: Dict[str, pd.Series],
        carry_signals: Dict[str, pd.Series],
    ) -> pd.Series:
        """Combine signals across asset classes"""
        
        # Align all signals
        all_signals = {}
        for ac, sig in momentum_signals.items():
            all_signals[f'{ac}_momentum'] = sig
        
        for ac, sig in carry_signals.items():
            all_signals[f'{ac}_carry'] = sig
        
        if not all_signals:
            return pd.Series(dtype=float)
        
        # Create combined DataFrame
        sig_df = pd.concat(all_signals, axis=1)
        
        # Forward fill and drop NaN
        sig_df = sig_df.ffill().dropna()
        
        if sig_df.empty:
            return pd.Series(dtype=float)
        
        # Separate momentum and carry
        mom_cols = [c for c in sig_df.columns if c.endswith('_momentum')]
        carry_cols = [c for c in sig_df.columns if c.endswith('_carry')]
        
        # Combine momentum signals
        if mom_cols:
            momentum_combined = sig_df[mom_cols].mean(axis=1)
        else:
            return pd.Series(index=sig_df.index, dtype=float)
        
        # Add carry overlay
        if carry_cols and self.config.carry_weight > 0:
            carry_combined = sig_df[carry_cols].mean(axis=1)
            # Normalize carry to similar scale as momentum
            carry_scaled = carry_combined * (
                momentum_combined.rolling(252).std() / (carry_combined.rolling(252).std() + 1e-8)
            )
            combined = (1 - self.config.carry_weight) * momentum_combined + \
                       self.config.carry_weight * carry_scaled
        else:
            combined = momentum_combined
        
        # Final volatility scaling
        if self.config.vol_scaling:
            combined = self._vol_scale(combined)
        
        return combined


class MultiHorizonCrossAssetMomentum(CrossAssetMomentumFactor):
    """
    Multi-horizon cross-asset momentum with regime-adaptive windows.
    Uses regime detection to adjust lookback windows dynamically.
    """
    
    def __init__(
        self,
        config: Optional[CrossAssetConfig] = None,
        regime_factor: Optional = None,
    ):
        super().__init__(config, name="multi_horizon_cross_asset_momentum")
        self.regime_factor = regime_factor
    
    def compute(self, data: Dict[str, pd.DataFrame], **kwargs) -> pd.Series:
        """Compute with regime-adaptive windows"""
        
        # Get regime if available
        if self.regime_factor and 'returns' in data:
            regime = self.regime_factor.compute({'returns': data['returns']})
            # Adjust windows based on regime
            if hasattr(regime, 'regime'):
                self._adjust_windows_for_regime(regime)
        
        return super().compute(data, **kwargs)
    
    def _adjust_windows_for_regime(self, regime):
        """Adjust lookback windows based on market regime"""
        if regime.regime.value == 'volatile':
            # Shorter windows in volatile regimes
            self.config.lookback_windows = [10, 21, 42]
        elif regime.regime.value in ['trend_up', 'trend_down']:
            # Longer windows in trending regimes
            self.config.lookback_windows = [42, 84, 168, 252]
        else:
            # Default
            self.config.lookback_windows = [21, 63, 126, 252]


def create_cross_asset_momentum(
    lookback_windows: List[int] = None,
    carry_weight: float = 0.3,
    vol_target: float = 0.10,
    **kwargs
) -> CrossAssetMomentumFactor:
    """Factory function for cross-asset momentum factor"""
    config = CrossAssetConfig(
        lookback_windows=lookback_windows,
        carry_weight=carry_weight,
        vol_target=vol_target,
        **kwargs
    )
    return CrossAssetMomentumFactor(config=config)


if __name__ == "__main__":
    # Quick test
    import numpy as np
    import pandas as pd
    
    np.random.seed(42)
    n = 500
    dates = pd.date_range('2020-01-01', periods=n, freq='D')
    
    # Synthetic multi-asset data
    equity_data = pd.DataFrame({
        'close': 100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))),
    }, index=dates)
    equity_data['carry'] = 0.02 / 252  # 2% dividend yield
    
    crypto_data = pd.DataFrame({
        'close': 30000 * np.exp(np.cumsum(np.random.normal(0.0002, 0.03, n))),
    }, index=dates)
    crypto_data['funding_rate'] = np.random.normal(0.0001, 0.001, n)
    
    fx_data = pd.DataFrame({
        'close': 1.1 * np.exp(np.cumsum(np.random.normal(0.0000, 0.005, n))),
    }, index=dates)
    fx_data['rate_diff'] = 0.015 / 252  # 1.5% rate differential
    
    data = {
        'equity': equity_data,
        'crypto': crypto_data,
        'fx': fx_data,
    }
    
    factor = create_cross_asset_momentum()
    signal = factor.compute(data)
    
    print(f"Signal shape: {signal.shape}")
    print(f"Signal stats: mean={signal.mean():.6f}, std={signal.std():.6f}")
    print(f"Last 5 values:\n{signal.tail()}")