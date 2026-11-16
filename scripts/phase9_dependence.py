import json
import numpy as np
import pandas as pd
from datetime import datetime
import os
import hashlib

# Load the 5m data
DATA_PATH = '/Users/aryanagarwal/trading-bot/data/btc_5m_5year.parquet'
data_5m = pd.read_parquet(DATA_PATH)
print(f"Loaded 5m data: {len(data_5m)} bars from {data_5m.index[0]} to {data_5m.index[-1]}")

# Function to resample to higher timeframes
def resample_ohlcv(df, rule):
    """Resample OHLCV data to higher timeframe"""
    resampled = df.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    return resampled

# Create timeframes to test (same as original)
timeframes = {
    '5m': '5T',
    '15m': '15T',
    '30m': '30T',
    '1h': '1H',
    '2h': '2H',
    '4h': '4H'
}

# Store all timeframe data
all_data = {'5m': data_5m}  # Include 5m for completeness
for tf_name, rule in timeframes.items():
    all_data[tf_name] = resample_ohlcv(data_5m, rule)
    print(f"Loaded {tf_name} data: {len(all_data[tf_name])} bars")

# Strategy parameters (from original experiment)
ema_fast = 20
ema_slow = 50
atr_mult = 1.5
risk_per_trade = 0.1  # 10% equity per trade
fees_rt = 0.0005      # 0.05% round-trip fees
slippage_per_trade = 0.0005  # 0.05% slippage

# ATR period for calculation
atr_period = 14

# Function to calculate EMA
def calculate_ema(period, values):
    """Calculate EMA"""
    ema = np.zeros_like(values)
    ema[0] = values[0]
    multiplier = 2 / (period + 1)
    for i in range(1, len(values)):
        ema[i] = (values[i] * multiplier) + (ema[i-1] * (1 - multiplier))
    return ema

# Function to calculate ATR
def calculate_atr(high, low, close, period=14):
    """Calculate ATR"""
    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    tr[0] = tr1[0]  # First value
    atr = np.zeros_like(tr)
    atr[period-1] = np.mean(tr[0:period])  # Seed
    for i in range(period, len(tr)):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    return atr

# Function to backtest the strategy on a dataframe and return trades with times
def backtest_strategy_with_trades(df):
    """
    Backtest the EMA crossover strategy with ATR stop on the given dataframe.
    Returns a list of trades with entry and exit times.
    """
    if len(df) < max(ema_slow, 30):
        return []
    
    # Calculate indicators
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    
    ema_fast_val = calculate_ema(ema_fast, close)
    ema_slow_val = calculate_ema(ema_slow, close)
    atr_val = calculate_atr(high, low, close, atr_period)
    
    # Generate signals: 1 for long, 0 for no position (long-only)
    signal = np.where(ema_fast_val > ema_slow_val, 1, 0)
    # Next-bar execution: position at bar i is signal at bar i-1
    position = np.zeros_like(signal)
    position[1:] = signal[:-1]
    
    # Calculate ATR-based stop: stop_price = close - atr_mult * atr (for long)
    stop_price = close - atr_mult * atr_val
    
    # Simulate trades
    trades = []
    in_trade = False
    entry_price = 0.0
    entry_time = None
    
    for i in range(len(df)):
        # Check for entry: if we are not in a trade and position[i] == 1
        if not in_trade and position[i] == 1:
            entry_price = df['open'].iloc[i]
            entry_time = df.index[i]
            in_trade = True
        
        # Check for exit: if we are in a trade and either:
        # 1. position[i] == 0 (signal to exit)
        # 2. low[i] <= stop_price[i] (stop loss hit)
        if in_trade:
            exit = False
            exit_price = None
            
            # Check stop loss
            if low[i] <= stop_price[i]:
                exit = True
                exit_price = stop_price[i]  # Exit at stop price
            # Check signal exit
            elif position[i] == 0:
                exit = True
                exit_price = df['close'].iloc[i]  # Exit at close
            
            if exit:
                # Calculate trade return
                trade_return = (exit_price - entry_price) / entry_price
                # Apply fees and slippage (round-trip)
                trade_return -= fees_rt + slippage_per_trade
                
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'return': trade_return
                })
                
                in_trade = False
    
    return trades

# We'll audit dependence by checking for overlapping trades and clustered signals
results = {}
for tf_name, df in all_data.items():
    print(f"\nProcessing {tf_name}...")
    # We'll use the original walkforward parameters to get trades
    train_frac = 0.60
    step_frac = 0.20
    test_frac = 0.20
    
    n = len(df)
    if n < 100:
        results[tf_name] = None
        continue
        
    train_end_idx = int(n * train_frac)
    step_size = int(n * step_frac)
    
    # We'll collect all trades from all windows
    all_trades = []
    
    max_windows = 8  # as in original
    for w in range(max_windows):
        train_start_idx = w * step_size
        train_end_w = train_end_idx + w * step_size
        test_start_idx = train_end_w
        test_end_idx = min(test_start_idx + int(n * test_frac), n)
        
        if test_end_idx - test_start_idx < 50:  # Minimum test size
            break
        
        test_df = df.iloc[test_start_idx:test_end_idx].copy()
        trades = backtest_strategy_with_trades(test_df)
        for trade in trades:
            trade['window'] = w
            all_trades.append(trade)
    
    if len(all_trades) == 0:
        results[tf_name] = {
            'overlapping_trades': 0,
            'clustered_signals': 0,
            'effective_independent_sample_size': 0,
            'dependence_measure': 'N/A'
        }
        continue
    
    # Check for overlapping trades: two trades overlap if the entry of one is before the exit of the other
    # We'll sort trades by entry time
    sorted_trades = sorted(all_trades, key=lambda x: x['entry_time'])
    overlapping_count = 0
    for i in range(len(sorted_trades)-1):
        if sorted_trades[i]['exit_time'] > sorted_trades[i+1]['entry_time']:
            overlapping_count += 1
    
    # Check for clustered signals: we'll look at the time between consecutive entries
    # If the time between entries is less than a threshold (e.g., 1 hour), we consider it clustered
    entry_times = [t['entry_time'] for t in sorted_trades]
    time_diffs = []
    for i in range(len(entry_times)-1):
        diff = (entry_times[i+1] - entry_times[i]).total_seconds()
        time_diffs.append(diff)
    # We'll set a threshold of 1 hour = 3600 seconds
    clustered_count = sum(1 for diff in time_diffs if diff < 3600)
    
    # Effective independent sample size: we'll use the formula: n_eff = n / (1 + 2 * sum of autocorrelations)
    # We'll approximate by using the trades returns and checking autocorrelation
    returns = [t['return'] for t in all_trades]
    if len(returns) > 1:
        # Compute autocorrelation at lag 1
        mean_return = np.mean(returns)
        var_return = np.var(returns)
        if var_return > 0:
            autocorr_lag1 = np.sum((returns[:-1] - mean_return) * (returns[1:] - mean_return)) / (len(returns) * var_return)
        else:
            autocorr_lag1 = 0.0
        # Effective sample size approximation for autocorrelated data
        n_eff = len(returns) / (1 + 2 * autocorr_lag1) if autocorr_lag1 > 0 else len(returns)
    else:
        n_eff = len(returns)
    
    results[tf_name] = {
        'overlapping_trades': overlapping_count,
        'clustered_signals': clustered_count,
        'effective_independent_sample_size': n_eff,
        'dependence_measure': 'Low' if n_eff > len(returns)*0.5 else 'High'
    }

# Save results
output_file = '/Users/aryanagarwal/experiments/profitability_lab/hostile_test/dependence_audit_results.json'
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_file}")

# Create checkpoint
checkpoint_file = '/Users/aryanagarwal/VOL_HOSTILE_09_DEPENDENCE.json'
# We'll compute hashes
with open('/Users/aryanagarwal/phase9_dependence.py', 'rb') as f:
    script_hash = hashlib.sha256(f.read()).hexdigest()
with open(output_file, 'rb') as f:
    output_hash = hashlib.sha256(f.read()).hexdigest()

checkpoint = {
    'checkpoint': 'VOL_HOSTILE_09_DEPENDENCE',
    'timestamp': datetime.now().isoformat(),
    'data_hash': '743efdef3f7860d580fcb11c4c8f42589bb328b7ab4584b9ab72f9803e7f8d1e',
    'script_file': 'phase9_dependence.py',
    'script_hash': script_hash,
    'output_file': output_file,
    'output_hash': output_hash,
    'git_commit': '48070e9738174ee2fe297ef63d5757f5259596ff',
    'parameters': {
        'ema_fast': ema_fast,
        'ema_slow': ema_slow,
        'atr_mult': atr_mult,
        'risk_per_trade': risk_per_trade,
        'fees_rt': fees_rt,
        'slippage_per_trade': slippage_per_trade,
        'atr_period': atr_period,
        'train_frac': 0.60,
        'step_frac': 0.20,
        'test_frac': 0.20
    },
    'test_result': {
        'results': results
    }
}

with open(checkpoint_file, 'w') as f:
    json.dump(checkpoint, f, indent=2)

print(f"Checkpoint saved to {checkpoint_file}")
