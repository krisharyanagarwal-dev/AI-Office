#!/usr/bin/env python3
"""
Test script for EventDrivenBacktester
"""
import sys
import os
sys.path.insert(0, '/Users/aryanagarwal/alpha-system')

import pandas as pd
import numpy as np
from alpha.backtest import EventDrivenBacktester

def test_event_driven_backtester():
    """Test the event-driven backtester with simple data"""
    print("Testing EventDrivenBacktester...")
    
    # Create sample data (same as vectorized test)
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
    
    # Run backtest
    backtester = EventDrivenBacktester()
    results = backtester.run_backtest(
        signals=signals,
        data=data,
        initial_capital=100000
    )
    
    # Print results
    print("\n" + "="*50)
    print("EVENT-DRIVEN BACKTEST RESULTS")
    print("="*50)
    print(f"Period: {results['period_start']} to {results['period_end']}")
    print(f"Initial Capital: ${results['initial_capital']:,.2f}")
    print(f"Final Equity: ${results['final_equity']:,.2f}")
    print(f"Total Return: {results['total_return']:.2%}")
    print(f"Annualized Return: {results['annualized_return']:.2%}")
    print(f"Volatility: {results['volatility']:.2%}")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results['max_drawdown']:.2%}")
    print(f"Win Rate: {results['win_rate']:.2%}")
    print(f"Total Trades: {results['total_trades']}")
    
    # Basic validations
    assert results['initial_capital'] == 100000
    assert isinstance(results['total_return'], float)
    assert isinstance(results['annualized_return'], float)
    assert results['volatility'] >= 0
    assert 0 <= results['win_rate'] <= 1
    assert results['total_trades'] >= 0
    
    print("\n✓ EventDrivenBacktester test passed!")
    return True

if __name__ == "__main__":
    test_event_driven_backtester()
