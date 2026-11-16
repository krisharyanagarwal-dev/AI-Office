"""
Performance Metrics
Information coefficient, Sharpe ratio, drawdown, and other trading metrics
"""
import pandas as pd
import numpy as np
from typing import Union, Optional
from scipy import stats


def calculate_ic(
    predictions: Union[pd.Series, np.ndarray],
    actual_returns: Union[pd.Series, np.ndarray],
    method: str = 'pearson'
) -> float:
    """
    Calculate Information Coefficient (IC)
    
    Parameters:
    -----------
    predictions : array-like
        Model predictions
    actual_returns : array-like
        Actual forward returns
    method : str
        Correlation method ('pearson', 'spearman')
        
    Returns:
    --------
    float
        Information coefficient
    """
    # Convert to pandas Series if needed
    if isinstance(predictions, np.ndarray):
        predictions = pd.Series(predictions)
    if isinstance(actual_returns, np.ndarray):
        actual_returns = pd.Series(actual_returns)
    
    # Align indices
    df = pd.DataFrame({'pred': predictions, 'actual': actual_returns}).dropna()
    
    if len(df) < 2:
        return 0.0
    
    if method == 'pearson':
        ic = df['pred'].corr(df['actual'], method='pearson')
    elif method == 'spearman':
        ic = df['pred'].corr(df['actual'], method='spearman')
    else:
        raise ValueError("Method must be 'pearson' or 'spearman'")
    
    return ic if not np.isnan(ic) else 0.0


def calculate_rank_ic(
    predictions: Union[pd.Series, np.ndarray],
    actual_returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate Rank Information Coefficient (Rank IC)
    
    Parameters:
    -----------
    predictions : array-like
        Model predictions
    actual_returns : array-like
        Actual forward returns
        
    Returns:
    --------
    float
        Rank information coefficient (Spearman correlation)
    """
    return calculate_ic(predictions, actual_returns, method='spearman')


def calculate_sharpe(
    returns: Union[pd.Series, np.ndarray],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252
) -> float:
    """
    Calculate Sharpe ratio
    
    Parameters:
    -----------
    returns : array-like
        Return series
    risk_free_rate : float
        Risk-free rate (annualized)
    periods_per_year : int
        Number of periods in a year (252 for daily, 12 for monthly, etc.)
        
    Returns:
    --------
    float
        Sharpe ratio
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate excess returns
    excess_returns = returns - risk_free_rate / periods_per_year
    
    # Calculate Sharpe ratio
    if excess_returns.std() == 0:
        return 0.0
    
    sharpe = np.sqrt(periods_per_year) * excess_returns.mean() / excess_returns.std()
    return sharpe


def calculate_sortino(
    returns: Union[pd.Series, np.ndarray],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
    target_return: float = 0.0
) -> float:
    """
    Calculate Sortino ratio
    
    Parameters:
    -----------
    returns : array-like
        Return series
    risk_free_rate : float
        Risk-free rate (annualized)
    periods_per_year : int
        Number of periods in a year
    target_return : float
        Target return (default 0 for downside deviation)
        
    Returns:
    --------
    float
        Sortino ratio
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate excess returns
    excess_returns = returns - risk_free_rate / periods_per_year
    
    # Calculate downside deviation
    downside_returns = excess_returns[excess_returns < target_return]
    if len(downside_returns) == 0:
        return np.inf if excess_returns.mean() > 0 else 0.0
    
    downside_deviation = np.sqrt(np.mean(downside_returns**2))
    
    if downside_deviation == 0:
        return 0.0
    
    sortino = np.sqrt(periods_per_year) * excess_returns.mean() / downside_deviation
    return sortino


def calculate_calmar(
    returns: Union[pd.Series, np.ndarray],
    periods_per_year: int = 252
) -> float:
    """
    Calculate Calmar ratio (annualized return / max drawdown)
    
    Parameters:
    -----------
    returns : array-like
        Return series
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    float
        Calmar ratio
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate annualized return
    total_return = (1 + returns).prod() - 1
    n_periods = len(returns)
    annualized_return = (1 + total_return) ** (periods_per_year / n_periods) - 1
    
    # Calculate max drawdown
    max_dd = calculate_max_drawdown(returns)
    
    if max_dd == 0:
        return np.inf if annualized_return > 0 else 0.0
    
    calmar = annualized_return / abs(max_dd)
    return calmar


def calculate_max_drawdown(
    returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate maximum drawdown
    
    Parameters:
    -----------
    returns : array-like
        Return series
        
    Returns:
    --------
    float
        Maximum drawdown (negative value)
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate cumulative returns
    cum_returns = (1 + returns).cumprod()
    
    # Calculate running maximum
    running_max = cum_returns.expanding().max()
    
    # Calculate drawdown
    drawdown = (cum_returns - running_max) / running_max
    
    # Return maximum drawdown
    max_dd = drawdown.min()
    return max_dd


def calculate_hit_rate(
    predictions: Union[pd.Series, np.ndarray],
    actual_returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate hit rate (percentage of correct directional predictions)
    
    Parameters:
    -----------
    predictions : array-like
        Model predictions
    actual_returns : array-like
        Actual forward returns
        
    Returns:
    --------
    float
        Hit rate (between 0 and 1)
    """
    # Convert to pandas Series if needed
    if isinstance(predictions, np.ndarray):
        predictions = pd.Series(predictions)
    if isinstance(actual_returns, np.ndarray):
        actual_returns = pd.Series(actual_returns)
    
    # Align indices
    df = pd.DataFrame({'pred': predictions, 'actual': actual_returns}).dropna()
    
    if len(df) == 0:
        return 0.0
    
    # Calculate hit rate
    correct_directions = (df['pred'] * df['actual']) > 0
    hit_rate = correct_directions.mean()
    
    return hit_rate


def calculate_turnover(
    weights: Union[pd.DataFrame, np.ndarray]
) -> float:
    """
    Calculate average turnover
    
    Parameters:
    -----------
    weights : array-like
        Weight matrix (assets x time) or weight vector over time
        
    Returns:
    --------
    float
        Average turnover
    """
    # Convert to pandas DataFrame if needed
    if isinstance(weights, np.ndarray):
        weights = pd.DataFrame(weights)
    
    # Calculate turnover (sum of absolute weight changes)
    weight_changes = weights.diff().abs()
    turnover = weight_changes.sum().sum() / 2  # Divide by 2 because each trade involves buy and sell
    
    # Average turnover per period
    avg_turnover = turnover / len(weights)
    
    return avg_turnover


def calculate_win_loss_ratio(
    returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate win/loss ratio (average win / average loss)
    
    Parameters:
    -----------
    returns : array-like
        Return series
        
    Returns:
    --------
    float
        Win/loss ratio
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Separate wins and losses
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    
    if len(losses) == 0:
        return np.inf if len(wins) > 0 else 0.0
    if len(wins) == 0:
        return 0.0
    
    avg_win = wins.mean()
    avg_loss = abs(losses.mean())  # Make positive
    
    if avg_loss == 0:
        return np.inf
    
    win_loss_ratio = avg_win / avg_loss
    return win_loss_ratio


def calculate_profit_factor(
    returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate profit factor (gross profit / gross loss)
    
    Parameters:
    -----------
    returns : array-like
        Return series
        
    Returns:
    --------
    float
        Profit factor
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate gross profit and gross loss
    gross_profit = returns[returns > 0].sum()
    gross_loss = abs(returns[returns < 0].sum())  # Make positive
    
    if gross_loss == 0:
        return np.inf if gross_profit > 0 else 0.0
    
    profit_factor = gross_profit / gross_loss
    return profit_factor


def calculate_information_ratio(
    returns: Union[pd.Series, np.ndarray],
    benchmark_returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate information ratio (active return / tracking error)
    
    Parameters:
    -----------
    returns : array-like
        Strategy return series
    benchmark_returns : array-like
        Benchmark return series
        
    Returns:
    --------
    float
        Information ratio
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    if isinstance(benchmark_returns, np.ndarray):
        benchmark_returns = pd.Series(benchmark_returns)
    
    # Align indices
    df = pd.DataFrame({'strategy': returns, 'benchmark': benchmark_returns}).dropna()
    
    if len(df) < 2:
        return 0.0
    
    # Calculate active returns
    active_returns = df['strategy'] - df['benchmark']
    
    # Calculate information ratio
    if active_returns.std() == 0:
        return np.inf if active_returns.mean() > 0 else 0.0
    
    information_ratio = active_returns.mean() / active_returns.std()
    return information_ratio


def calculate_kappa(
    returns: Union[pd.Series, np.ndarray],
    threshold: float = 0.0
) -> float:
    """
    Calculate Kappa (ratio of upside to downside variance)
    
    Parameters:
    -----------
    returns : array-like
        Return series
    threshold : float
        Return threshold (default 0)
        
    Returns:
    --------
    float
        Kappa ratio
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate upside and downside variance
    upside_returns = returns[returns > threshold]
    downside_returns = returns[returns < threshold]
    
    if len(downside_returns) == 0:
        return np.inf if len(upside_returns) > 0 else 0.0
    if len(upside_returns) == 0:
        return 0.0
    
    upside_variance = upside_returns.var()
    downside_variance = downside_returns.var()
    
    if downside_variance == 0:
        return np.inf
    
    kappa = upside_variance / downside_variance
    return kappa


def calculate_tail_ratio(
    returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate tail ratio (95th percentile / 5th percentile of returns)
    
    Parameters:
    -----------
    returns : array-like
        Return series
        
    Returns:
    --------
    float
        Tail ratio
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate percentiles
    percentile_95 = np.percentile(returns, 95)
    percentile_05 = np.percentile(returns, 5)
    
    if percentile_05 == 0:
        return np.inf if percentile_95 > 0 else 0.0
    
    tail_ratio = abs(percentile_95 / percentile_05)
    return tail_ratio


def calculate_recovery_factor(
    returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate recovery factor (net profit / max drawdown)
    
    Parameters:
    -----------
    returns : array-like
        Return series
        
    Returns:
    --------
    float
        Recovery factor
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate net profit
    net_profit = (1 + returns).prod() - 1
    
    # Calculate max drawdown
    max_dd = calculate_max_drawdown(returns)
    
    if max_dd == 0:
        return np.inf if net_profit > 0 else 0.0
    
    recovery_factor = net_profit / abs(max_dd)
    return recovery_factor


def calculate_ulcer_index(
    returns: Union[pd.Series, np.ndarray]
) -> float:
    """
    Calculate Ulcer Index (measure of downside volatility)
    
    Parameters:
    -----------
    returns : array-like
        Return series
        
    Returns:
    --------
    float
        Ulcer Index
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate cumulative returns
    cum_returns = (1 + returns).cumprod()
    
    # Calculate running maximum
    running_max = cum_returns.expanding().max()
    
    # Calculate percentage drawdown
    drawdown_pct = 100 * (cum_returns - running_max) / running_max
    
    # Calculate Ulcer Index
    ulcer_index = np.sqrt(np.mean(drawdown_pct**2))
    
    return ulcer_index


def calculate_martin_ratio(
    returns: Union[pd.Series, np.ndarray],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252
) -> float:
    """
    Calculate Martin ratio (Ulcer Index equivalent of Sharpe ratio)
    
    Parameters:
    -----------
    returns : array-like
        Return series
    risk_free_rate : float
        Risk-free rate (annualized)
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    float
        Martin ratio
    """
    # Convert to pandas Series if needed
    if isinstance(returns, np.ndarray):
        returns = pd.Series(returns)
    
    # Calculate annualized return
    total_return = (1 + returns).prod() - 1
    n_periods = len(returns)
    annualized_return = (1 + total_return) ** (periods_per_year / n_periods) - 1
    
    # Calculate excess return
    excess_return = annualized_return - risk_free_rate
    
    # Calculate Ulcer Index
    ulcer_index = calculate_ulcer_index(returns)
    
    if ulcer_index == 0:
        return np.inf if excess_return > 0 else 0.0
    
    martin_ratio = excess_return / ulcer_index
    return martin_ratio

def calculate_profit_attribution_by_factor(
    factor_returns: pd.DataFrame,
    factor_weights: pd.DataFrame,
    periods_per_year: int = 252
) -> pd.DataFrame:
    """
    Calculate profit attribution by factor (Brinson-style)
    
    Parameters:
    -----------
    factor_returns : DataFrame
        Factor returns (assets x factors) for each period
    factor_weights : DataFrame
        Factor weights (assets x factors) for each period
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    DataFrame
        Attribution table with columns: factor, total_return, attribution, contribution_pct
    """
    # Align indices
    common_index = factor_returns.index.intersection(factor_weights.index)
    factor_returns = factor_returns.loc[common_index]
    factor_weights = factor_weights.loc[common_index]
    
    if len(common_index) == 0:
        return pd.DataFrame(columns=['factor', 'total_return', 'attribution', 'contribution_pct'])
    
    # Calculate portfolio returns for each period
    # Portfolio return = sum(factor_return * factor_weight) across factors
    portfolio_returns = (factor_returns * factor_weights).sum(axis=1)
    
    # Calculate total return
    total_return = (1 + portfolio_returns).prod() - 1
    
    # Calculate attribution for each factor
    attribution_data = []
    
    for factor in factor_returns.columns:
        # Factor return series
        factor_ret = factor_returns[factor]
        
        # Average factor weight over time
        avg_weight = factor_weights[factor].mean()
        
        # Factor contribution to return (Brinson model)
        # Contribution = average weight * factor return
        factor_contribution = (avg_weight * factor_ret.mean()) * len(factor_returns)
        
        # Alternative: geometric linking (more accurate)
        # Calculate what return would be if only this factor existed
        factor_only_returns = factor_returns[factor] * factor_weights[factor]
        factor_total_return = (1 + factor_only_returns).prod() - 1
        
        attribution_data.append({
            'factor': factor,
            'total_return': factor_total_return,
            'attribution': factor_contribution,
            'contribution_pct': (factor_total_return / total_return * 100) if total_return != 0 else 0
        })
    
    attribution_df = pd.DataFrame(attribution_data)
    return attribution_df


def calculate_profit_attribution_by_regime(
    returns: pd.Series,
    regimes: pd.Series,
    periods_per_year: int = 252
) -> pd.DataFrame:
    """
    Calculate profit attribution by market regime
    
    Parameters:
    -----------
    returns : Series
        Period returns
    regimes : Series
        Regime labels for each period (should match returns index)
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    DataFrame
        Attribution table with columns: regime, total_return, annualized_return, contribution_pct
    """
    # Align indices
    common_index = returns.index.intersection(regimes.index)
    returns = returns.loc[common_index]
    regimes = regimes.loc[common_index]
    
    if len(common_index) == 0:
        return pd.DataFrame(columns=['regime', 'total_return', 'annualized_return', 'contribution_pct'])
    
    # Calculate total return
    total_return = (1 + returns).prod() - 1
    
    # Calculate attribution for each regime
    attribution_data = []
    
    for regime in regimes.unique():
        regime_returns = returns[regimes == regime]
        
        if len(regime_returns) > 0:
            regime_total_return = (1 + regime_returns).prod() - 1
            regime_annualized = (1 + regime_total_return) ** (periods_per_year / len(regime_returns)) - 1
            
            attribution_data.append({
                'regime': regime,
                'total_return': regime_total_return,
                'annualized_return': regime_annualized,
                'contribution_pct': (regime_total_return / total_return * 100) if total_return != 0 else 0
            })
    
    attribution_df = pd.DataFrame(attribution_data)
    return attribution_df


def calculate_profit_attribution_by_model(
    model_predictions: Dict[str, pd.Series],
    actual_returns: pd.Series,
    model_weights: Dict[str, float],
    periods_per_year: int = 252
) -> pd.DataFrame:
    """
    Calculate profit attribution by model
    
    Parameters:
    -----------
    model_predictions : dict
        Dictionary of model predictions (model_name -> predictions series)
    actual_returns : Series
        Actual forward returns
    model_weights : dict
        Dictionary of model weights (model_name -> weight)
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    DataFrame
        Attribution table with columns: model, weight, ic, attribution, contribution_pct
    """
    # Align all series to common index
    common_index = actual_returns.index
    for model_name, preds in model_predictions.items():
        common_index = common_index.intersection(preds.index)
    
    if len(common_index) == 0:
        return pd.DataFrame(columns=['model', 'weight', 'ic', 'attribution', 'contribution_pct'])
    
    actual_returns_aligned = actual_returns.loc[common_index]
    
    # Calculate IC for each model
    model_ics = {}
    for model_name, preds in model_predictions.items():
        preds_aligned = preds.loc[common_index]
        if len(preds_aligned) > 1:
            ic = calculate_ic(preds_aligned, actual_returns_aligned)
        else:
            ic = 0.0
        model_ics[model_name] = ic
    
    # Calculate attribution (IC * weight)
    total_weighted_ic = sum(model_ics[model] * model_weights.get(model, 0) for model in model_ics)
    
    attribution_data = []
    for model_name in model_ics:
        weight = model_weights.get(model_name, 0)
        ic = model_ics[model_name]
        attribution = ic * weight
        
        attribution_data.append({
            'model': model_name,
            'weight': weight,
            'ic': ic,
            'attribution': attribution,
            'contribution_pct': (attribution / total_weighted_ic * 100) if total_weighted_ic != 0 else 0
        })
    
    attribution_df = pd.DataFrame(attribution_data)
    return attribution_df


def calculate_factor_half_life(
    factor_returns: pd.Series,
    periods_per_year: int = 252
) -> float:
    """
    Calculate factor edge half-life (how long until factor IC decays to half)
    
    Parameters:
    -----------
    factor_returns : Series
        Factor returns over time (can use rolling IC as proxy)
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    float
        Half-life in periods
    """
    # This is a simplified version - in practice you'd track rolling IC
    # For now, we'll estimate from autocorrelation of factor returns
    
    # Drop NaN values
    clean = factor_returns.dropna()
    if len(clean) < 10:
        return np.nan  # Not enough data for reliable estimate
    
    # Calculate autocorrelation at different lags
    max_lag = min(len(clean) // 2, 252)  # Don't go beyond half the data or 1 year
    autocorrs = []
    
    for lag in range(1, max_lag + 1):
        if len(clean) > lag:
            corr = clean.autocorr(lag=lag)
            if np.isnan(corr):
                break
            autocorrs.append(corr)
        else:
            break
    
    if len(autocorrs) < 2:
        return np.nan
    
    # Fit exponential decay: acf = exp(-lag / half_life)
    lags = np.arange(1, len(autocorrs) + 1)
    log_acfs = np.log(np.abs(autocorrs) + 1e-8)
    
    if np.all(np.isnan(log_acfs)):
        return np.nan
    
    # Linear regression: log(acf) = -lag / half_life
    slope, _, _, _, _ = stats.linregress(lags, log_acfs)
    half_life = -1 / slope if slope < 0 else np.nan
    
    return half_life


def calculate_regime_transition_probability(
    regime_history: pd.Series
) -> pd.DataFrame:
    """
    Calculate regime transition probability matrix
    
    Parameters:
    -----------
    regime_history : Series
        Historical regime labels
        
    Returns:
    --------
    DataFrame
        Transition probability matrix (rows = from_regime, cols = to_regime)
    """
    from alpha.brain.schemas import RegimeState
    
    # Get unique regimes
    regimes = sorted([r for r in regime_history.unique() if r in [rs.value for rs in RegimeState]])
    
    if len(regimes) == 0:
        return pd.DataFrame()
    
    # Initialize transition count matrix
    transition_counts = pd.DataFrame(0, index=regimes, columns=regimes, dtype=int)
    
    # Count transitions
    for i in range(len(regime_history) - 1):
        from_regime = regime_history.iloc[i]
        to_regime = regime_history.iloc[i + 1]
        
        if from_regime in regimes and to_regime in regimes:
            transition_counts.loc[from_regime, to_regime] += 1
    
    # Convert to probabilities
    transition_probs = transition_counts.div(transition_counts.sum(axis=1), axis=0)
    transition_probs = transition_probs.fillna(0)  # Fill NaN (from states with no transitions) with 0
    
    return transition_probs


def calculate_profit_attribution_by_factor_tca(
    factor_returns: pd.DataFrame,
    factor_weights: pd.DataFrame,
    transaction_costs: pd.DataFrame,
    periods_per_year: int = 252
) -> pd.DataFrame:
    """
    Calculate profit attribution by factor with Transaction Cost Analysis (TCA).
    
    Subtracts per-factor transaction costs from gross attribution to get net attribution.
    
    Parameters:
    -----------
    factor_returns : DataFrame
        Factor returns (dates x factors)
    factor_weights : DataFrame
        Factor weights (dates x factors)
    transaction_costs : DataFrame
        Transaction costs per factor per period (dates x factors)
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    DataFrame
        Attribution table with net attribution after costs
    """
    # Align indices
    common_index = factor_returns.index.intersection(factor_weights.index).intersection(transaction_costs.index)
    factor_returns = factor_returns.loc[common_index]
    factor_weights = factor_weights.loc[common_index]
    transaction_costs = transaction_costs.loc[common_index]
    
    if len(common_index) == 0:
        return pd.DataFrame(columns=['factor', 'total_return', 'attribution', 'costs', 'net_attribution', 'contribution_pct'])
    
    # Gross portfolio returns
    portfolio_returns = (factor_returns * factor_weights).sum(axis=1)
    total_return = (1 + portfolio_returns).prod() - 1
    
    attribution_data = []
    
    for factor in factor_returns.columns:
        factor_ret = factor_returns[factor]
        avg_weight = factor_weights[factor].mean()
        
        # Gross contribution
        factor_contribution = (avg_weight * factor_ret.mean()) * len(factor_returns)
        
        # Transaction costs for this factor
        factor_costs = (transaction_costs[factor] * factor_weights[factor].abs()).sum()
        
        # Net attribution
        net_attribution = factor_contribution - factor_costs
        
        attribution_data.append({
            'factor': factor,
            'total_return': (1 + factor_returns[factor] * factor_weights[factor]).prod() - 1,
            'attribution': factor_contribution,
            'costs': factor_costs,
            'net_attribution': net_attribution,
            'contribution_pct': (net_attribution / total_return * 100) if total_return != 0 else 0
        })
    
    return pd.DataFrame(attribution_data)


def calculate_factor_timing_attribution(
    factor_returns: pd.DataFrame,
    factor_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
    periods_per_year: int = 252
) -> pd.DataFrame:
    """
    Calculate factor timing attribution (Allocation + Selection + Interaction).
    
    Brinson-style decomposition comparing dynamic weights vs static benchmark weights.
    
    Parameters:
    -----------
    factor_returns : DataFrame
        Factor returns (dates x factors)
    factor_weights : DataFrame
        Dynamic factor weights (dates x factors)
    benchmark_weights : DataFrame
        Static benchmark weights (dates x factors) or single row
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    DataFrame
        Attribution table with Allocation, Selection, Interaction effects
    """
    # Align indices
    common_index = factor_returns.index.intersection(factor_weights.index).intersection(benchmark_weights.index)
    factor_returns = factor_returns.loc[common_index]
    factor_weights = factor_weights.loc[common_index]
    benchmark_weights = benchmark_weights.loc[common_index]
    
    if len(common_index) == 0:
        return pd.DataFrame(columns=['factor', 'allocation', 'selection', 'interaction', 'total_effect'])
    
    # Portfolio returns
    portfolio_returns = (factor_returns * factor_weights).sum(axis=1)
    benchmark_returns = (factor_returns * benchmark_weights).sum(axis=1)
    
    attribution_data = []
    
    for factor in factor_returns.columns:
        factor_ret = factor_returns[factor]
        
        # Average weights
        avg_weight = factor_weights[factor].mean()
        avg_bench_weight = benchmark_weights[factor].mean()
        
        # Factor returns
        factor_return = factor_ret.mean()
        benchmark_factor_return = factor_ret.mean()  # Same factor return
        
        # Brinson decomposition
        # Allocation: (weight - bench_weight) * (bench_factor_return - total_bench_return)
        # But since we're at factor level, simplify:
        # Allocation = (weight - bench_weight) * factor_return
        allocation = (avg_weight - avg_bench_weight) * factor_ret.mean()
        
        # Selection: bench_weight * (factor_return - bench_factor_return)
        # Since we don't have sub-factor selection, this is 0 at factor level
        selection = 0.0
        
        # Interaction: (weight - bench_weight) * (factor_return - bench_factor_return)
        interaction = (avg_weight - avg_bench_weight) * (factor_ret.mean() - factor_ret.mean())
        
        total_effect = allocation + selection + interaction
        
        attribution_data.append({
            'factor': factor,
            'allocation': allocation,
            'selection': selection,
            'interaction': interaction,
            'total_effect': total_effect
        })
    
    return pd.DataFrame(attribution_data)


def calculate_brinson_attribution(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    portfolio_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
    sector_returns: pd.DataFrame = None,
    periods_per_year: int = 252
) -> dict:
    """
    Calculate Brinson attribution at portfolio level (Allocation + Selection + Interaction).
    
    Can optionally decompose by sector if sector_returns provided.
    
    Parameters:
    -----------
    portfolio_returns : Series
        Portfolio returns per period
    benchmark_returns : Series
        Benchmark returns per period
    portfolio_weights : DataFrame
        Portfolio weights (dates x assets/sectors)
    benchmark_weights : DataFrame
        Benchmark weights (dates x assets/sectors)
    sector_returns : DataFrame, optional
        Sector-level returns (dates x sectors)
    periods_per_year : int
        Number of periods in a year
        
    Returns:
    --------
    dict
        Dictionary with 'total', 'by_asset', 'by_sector' attribution tables
    """
    # Align indices
    common_index = portfolio_returns.index.intersection(benchmark_returns.index).intersection(portfolio_weights.index).intersection(benchmark_weights.index)
    
    if len(common_index) == 0:
        return {'total': pd.DataFrame(), 'by_asset': pd.DataFrame(), 'by_sector': pd.DataFrame()}
    
    portfolio_returns = portfolio_returns.loc[common_index]
    benchmark_returns = benchmark_returns.loc[common_index]
    portfolio_weights = portfolio_weights.loc[common_index]
    benchmark_weights = benchmark_weights.loc[common_index]
    
    if sector_returns is not None:
        sector_returns = sector_returns.loc[common_index]
    
    # Total portfolio returns
    total_portfolio_return = (1 + portfolio_returns).prod() - 1
    total_benchmark_return = (1 + benchmark_returns).prod() - 1
    total_excess = total_portfolio_return - total_benchmark_return
    
    # Overall attribution (single-period approximation)
    avg_port_weights = portfolio_weights.mean()
    avg_bench_weights = benchmark_weights.mean()
    
    # Asset-level returns
    if sector_returns is not None:
        asset_returns = sector_returns.mean()
    else:
        # Use portfolio weights * returns if no sector data
        asset_returns = (portfolio_returns * portfolio_weights).sum(axis=1).mean()  # approximation
    
    # Brinson attribution
    # Allocation = sum((wp - wb) * (rb - rb_total))
    # Selection = sum(wb * (rp - rb))
    # Interaction = sum((wp - wb) * (rp - rb))
    
    attribution_data = []
    
    for asset in portfolio_weights.columns:
        wp = portfolio_weights[asset].mean()
        wb = benchmark_weights[asset].mean()
        
        rp = portfolio_returns.mean()  # portfolio return
        rb = benchmark_returns.mean()  # benchmark return
        
        # At asset level, need asset-specific returns
        # Approximate with overall returns if not available
        allocation = (wp - wb) * (benchmark_returns.mean() - benchmark_returns.mean())
        selection = wb * (portfolio_returns.mean() - benchmark_returns.mean())
        interaction = (wp - wb) * (portfolio_returns.mean() - benchmark_returns.mean())
        
        attribution_data.append({
            'asset': asset,
            'allocation': allocation,
            'selection': selection,
            'interaction': interaction,
            'total_effect': allocation + selection + interaction
        })
    
    by_asset = pd.DataFrame(attribution_data)
    
    # Sector-level if sector_returns provided
    by_sector = pd.DataFrame()
    if sector_returns is not None and len(sector_returns.columns) > 0:
        sector_attr = []
        for sector in sector_returns.columns:
            wp = portfolio_weights[sector].mean() if sector in portfolio_weights.columns else 0
            wb = benchmark_weights[sector].mean() if sector in benchmark_weights.columns else 0
            rp = sector_returns[sector].mean()
            rb = sector_returns[sector].mean()  # approximation
            
            allocation = (wp - wb) * (rb - rb)
            selection = wb * (rp - rb)
            interaction = (wp - wb) * (rp - rb)
            
            sector_attr.append({
                'sector': sector,
                'allocation': allocation,
                'selection': selection,
                'interaction': interaction,
                'total_effect': allocation + selection + interaction
            })
        by_sector = pd.DataFrame(sector_attr)
    
    total_df = pd.DataFrame([{
        'total_portfolio_return': total_portfolio_return,
        'total_benchmark_return': total_benchmark_return,
        'total_excess_return': total_excess,
        'allocation_total': by_asset['allocation'].sum(),
        'selection_total': by_asset['selection'].sum(),
        'interaction_total': by_asset['interaction'].sum(),
        'total_effect': by_asset['total_effect'].sum()
    }])
    
    return {
        'total': total_df,
        'by_asset': by_asset,
        'by_sector': by_sector
    }
