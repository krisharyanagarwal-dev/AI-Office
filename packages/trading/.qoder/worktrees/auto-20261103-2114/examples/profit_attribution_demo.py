#!/usr/bin/env python3
"""
Profit Attribution Demo
Demonstrates how to use the new profit attribution functions in the alpha-system

Usage:
    python profit_attribution_demo.py [--mode MODE] [--output OUTPUT] [--periods PERIODS] [--seed SEED] [--real-data]
    
Modes:
    all         Run all attribution analyses (default)
    factor      Factor attribution only
    regime      Regime attribution only  
    model       Model attribution only
    half-life   Factor half-life analysis only
    transition  Regime transition matrix only
    tca         Transaction cost aware factor attribution
    timing      Factor timing attribution (Brinson)
    brinson     Brinson portfolio attribution
    all         All analyses (default)

Output formats:
    console     Print to console (default)
    csv         Save results to CSV files
    json        Save results to JSON files
    html        Generate HTML report
"""
import argparse
import pandas as pd
import numpy as np
import sys
import os
import json
from datetime import datetime

# Add alpha-system to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from alpha.validation.metrics import (
    calculate_profit_attribution_by_factor,
    calculate_profit_attribution_by_regime,
    calculate_profit_attribution_by_model,
    calculate_factor_half_life,
    calculate_regime_transition_probability,
    calculate_profit_attribution_by_factor_tca,
    calculate_factor_timing_attribution,
    calculate_brinson_attribution,
)


def generate_sample_data(n_periods=252, seed=42):
    """Generate sample factor returns, regimes, and model predictions"""
    np.random.seed(seed)
    
    dates = pd.date_range('2023-01-01', periods=n_periods, freq='D')
    
    # Generate factor returns
    factor_returns = pd.DataFrame({
        'momentum': np.random.normal(0.0005, 0.015, n_periods),
        'value': np.random.normal(0.0003, 0.012, n_periods),
        'quality': np.random.normal(0.0004, 0.010, n_periods),
    }, index=dates)
    
    # Add correlations
    factor_returns['value'] += 0.3 * factor_returns['momentum']
    factor_returns['quality'] += 0.2 * factor_returns['momentum'] + 0.2 * factor_returns['value']
    
    # Equal weights
    factor_weights = pd.DataFrame({
        'momentum': 0.33,
        'value': 0.33,
        'quality': 0.34
    }, index=dates)
    
    # Regimes from momentum
    trend_signal = factor_returns['momentum'].rolling(20).mean().fillna(0)
    regimes = pd.Series(
        np.where(trend_signal > 0.001, 'trend_up',
                np.where(trend_signal < -0.001, 'trend_down', 'chop')),
        index=dates
    )
    
    # Portfolio returns
    factor_weights = pd.DataFrame({
        'momentum': 0.33,
        'value': 0.33,
        'quality': 0.34
    }, index=dates)
    actual_returns = (factor_returns * factor_weights).sum(axis=1)
    
    # Model predictions
    model_predictions = {
        'ml_model': pd.Series(
            factor_returns['momentum'].shift(1).fillna(0) + np.random.normal(0, 0.005, n_periods),
            index=dates
        ),
        'factor_model': pd.Series(
            (factor_returns * pd.Series([0.4, 0.3, 0.3], index=['momentum', 'value', 'quality'])).sum(axis=1).shift(1).fillna(0),
            index=dates
        )
    }
    
    model_weights = {'ml_model': 0.6, 'factor_model': 0.4}
    
    return {
        'dates': dates,
        'factor_returns': factor_returns,
        'factor_weights': factor_weights,
        'regimes': regimes,
        'actual_returns': (factor_returns * factor_weights).sum(axis=1),
        'model_predictions': model_predictions,
        'model_weights': model_weights,
        'factor_returns_raw': factor_returns,
        'returns': pd.DataFrame({
            col: np.random.normal(0.0005, 0.015, len(dates)) for col in ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM']
        }, index=pd.date_range('2023-01-01', periods=n_periods, freq='D')),
    }


def load_real_data(tickers, start, end):
    """Load real data from yfinance"""
    try:
        import yfinance as yf
        data = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)['Close']
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        data = data.ffill().dropna(axis=1, how='all')
        returns = data.pct_change().dropna()
        return returns
    except ImportError:
        print("yfinance not installed, using synthetic data")
        return None


def run_factor_attribution(data, output_format='console', output_dir=None):
    """Run factor attribution analysis"""
    print("\n📊 1. Factor Attribution Analysis")
    print("-" * 50)
    
    factor_attr = calculate_profit_attribution_by_factor(
        data['factor_returns'], 
        data['factor_weights']
    )
    
    if output_format == 'console':
        print(factor_attr.to_string(index=False))
    elif output_format in ('csv', 'json'):
        if output_dir:
            path = os.path.join(output_dir, 'factor_attribution.csv')
            factor_attr.to_csv(path, index=False)
            print(f"Saved to {path}")
    
    return factor_attr


def run_regime_attribution(data, output_format='console', output_dir=None):
    """Run regime attribution analysis"""
    print("\n📊 2. Regime Attribution Analysis")
    print("-" * 50)
    
    # Recreate factors for attribution
    trend_signal = data['factor_returns_raw']['momentum'].rolling(20).mean().fillna(0)
    regimes = pd.Series(
        np.where(trend_signal > 0.001, 'trend_up',
                np.where(trend_signal < -0.001, 'trend_down', 'chop')),
        index=data['factor_returns_raw'].index
    )
    
    portfolio_returns = (data['factor_returns_raw'] * data['factor_weights']).sum(axis=1)
    
    regime_attr = calculate_profit_attribution_by_regime(portfolio_returns, regimes)
    
    if output_format == 'console':
        print(regime_attr.to_string(index=False))
    elif output_format in ('csv', 'json') and output_dir:
        path = os.path.join(output_dir, 'regime_attribution.csv')
        regime_attr.to_csv(path, index=False)
        print(f"Saved to {path}")
    
    return regime_attr


def run_model_attribution(data, output_format='console', output_dir=None):
    """Run model attribution analysis"""
    print("\n📊 3. Model Attribution Analysis")
    print("-" * 50)
    
    # Recreate models
    factor_returns_raw = data['factor_returns_raw']
    returns = data['returns'] if 'returns' in data else pd.DataFrame()
    
    # Recreate individual factors using the same logic as factor engineering cell
    # Momentum (12-1): 12-month return skipping last month
    # Recreate individual factors using the same logic as factor engineering cell
    # Momentum (12-1): 12-month return skipping last month
    mom_12_1 = data['factor_returns_raw'].pct_change(252).shift(21).mean(axis=1)
    # Reversal (1-month): Negative 1-month return  
    reversal_1m = -data['factor_returns_raw'].rolling(21).mean().mean(axis=1)
    # Volatility (60-day): 60-day rolling standard deviation (inverted for quality factor)
    vol_60 = data['factor_returns_raw'].rolling(60).std().mean(axis=1)
    quality_factor = 1 / (vol_60 + 1e-8)  # Invert volatility for quality (lower vol = higher quality)
    # Value proxy: mean reversion (negative 60-day return)
    value_factor = -data['factor_returns_raw'].rolling(60).mean().mean(axis=1)

    factor_returns = pd.DataFrame({
        'momentum': mom_12_1,
        'reversal': reversal_1m,
        'quality': quality_factor,
        'value': value_factor
    }, index=data['factor_returns_raw'].index)

    for col in factor_returns.columns:
        std_val = factor_returns[col].std()
        factor_returns[col] = factor_returns[col].sub(factor_returns[col].mean()).div(
            std_val if std_val != 0 else 1)
    
    factor_weights = pd.DataFrame(0.25, index=factor_returns.index, columns=factor_returns.columns)
    asset_returns = (factor_returns * factor_weights).sum(axis=1)
    portfolio_returns = asset_returns.mean()
    
    trend_signal = factor_returns['momentum'].rolling(20).mean().fillna(0)
    regimes = pd.Series(
        np.where(trend_signal > 0.001, 'trend_up',
                np.where(trend_signal < -0.001, 'trend_down', 'chop')),
        index=factor_returns.index
    )
    
    model1_pred = factor_returns['momentum'].rolling(5).mean().shift(1)
    model2_pred = -factor_returns['momentum'].rolling(5).mean().shift(1)
    model1_pred = (model1_pred - model1_pred.mean()) / (model1_pred.std() + 1e-8)
    model2_pred = (model2_pred - model2_pred.mean()) / (model2_pred.std() + 1e-8)
    
    model_predictions = {
        'momentum_model': model1_pred,
        'mean_reversion_model': model2_pred
    }
    model_weights = {'momentum_model': 0.6, 'mean_reversion_model': 0.4}
    
    # Ensure portfolio_returns is a Series with proper index
    if isinstance(portfolio_returns, (float, int, np.floating)):
        portfolio_returns = pd.Series(portfolio_returns, index=factor_returns.index)
    
    model_attr = calculate_profit_attribution_by_model(
        model_predictions,  # Use the actual model predictions from data
        portfolio_returns,
        model_weights
    )
    
    return model_attr


def run_half_life_analysis(data, output_format='console', output_dir=None):
    """Run factor half-life analysis"""
    print("\n📊 4. Factor Half-Life Analysis")
    print("-" * 50)
    
    factor_returns = pd.DataFrame({
        'momentum': np.random.normal(0.0005, 0.015, 252),
        'reversal': np.random.normal(0.0003, 0.012, 252),
        'quality': np.random.normal(0.0004, 0.010, 252),
        'value': np.random.normal(0.0003, 0.012, 252),
    }, index=pd.date_range('2023-01-01', periods=252, freq='D'))
    
    print("Factor half-life (estimated decay time):")
    for factor in factor_returns.columns:
        half_life = calculate_factor_half_life(factor_returns[factor])
        print(f"{factor:10s}: {half_life:3.0f} days")
    
    return None


def run_transition_matrix(data, output_format='console', output_dir=None):
    """Run regime transition matrix"""
    print("\n📊 5. Regime Transition Probability Matrix")
    print("-" * 50)
    
    trend_signal = np.random.normal(0, 1, 252).cumsum()
    regimes = pd.Series(
        np.where(trend_signal > 0.5, 'trend_up',
                np.where(trend_signal < -0.5, 'trend_down', 'chop')),
        index=pd.date_range('2023-01-01', periods=252, freq='D')
    )
    
    transition_prob = calculate_regime_transition_probability(regimes)
    
    if output_format == 'console':
        print(transition_prob.to_string())
    elif output_format in ('csv', 'json') and output_dir:
        path = os.path.join(output_dir, 'transition_matrix.csv')
        transition_prob.to_csv(path)
        print(f"Saved to {path}")
    
    return None


def run_tca_attribution(data, output_format='console', output_dir=None):
    """Run TCA-aware factor attribution"""
    print("\n📊 TCA-Aware Factor Attribution")
    print("-" * 50)
    
    factor_returns = pd.DataFrame({
        'momentum': np.random.normal(0.0005, 0.015, 100),
        'reversal': np.random.normal(0.0003, 0.012, 100),
        'quality': np.random.normal(0.0004, 0.010, 100),
        'value': np.random.normal(0.0003, 0.012, 100),
    }, index=pd.date_range('2023-01-01', periods=100, freq='D'))
    
    factor_weights = pd.DataFrame(0.25, index=factor_returns.index, columns=factor_returns.columns)
    transaction_costs = pd.DataFrame(0.001, index=factor_returns.index, columns=factor_returns.columns)
    
    tca_result = calculate_profit_attribution_by_factor_tca(
        pd.DataFrame({
            'momentum': np.random.normal(0.0005, 0.015, 100),
            'reversal': np.random.normal(0.0003, 0.012, 100),
            'quality': np.random.normal(0.0004, 0.010, 100),
            'value': np.random.normal(0.0003, 0.012, 100),
        }, index=pd.date_range('2023-01-01', periods=100, freq='D')),
        pd.DataFrame(0.25, index=pd.date_range('2023-01-01', periods=100, freq='D'), columns=['momentum', 'reversal', 'quality', 'value']),
        pd.DataFrame(0.001, index=pd.date_range('2023-01-01', periods=100, freq='D'), columns=['momentum', 'reversal', 'quality', 'value'])
    )
    
    if output_format == 'console':
        print(tca_result.to_string(index=False))
    elif output_format in ('csv', 'json') and output_dir:
        path = os.path.join(output_dir, 'tca_attribution.csv')
        tca_result.to_csv(path, index=False)
        print(f"Saved to {path}")
    
    return None


def run_timing_attribution(data, output_format='console', output_dir=None):
    """Run factor timing attribution"""
    print("\n📊 Factor Timing Attribution (Brinson)")
    print("-" * 50)
    
    factor_returns = pd.DataFrame({
        'momentum': np.random.normal(0.0005, 0.015, 100),
        'reversal': np.random.normal(-0.0003, 0.012, 100),
    }, index=pd.date_range('2023-01-01', periods=100, freq='D'))
    
    factor_weights = pd.DataFrame({
        'momentum': 0.6,
        'reversal': 0.4
    }, index=pd.date_range('2023-01-01', periods=100, freq='D'))
    
    benchmark_weights = pd.DataFrame({
        'momentum': 0.5,
        'reversal': 0.5
    }, index=pd.date_range('2023-01-01', periods=100, freq='D'))
    
    timing_result = calculate_factor_timing_attribution(
        factor_returns, factor_weights, benchmark_weights
    )
    
    if output_format == 'console':
        print(timing_result.to_string(index=False))
    
    return None


def run_brinson_attribution(data, output_format='console', output_dir=None):
    """Run Brinson portfolio attribution"""
    print("\n📊 Brinson Portfolio Attribution")
    print("-" * 50)
    
    dates = pd.date_range('2023-01-01', periods=100, freq='D')
    portfolio_returns = pd.Series(np.random.normal(0.001, 0.02, 100), index=pd.date_range('2023-01-01', periods=100, freq='D'))
    benchmark_returns = pd.Series(np.random.normal(0.0005, 0.015, 100), index=pd.date_range('2023-01-01', periods=100, freq='D'))
    portfolio_weights = pd.DataFrame(0.5, index=pd.date_range('2023-01-01', periods=100, freq='D'), columns=['asset1', 'asset2'])
    benchmark_weights = pd.DataFrame(0.5, index=pd.date_range('2023-01-01', periods=100, freq='D'), columns=['asset1', 'asset2'])
    
    result = calculate_brinson_attribution(
        pd.Series(np.random.normal(0.001, 0.02, 100), index=dates),
        pd.Series(np.random.normal(0.0005, 0.015, 100), index=dates),
        pd.DataFrame(0.5, index=pd.date_range('2023-01-01', periods=100, freq='D'), columns=['asset1', 'asset2']),
        pd.DataFrame(0.5, index=pd.date_range('2023-01-01', periods=100, freq='D'), columns=['asset1', 'asset2'])
    )
    
    if output_format == 'console':
        print(result['total'].to_string(index=False))
        print(result['by_asset'].to_string(index=False))
    
    return None


def save_results(results_dict, output_format, output_dir):
    """Save results to files"""
    if not output_dir:
        return
    
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    for name, result in results_dict.items():
        if result is None:
            continue
        if isinstance(result, dict):
            for k, v in result.items():
                if isinstance(v, pd.DataFrame) and not v.empty:
                    if output_format == 'csv':
                        v.to_csv(os.path.join(output_dir, f"{name}_{k}_{timestamp}.csv"))
                    elif output_format == 'json':
                        v.to_json(os.path.join(output_dir, f"{name}_{k}_{timestamp}.json"), orient='records')
        elif isinstance(result, pd.DataFrame) and not result.empty:
            if output_format == 'csv':
                result.to_csv(os.path.join(output_dir, f"{name}_{timestamp}.csv"), index=False)
            elif output_format == 'json':
                result.to_json(os.path.join(output_dir, f"{name}_{timestamp}.json"), orient='records')


def main():
    parser = argparse.ArgumentParser(description='Profit Attribution Demo')
    parser.add_argument('--mode', choices=['all', 'factor', 'regime', 'model', 'half-life', 'transition', 'tca', 'timing', 'brinson', 'all'], 
                        default='all', help='Analysis mode')
    parser.add_argument('--output', choices=['console', 'csv', 'json', 'html'], default='console',
                        help='Output format')
    parser.add_argument('--output-dir', type=str, default=None, help='Output directory for files')
    parser.add_argument('--periods', type=int, default=252, help='Number of periods (days)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--real-data', action='store_true', help='Use real data from yfinance')
    parser.add_argument('--tickers', nargs='+', default=['SPY', 'QQQ', 'IWM', 'EFA', 'EEM'], help='Tickers for real data')
    parser.add_argument('--start', type=str, default='2020-01-01', help='Start date for real data')
    parser.add_argument('--end', type=str, default='2024-12-31', help='End date for real data')
    
    args = parser.parse_args()
    
    # Generate or load data
    if args.real_data:
        print("📥 Loading real data from yfinance...")
        returns = load_real_data(args.tickers, args.start, args.end)
        if returns is None:
            print("Failed to load real data, falling back to synthetic")
            data = generate_sample_data(args.periods, args.seed)
        else:
            data = {'factor_returns_raw': returns, 'returns': returns}
    else:
        data = generate_sample_data(args.periods, args.seed)
    
    print(f"📊 Generated {len(data.get('dates', pd.date_range('2023-01-01', periods=252)))} periods of sample data")
    print(f"📅 Date range: {data.get('dates', pd.date_range('2023-01-01', periods=252))[0].date()} to {data.get('dates', pd.date_range('2023-01-01', periods=252))[-1].date()}")
    
    results = {}
    
    # Run selected analyses
    if args.mode in ('all', 'factor'):
        results['factor'] = run_factor_attribution(data, args.output, args.output_dir)
    
    if args.mode in ('all', 'regime'):
        results['regime'] = run_regime_attribution(data, args.output, args.output_dir)
    
    if args.mode in ('all', 'model'):
        results['model'] = run_model_attribution(data, args.output, args.output_dir)
    
    if args.mode in ('all', 'half-life'):
        run_half_life_analysis(data)
    
    if args.mode in ('all', 'transition'):
        run_transition_matrix(data, args.output, args.output_dir)
    
    if args.mode in ('all', 'tca'):
        run_tca_attribution(data, args.output, args.output_dir)
    
    if args.mode in ('all', 'timing'):
        run_timing_attribution(data, args.output, args.output_dir)
    
    if args.mode in ('all', 'brinson'):
        run_brinson_attribution(data, args.output, args.output_dir)
    
    # Save results if output format is not console
    if args.output != 'console' and args.output_dir:
        save_results(results, args.output, args.output_dir)
    
    if args.mode == 'all':
        print("\n✅ Profit Attribution Demo Complete!")
        print("💡 These attribution analyses help identify what's driving performance")
        print("   and where to allocate capital for optimal risk-adjusted returns.")


if __name__ == "__main__":
    main()
