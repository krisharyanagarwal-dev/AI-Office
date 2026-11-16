#!/usr/bin/env python3
"""
Comparison test for VectorizedBacktester vs EventDrivenBacktester
"""
import sys
import os
sys.path.insert(0, '/Users/aryanagarwal/alpha-system')

import pandas as pd
import numpy as np
from alpha.backtest import VectorizedBacktester, EventDrivenBacktester

def get_vectorized_metrics(vec_results):
    """Extract metrics from vectorized backtester results in a standardized format"""
    equity_curve = vec_results['equity_curve']
    metrics = vec_results['metrics']
    
    return {
        'initial_capital': vec_results['initial_capital'],
        'final_equity': equity_curve.iloc[-1] if len(equity_curve) > 0 else vec_results['initial_capital'],
        'total_return': metrics['total_return'],
        'annualized_return': metrics['annualized_return'],
        'volatility': metrics['volatility'],
        'sharpe_ratio': metrics['sharpe_ratio'],
        'max_drawdown': metrics['max_drawdown'],
        'win_rate': metrics['win_rate'],
        'total_trades': metrics.get('total_days', 0)  # Approximation
    }

def get_event_driven_metrics(evt_results):
    """Extract metrics from event-driven backtester results"""
    return {
        'initial_capital': evt_results['initial_capital'],
        'final_equity': evt_results['final_equity'],
        'total_return': evt_results['total_return'],
        'annualized_return': evt_results['annualized_return'],
        'volatility': evt_results['volatility'],
        'sharpe_ratio': evt_results['sharpe_ratio'],
        'max_drawdown': evt_results['max_drawdown'],
        'win_rate': evt_results['win_rate'],
        'total_trades': evt_results['total_trades']
    }

def compare_backtesters():
    """Compare vectorized and event-driven backtesters with same data"""
    print("Comparing VectorizedBacktester vs EventDrivenBacktester...")
    
    # Create sample data
    dates = pd.date_range('2020-01-01', '2020-12-31', freq='D')
    n = len(dates)
    
    # Create two assets with correlated returns
    np.random.seed(42)
    returns_a = np.random.normal(0.0005, 0.02, n)  # 0.05% daily return, 2% volatility
    returns_b = np.random.normal(0.0003, 0.015, n) + 0.5 * returns_a  # correlated with A
    
    # Convert to prices
    prices_a = 100 * np.exp(np.cumsum(returns_a))
    prices_b = 100 * np.exp(np.cumsum(returns_b))
    
    # Create DataFrames
    data_a = pd.DataFrame({
        'open': prices_a * 0.99,
        'high': prices_a * 1.01,
        'low': prices_a * 0.98,
        'close': prices_a,
        'volume': np.random.randint(1000000, 5000000, n)
    }, index=dates)
    
    data_b = pd.DataFrame({
        'open': prices_b * 0.99,
        'high': prices_b * 1.01,
        'low': prices_b * 0.98,
        'close': prices_b,
        'volume': np.random.randint(1000000, 5000000, n)
    }, index=dates)
    
    data = {
        'ASSET_A': data_a,
        'ASSET_B': data_b
    }
    
    # Create simple signals: buy when price > 50-day moving average
    signals = {}
    for symbol, df in data.items():
        ma_50 = df['close'].rolling(50).mean()
        signal = np.where(df['close'] > ma_50, 1, -1)  # 1 for long, -1 for short
        signals[symbol] = pd.Series(signal, index=df.index)
    
    print(f"Testing on {len(data)} symbols from {dates[0]} to {dates[-1]}")
    print(f"Data points per symbol: {len(data_a)}")
    
    # Run Vectorized Backtester
    print("\n" + "="*60)
    print("RUNNING VECTORIZED BACKTESTER")
    print("="*60)
    try:
        # Need to set API keys to avoid provider errors
        import os
        os.environ['ALPHAVANTAGE_API_KEY'] = 'dummy_key'
        os.environ['POLYGON_API_KEY'] = 'dummy_key'
        
        vec_backtester = VectorizedBacktester()
        vec_results = vec_backtester.run_backtest(
            signals=signals,
            data=data,
            initial_capital=100000
        )
        vec_metrics = get_vectorized_metrics(vec_results)
        print("✓ VectorizedBacktester completed successfully")
        vec_success = True
    except Exception as e:
        print(f"✗ VectorizedBacktester failed: {e}")
        import traceback
        traceback.print_exc()
        vec_success = False
        vec_metrics = None
    
    # Run Event-Driven Backtester
    print("\n" + "="*60)
    print("RUNNING EVENT-DRIVEN BACKTESTER")
    print("="*60)
    try:
        evt_backtester = EventDrivenBacktester()
        evt_results = evt_backtester.run_backtest(
            signals=signals,
            data=data,
            initial_capital=100000
        )
        evt_metrics = get_event_driven_metrics(evt_results)
        print("✓ EventDrivenBacktester completed successfully")
        evt_success = True
    except Exception as e:
        print(f"✗ EventDrivenBacktester failed: {e}")
        import traceback
        traceback.print_exc()
        evt_success = False
        evt_metrics = None
    
    # Compare results if both succeeded
    if vec_success and evt_success:
        print("\n" + "="*60)
        print("COMPARISON RESULTS")
        print("="*60)
        
        print(f"{'Metric':<25} {'Vectorized':<15} {'Event-Driven':<15} {'Difference':<15}")
        print("-" * 70)
        
        # Compare key metrics
        metrics_to_compare = [
            ('Initial Capital', 'initial_capital', lambda x: f"${x:,.0f}"),
            ('Final Equity', 'final_equity', lambda x: f"${x:,.0f}"),
            ('Total Return', 'total_return', lambda x: f"{x:.2%}"),
            ('Annualized Return', 'annualized_return', lambda x: f"{x:.2%}"),
            ('Volatility', 'volatility', lambda x: f"{x:.2%}"),
            ('Sharpe Ratio', 'sharpe_ratio', lambda x: f"{x:.2f}"),
            ('Max Drawdown', 'max_drawdown', lambda x: f"{x:.2%}"),
            ('Win Rate', 'win_rate', lambda x: f"{x:.2%}"),
            ('Total Trades', 'total_trades', lambda x: f"{x}")
        ]
        
        for metric_name, vec_key, fmt_func in metrics_to_compare:
            vec_val = vec_metrics[vec_key]
            evt_val = evt_metrics[vec_key]
            
            if isinstance(vec_val, (int, float)) and isinstance(evt_val, (int, float)):
                if isinstance(vec_val, float):
                    diff = evt_val - vec_val
                    if 'Return' in metric_name or 'Drawdown' in metric_name or 'Rate' in metric_name:
                        diff_str = f"{diff:+.2%}"
                    else:
                        diff_str = f"{diff:+.2f}"
                else:
                    diff = evt_val - vec_val
                    diff_str = f"{diff:+d}"
                
                print(f"{metric_name:<25} {fmt_func(vec_val):<15} {fmt_func(evt_val):<15} {diff_str:<15}")
            else:
                print(f"{metric_name:<25} {str(vec_val):<15} {str(evt_val):<15} {'N/A':<15}")
        
        print("\n🎉 Both backtesters completed successfully!")
        return True
    else:
        print("\n❌ Comparison failed - one or both backtesters had errors")
        return False

if __name__ == "__main__":
    compare_backtesters()
