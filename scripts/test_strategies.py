#!/usr/bin/env python3
"""
Test script to validate strategy implementations
"""

import pandas as pd
import numpy as np
import sys
import os

# Add the strategy utility path
sys.path.append('/Users/aryanagarwal/.openalice/workspaces/workspaces/a31ee5a7-c1bc-45ae-8072-83989eb582e7/utils')

# Import strategy utilities
from strategy_utils import (
    calculate_volume_spike,
    calculate_regime_ema200,
    calculate_drawdown_from_high,
    calculate_rsi_conviction,
    calculate_atr_stoploss,
    calculate_atr_take_profit,
    is_volume_above_average
)

def test_strategy_utilities():
    """Test the shared strategy utilities"""
    print("Testing Strategy Utilities...")

    # Test data
    dates = pd.date_range('2023-01-01', periods=100, freq='1h')
    sample_data = pd.DataFrame({
        'open': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 105,
        'low': np.random.randn(100).cumsum() + 95,
        'close': np.random.randn(100).cumsum() + 100,
        'volume': np.random.randn(100).abs() * 1000 + 500
    }, index=dates)

    # Add some indicators for testing
    sample_data['ema200'] = sample_data['close'].ewm(span=200).mean()
    sample_data['volume_ma20'] = sample_data['volume'].rolling(20).mean()
    sample_data['rsi'] = 50 + 20 * np.sin(np.arange(100) * 0.1)  # Fake RSI for testing
    sample_data['high'] = sample_data['high']  # For drawdown test

    print("  Testing calculate_volume_spike...")
    current_vol = sample_data['volume'].iloc[-1]
    vol_ma = sample_data['volume_ma20'].iloc[-1]
    vol_spike = calculate_volume_spike(current_vol, vol_ma, 1.5)
    print(f"    Result: {vol_spike} (Current: {current_vol:.0f}, MA: {vol_ma:.0f}, Ratio: {current_vol/vol_ma:.2f})")

    print("  Testing calculate_regime_ema200...")
    regime_df = calculate_regime_ema200(sample_data.copy())
    regime_counts = regime_df['regime'].value_counts().sort_index()
    print(f"    Bull (2): {regime_counts.get(2, 0)}, Neutral (1): {regime_counts.get(1, 0)}, Winter (0): {regime_counts.get(0, 0)}")

    print("  Testing calculate_drawdown_from_high...")
    drawdown = calculate_drawdown_from_high(sample_data['high'])
    print(f"    Current Drawdown: {drawdown.iloc[-1]:.2%}, Max Drawdown: {drawdown.min():.2%}")

    print("  Testing calculate_rsi_conviction...")
    rsi_conviction = calculate_rsi_conviction(sample_data['rsi'])
    print(f"    Current RSI: {sample_data['rsi'].iloc[-1]:.1f}, Current Conviction: {rsi_conviction.iloc[-1]:.2f}")

    print("  Testing calculate_atr_stoploss...")
    stop_loss = calculate_atr_stoploss(100.0, 2.0, 2.5)
    print(f"    Stop Loss: {stop_loss} (Entry: 100.0, ATR: 2.0, Multiplier: 2.5)")

    print("  Testing calculate_atr_take_profit...")
    take_profit = calculate_atr_take_profit(100.0, 2.0, 5.0)
    print(f"    Take Profit: {take_profit} (Entry: 100.0, ATR: 2.0, Multiplier: 5.0)")

    print("  Strategy Utilities Test Complete\n")

def test_trading_bot_strategy():
    """Test the main trading bot strategy module"""
    print("Testing Trading Bot Strategy Module...")

    # Add trading bot to path
    sys.path.append('/Users/aryanagarwal/trading-bot')

    try:
        from strategy import (
            calculate_ema,
            ema_crossover_signal,
            rsi_signal,
            macd_signal,
            get_strategy_signal,
            get_combined_signal
        )

        # Test data
        prices = np.random.randn(50).cumsum() + 100
        prices = np.abs(prices) + 50  # Ensure positive prices

        print("  Testing calculate_ema...")
        ema_values = calculate_ema(prices, 12)
        print(f"    EMA length: {len(ema_values)}, last value: {ema_values[-1]:.2f}")

        print("  Testing ema_crossover_signal...")
        signal = ema_crossover_signal(prices, 12, 26)
        print(f"    Signal: {signal}")

        print("  Testing rsi_signal...")
        signal = rsi_signal(prices, 14, 70, 30)
        print(f"    Signal: {signal}")

        print("  Testing macd_signal...")
        signal = macd_signal(prices, 12, 26, 9)
        print(f"    Signal: {signal}")

        print("  Testing get_strategy_signal...")
        signal = get_strategy_signal('ema', prices, fast_period=12, slow_period=26)
        print(f"    EMA Signal: {signal}")

        signal = get_strategy_signal('rsi', prices, period=14, overbought=70, oversold=30)
        print(f"    RSI Signal: {signal}")

        signal = get_strategy_signal('macd', prices, fast=12, slow=26, signal=9)
        print(f"    MACD Signal: {signal}")

        print("  Testing get_combined_signal...")
        strategies = [
            {'name': 'ema', 'params': {'fast_period': 12, 'slow_period': 26}},
            {'name': 'rsi', 'params': {'period': 14, 'overbought': 70, 'oversold': 30}}
        ]
        htf_data = np.random.randn(30).cumsum() + 100
        htf_data = np.abs(htf_data) + 50
        signal = get_combined_signal(prices, strategies, htf_data=htf_data)
        print(f"    Combined Signal: {signal}")

        print("  Trading Bot Strategy Test Complete\n")

    except Exception as e:
        print(f"  ERROR in Trading Bot Strategy Test: {e}\n")

if __name__ == "__main__":
    print("Running Strategy Validation Tests\n")

    test_strategy_utilities()
    test_trading_bot_strategy()

    print("All tests completed!")