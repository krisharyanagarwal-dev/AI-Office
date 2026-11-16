#!/usr/bin/env python3
"""
Test script for VectorizedBacktester
"""
import sys
import os
sys.path.insert(0, '/Users/aryanagarwal/alpha-system')

import pandas as pd
import numpy as np
from alpha.backtest import VectorizedBacktester

def test_vectorized_backtester():
    """Test the vectorized backtester with simple data"""
    print("Testing VectorizedBacktester...")
    
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
    
    # Run backtest
    backtester = VectorizedBacktester()
    results = backtester.run_backtest(
        signals=signals,
        data=data,
        initial_capital=100000
    )
    
    # Print results
    print("\n" + "="*50)
    print("BACKTEST RESULTS")
    print("="*50)
    print(backtester.get_tear_sheet())
    
    # Verify results structure
    assert 'equity_curve' in results
    assert 'metrics' in results
    assert 'data' in results
    assert 'signals' in results
    assert len(results['equity_curve']) > 0
    
    print("✓ VectorizedBacktester test passed!")
    return True

if __name__ == "__main__":
    try:
        test_vectorized_backtester()
        print("\n🎉 All tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)