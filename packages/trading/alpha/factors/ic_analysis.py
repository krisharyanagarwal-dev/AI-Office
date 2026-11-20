"""
Factor Ranking and IC (Information Coefficient) Analysis Module
Provides comprehensive factor evaluation: IC mean, IR, decay, turnover, crowding, sector neutrality
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union, Literal
from dataclasses import dataclass, field
from enum import Enum
import logging
from scipy import stats
from scipy.stats import spearmanr, pearsonr

logger = logging.getLogger(__name__)


class ICMethod(Enum):
    SPEARMAN = "spearman"  # Rank correlation (default, robust)
    PEARSON = "pearson"    # Linear correlation


@dataclass
class ICResult:
    """Result of IC analysis for a single factor"""
    factor_name: str
    ic_mean: float
    ic_std: float
    ic_ir: float  # Information Ratio = mean / std
    ic_t_stat: float
    ic_p_value: float
    positive_ic_ratio: float  # Fraction of periods with positive IC
    max_drawdown: float
    decay: Dict[int, float]  # IC at different horizons (1d, 5d, 10d, 20d)
    turnover: float
    sector_neutral_ic: Optional[float] = None
    sector_neutral_ir: Optional[float] = None
    n_observations: int = 0


@dataclass
class FactorRanking:
    """Ranked factors with scores"""
    factor_name: str
    composite_score: float
    ic_rank: int
    ir_rank: int
    stability_rank: int
    turnover_rank: int
    crowding_rank: Optional[int] = None
    details: ICResult = None


class ICAnalyzer:
    """
    Comprehensive Information Coefficient analysis for factor evaluation.
    
    Computes:
    - IC mean, std, IR (Information Ratio)
    - IC decay across horizons
    - Factor turnover
    - Sector-neutral IC
    - Positive IC ratio
    - IC drawdown
    """
    
    def __init__(
        self,
        method: ICMethod = ICMethod.SPEARMAN,
        min_periods: int = 20,
        horizons: List[int] = None,
    ):
        self.method = method
        self.min_periods = min_periods
        self.horizons = horizons or [1, 5, 10, 20]
    
    def compute_ic(
        self,
        factor: pd.Series,
        forward_returns: pd.Series,
        method: ICMethod = None,
    ) -> Tuple[float, float]:
        """Compute IC (correlation) between factor and forward returns"""
        method = method or self.method
        
        # Align data
        aligned = pd.concat([factor, forward_returns], axis=1, join='inner').dropna()
        
        if len(aligned) < self.min_periods:
            return np.nan, np.nan
        
        f = aligned.iloc[:, 0]
        r = aligned.iloc[:, 1]
        
        if method == ICMethod.SPEARMAN:
            ic, p_val = spearmanr(f, r, nan_policy='omit')
        else:
            ic, p_val = pearsonr(f, r)
        
        return float(ic) if not np.isnan(ic) else 0.0, float(p_val) if not np.isnan(p_val) else 1.0
    
    def compute_ic_series(
        self,
        factor: pd.DataFrame,  # Multi-factor: columns=factors, index=dates
        forward_returns: pd.DataFrame,  # Same shape
        method: ICMethod = None,
    ) -> pd.DataFrame:
        """Compute rolling IC series for each factor"""
        method = method or self.method
        factors = factor.columns if isinstance(factor, pd.DataFrame) else [factor.name]
        
        ic_series = {}
        for fname in factors:
            f = factor[fname] if isinstance(factor, pd.DataFrame) else factor
            r = forward_returns[fname] if isinstance(forward_returns, pd.DataFrame) else forward_returns
            
            # Rolling IC
            rolling_ic = f.rolling(window=self.min_periods).apply(
                lambda x: self.compute_ic(x, r.loc[x.index])[0] if len(x) == self.min_periods else np.nan,
                raw=False
            )
            ic_series[fname] = rolling_ic
        
        return pd.DataFrame(ic_series, index=factor.index)
    
    def compute_ic_decay(
        self,
        factor: pd.Series,
        returns: pd.DataFrame,  # Multi-horizon returns: columns=horizons
    ) -> Dict[int, float]:
        """Compute IC at different forward horizons"""
        decay = {}
        for h in self.horizons:
            if h in returns.columns:
                ic, _ = self.compute_ic(factor, returns[h])
                decay[h] = ic
            else:
                decay[h] = np.nan
        return decay
    
    def compute_turnover(
        self,
        factor: pd.Series,
        window: int = 20,
    ) -> float:
        """
        Compute factor turnover (average rank change per period).
        Lower turnover = more stable factor.
        """
        ranks = factor.rank(ascending=False, method='first')
        rank_changes = ranks.diff().abs()
        turnover = rank_changes.rolling(window).mean().mean()
        return float(turnover) if not np.isnan(turnover) else np.inf
    
    def compute_sector_neutral_ic(
        self,
        factor: pd.Series,
        forward_returns: pd.Series,
        sectors: pd.Series,  # Sector mapping for each asset
        method: ICMethod = None,
    ) -> Tuple[float, float]:
        """
        Compute sector-neutral IC by removing sector mean from factor and returns.
        """
        method = method or self.method
        
        # Align
        df = pd.concat([factor, forward_returns, sectors], axis=1, join='inner').dropna()
        df.columns = ['factor', 'return', 'sector']
        
        if len(df) < self.min_periods:
            return np.nan, np.nan
        
        # Demean by sector
        df['factor_sn'] = df.groupby('sector')['factor'].transform(lambda x: x - x.mean())
        df['return_sn'] = df.groupby('sector')['return'].transform(lambda x: x - x.mean())
        
        if method == ICMethod.SPEARMAN:
            ic, p_val = spearmanr(df['factor_sn'], df['return_sn'], nan_policy='omit')
        else:
            ic, p_val = pearsonr(df['factor_sn'], df['return_sn'])
        
        return float(ic) if not np.isnan(ic) else 0.0, float(p_val) if not np.isnan(p_val) else 1.0
    
    def analyze_factor(
        self,
        factor_name: str,
        factor: pd.Series,
        forward_returns: pd.DataFrame,  # Columns = horizons
        sectors: Optional[pd.Series] = None,
        benchmark_factor: Optional[pd.Series] = None,
    ) -> ICResult:
        """
        Comprehensive factor analysis.
        
        Args:
            factor_name: Name of the factor
            factor: Factor values (index=dates, values=factor scores)
            forward_returns: Forward returns at different horizons (columns=horizons)
            sectors: Optional sector mapping for sector-neutral analysis
            benchmark_factor: Optional benchmark for relative analysis
        
        Returns:
            ICResult with all metrics
        """
        # Primary horizon (1d)
        primary_horizon = min(self.horizons)
        if primary_horizon not in forward_returns.columns:
            primary_horizon = forward_returns.columns[0]
        
        primary_returns = forward_returns[primary_horizon]
        
        # Align
        aligned = pd.concat([factor, primary_returns], axis=1, join='inner').dropna()
        
        if len(aligned) < self.min_periods:
            return ICResult(
                factor_name=factor_name,
                ic_mean=np.nan, ic_std=np.nan, ic_ir=np.nan,
                ic_t_stat=np.nan, ic_p_value=np.nan,
                positive_ic_ratio=np.nan, max_drawdown=np.nan,
                decay={}, turnover=np.nan, n_observations=0
            )
        
        f = aligned.iloc[:, 0]
        r = aligned.iloc[:, 1]
        
        # Rolling IC series
        ic_series = f.rolling(self.min_periods).apply(
            lambda x: self.compute_ic(x, r.loc[x.index])[0] if len(x) == self.min_periods else np.nan,
            raw=False
        ).dropna()
        
        # Basic stats
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0.0
        ic_t_stat = ic_mean / (ic_std / np.sqrt(len(ic_series))) if ic_std > 0 else 0.0
        
        # T-test p-value
        _, ic_p_value = stats.ttest_1samp(ic_series, 0)
        
        # Positive IC ratio
        positive_ic_ratio = (ic_series > 0).mean()
        
        # Max drawdown of cumulative IC
        cum_ic = ic_series.cumsum()
        running_max = cum_ic.expanding().max()
        drawdown = (cum_ic - running_max).min()
        
        # IC decay
        decay = self.compute_ic_decay(factor, forward_returns)
        
        # Turnover
        turnover = self.compute_turnover(factor)
        
        # Sector-neutral IC
        sector_neutral_ic = None
        sector_neutral_ir = None
        if sectors is not None:
            sn_ic, sn_p = self.compute_sector_neutral_ic(factor, primary_returns, sectors)
            if not np.isnan(sn_ic):
                sector_neutral_ic = sn_ic
                # Need rolling sector-neutral for IR - simplified
                sector_neutral_ir = sn_ic / ic_std if ic_std > 0 else 0.0
        
        return ICResult(
            factor_name=factor_name,
            ic_mean=float(ic_mean),
            ic_std=float(ic_std),
            ic_ir=float(ic_ir),
            ic_t_stat=float(ic_t_stat),
            ic_p_value=float(ic_p_value),
            positive_ic_ratio=float(positive_ic_ratio),
            max_drawdown=float(drawdown),
            decay=decay,
            turnover=float(turnover),
            sector_neutral_ic=sector_neutral_ic,
            sector_neutral_ir=sector_neutral_ir,
            n_observations=len(aligned)
        )


class FactorRanker:
    """
    Rank factors by composite score combining multiple metrics.
    """
    
    def __init__(
        self,
        ic_weight: float = 0.4,
        ir_weight: float = 0.3,
        stability_weight: float = 0.2,
        turnover_weight: float = 0.1,
        crowding_weight: float = 0.0,
    ):
        # Weights should sum to 1
        total = ic_weight + ir_weight + stability_weight + turnover_weight + crowding_weight
        self.weights = {
            'ic': ic_weight / total,
            'ir': ir_weight / total,
            'stability': stability_weight / total,
            'turnover': turnover_weight / total,
            'crowding': crowding_weight / total,
        }
    
    def rank_factors(
        self,
        ic_results: List[ICResult],
        crowding_scores: Optional[Dict[str, float]] = None,
    ) -> List[FactorRanking]:
        """
        Rank factors by composite score.
        
        Args:
            ic_results: List of ICResult from ICAnalyzer
            crowding_scores: Optional dict factor_name -> crowding score (lower = less crowded)
        
        Returns:
            List of FactorRanking sorted by composite score (highest first)
        """
        if not ic_results:
            return []
        
        df = pd.DataFrame([
            {
                'factor': r.factor_name,
                'ic_mean': r.ic_mean,
                'ic_ir': r.ic_ir,
                'ic_std': r.ic_std,
                'turnover': r.turnover,
                'positive_ic_ratio': r.positive_ic_ratio,
                'max_drawdown': r.max_drawdown,
                'n_obs': r.n_observations,
            }
            for r in ic_results
        ])
        
        # Compute ranks (higher is better for IC, IR, positive_ratio, lower for turnover, drawdown)
        df['ic_rank'] = df['ic_mean'].rank(ascending=False, method='min').astype(int)
        df['ir_rank'] = df['ic_ir'].rank(ascending=False, method='min').astype(int)
        
        # Stability = 1 / (IC std * sqrt(n)) - higher is more stable
        df['stability'] = 1 / (df['ic_std'] * np.sqrt(df['n_obs']) + 1e-6)
        df['stability_rank'] = df['stability'].rank(ascending=False, method='min').astype(int)
        
        df['turnover_rank'] = df['turnover'].rank(ascending=True, method='min').astype(int)
        
        # Crowding rank
        if crowding_scores:
            df['crowding'] = df['factor'].map(crowding_scores).fillna(df['turnover'].median())
            df['crowding_rank'] = df['crowding'].rank(ascending=True, method='min').astype(int)
        else:
            df['crowding_rank'] = 1
        
        # Composite score
        w = self.weights
        df['composite_score'] = (
            w['ic'] * (1 - (df['ic_rank'] - 1) / len(df)) +
            w['ir'] * (1 - (df['ir_rank'] - 1) / len(df)) +
            w['stability'] * (1 - (df['stability_rank'] - 1) / len(df)) +
            w['turnover'] * (1 - (df['turnover_rank'] - 1) / len(df)) +
            w['crowding'] * (1 - (df['crowding_rank'] - 1) / len(df))
        )
        
        # Sort by composite score
        df = df.sort_values('composite_score', ascending=False).reset_index(drop=True)
        
        # Build rankings
        rankings = []
        for _, row in df.iterrows():
            # Find matching ICResult
            ic_result = next(r for r in ic_results if r.factor_name == row['factor'])
            rankings.append(FactorRanking(
                factor_name=row['factor'],
                composite_score=float(row['composite_score']),
                ic_rank=int(row['ic_rank']),
                ir_rank=int(row['ir_rank']),
                stability_rank=int(row['stability_rank']),
                turnover_rank=int(row['turnover_rank']),
                crowding_rank=int(row['crowding_rank']),
                details=ic_result
            ))
        
        return rankings


def compute_ic(
    factor: pd.Series,
    forward_returns: pd.Series,
    method: ICMethod = ICMethod.SPEARMAN,
) -> Tuple[float, float]:
    """Convenience function for single IC computation"""
    analyzer = ICAnalyzer(method=method)
    return analyzer.compute_ic(factor, forward_returns, method)


def rank_factors(
    ic_results: List[ICResult],
    crowding_scores: Optional[Dict[str, float]] = None,
    **weights
) -> List[FactorRanking]:
    """Convenience function for factor ranking"""
    ranker = FactorRanker(**weights)
    return ranker.rank_factors(ic_results, crowding_scores)


if __name__ == "__main__":
    # Quick test
    np.random.seed(42)
    n = 500
    dates = pd.date_range('2020-01-01', periods=n, freq='D')
    
    # Create synthetic factors with different IC properties
    factor1 = pd.Series(np.random.normal(0, 1, n), index=dates)  # Pure noise
    factor2 = pd.Series(np.random.normal(0, 1, n) + 0.5 * np.random.normal(0, 1, n).cumsum(), index=dates)  # Some signal
    factor3 = pd.Series(np.arange(n) % 10, index=dates, dtype=float)  # Seasonal
    
    # Forward returns (factor2 has some predictive power)
    returns_1d = pd.Series(np.random.normal(0, 0.01, n) + 0.1 * factor2, index=dates)
    returns_5d = returns_1d.rolling(5).sum()
    returns_10d = returns_1d.rolling(10).sum()
    
    forward_returns = pd.DataFrame({
        1: returns_1d,
        5: returns_5d,
        10: returns_10d,
    })
    
    analyzer = ICAnalyzer()
    
    for name, factor in [('noise', factor1), ('signal', factor2), ('seasonal', factor3)]:
        result = analyzer.analyze_factor(name, factor, forward_returns)
        print(f"{name}: IC={result.ic_mean:.4f}, IR={result.ic_ir:.4f}, "
              f"Pos%={result.positive_ic_ratio:.2%}, Turnover={result.turnover:.2f}")