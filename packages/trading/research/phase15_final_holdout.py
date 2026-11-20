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

# Function to backtest the strategy on a dataframe and return performance metrics
def backtest_strategy(df):
    """
    Backtest the EMA crossover strategy with ATR stop on the given dataframe.
    Returns a dict with performance metrics.
    """
    if len(df) < max(ema_slow, 30):
        return {'total_return': 0.0, 'sharpe': 0.0, 'max_dd': 0.0, 'trades': 0, 'win_rate': 0.0, 'final_capital': 100000.0, 'fees_paid': 0.0}
    
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
    capital = 100000.0
    peak_capital = capital
    max_dd = 0.0
    fees_paid = 0.0
    
    in_trade = False
    entry_price = 0.0
    
    for i in range(len(df)):
        # Check for entry: if we are not in a trade and position[i] == 1
        if not in_trade and position[i] == 1:
            entry_price = df['open'].iloc[i]
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
                
                trades.append(trade_return)
                
                # Update capital
                capital *= (1 + trade_return)
                fees_paid += (fees_rt + slippage_per_trade) * entry_price  # approximates
                
                # Update peak capital and max drawdown
                if capital > peak_capital:
                    peak_capital = capital
                dd = (peak_capital - capital) / peak_capital
                if dd > max_dd:
                    max_dd = dd
                
                in_trade = False
    
    # Calculate performance metrics
    if len(trades) == 0:
        total_return = 0.0
        sharpe = 0.0
        win_rate = 0.0
    else:
        returns = np.array(trades)
        total_return = np.sum(returns)
        win_rate = np.sum(returns > 0) / len(returns)
        # Sharpe ratio: approximate
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)  # annualize
        else:
            sharpe = 0.0
    
    return {
        'total_return': total_return,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'trades': len(trades),
        'win_rate': win_rate,
        'final_capital': capital,
        'fees_paid': fees_paid
    }

# We'll freeze the methodology and parameters as above.
# Now we define the final holdout period.
# We'll use the original walkforward parameters: train_frac=0.60, step_frac=0.20, test_frac=0.20
# We'll use the last possible window for training and then the next period as holdout.
# Alternatively, we can use a period after the end of the data used in the walkforward.

# We'll use the following approach:
# We'll use the first 80% of the data for development (including walkforward training and testing),
# and the last 20% as the final holdout.
# This is a common practice to avoid overfitting.

n_total = len(data_5m)
holdout_start_idx = int(n_total * 0.80)  # Start of holdout at 80% of data
holdout_df = data_5m.iloc[holdout_start_idx:].copy()

print(f"Total data: {n_total} bars")
print(f"Holdout data: {len(holdout_df)} bars from {holdout_df.index[0]} to {holdout_df.index[-1]}")

# We'll resample the holdout data to each timeframe and backtest the strategy
holdout_results = {}
for tf_name, rule in timeframes.items():
    print(f"\nProcessing {tf_name} for holdout...")
    holdout_tf = resample_ohlcv(holdout_df, rule)
    if len(holdout_tf) < 100:
        holdout_results[tf_name] = None
        continue
    result = backtest_strategy(holdout_tf)
    holdout_results[tf_name] = result

# We'll also compute the performance on the development data (the first 80%) for comparison
# We'll use the same walkforward parameters to get the average performance on the development data.
# We'll use the original walkforward to compute the average performance on the development data.
development_df = data_5m.iloc[:holdout_start_idx].copy()
print(f"\nDevelopment data: {len(development_df)} bars from {development_df.index[0]} to {development_df.index[-1]}")

# We'll run the walkforward on the development data to get the average performance
development_results = {}
for tf_name, rule in timeframes.items():
    print(f"\nProcessing {tf_name} for development (walkforward)...")
    df_tf = resample_ohlcv(development_df, rule)
    if len(df_tf) < 100:
        development_results[tf_name] = None
        continue
    n = len(df_tf)
    train_end_idx = int(n * 0.60)
    step_size = int(n * 0.20)
    
    all_trades = []
    max_windows = 8
    for w in range(max_windows):
        train_start_idx = w * step_size
        train_end_w = train_end_idx + w * step_size
        test_start_idx = train_end_w
        test_end_idx = min(test_start_idx + int(n * 0.20), n)
        
        if test_end_idx - test_start_idx < 50:
            break
        
        train_df = df_tf.iloc[train_start_idx:train_end_w].copy()
        test_df = df_tf.iloc[test_start_idx:test_end_idx].copy()
        
        result = backtest_strategy(test_df)
        all_trades.append(result['total_return'])
    
    if len(all_trades) > 0:
        mean_return = np.mean(all_trades)
        std_return = np.std(all_trades)
    else:
        mean_return = 0.0
        std_return = 0.0
    
    development_results[tf_name] = {
        'mean_return': mean_return,
        'std_return': std_return,
        'num_windows': len(all_trades)
    }

# Save results
results = {
    'holdout_results': holdout_results,
    'development_results': development_results,
    'holdout_definition': {
        'holdout_start_index': holdout_start_idx,
        'holdout_start_date': holdout_df.index[0].isoformat() if len(holdout_df) > 0 else None,
        'holdout_end_date': holdout_df.index[-1].isoformat() if len(holdout_df) > 0 else None,
        'development_end_index': holdout_start_idx - 1,
        'development_end_date': development_df.index[-1].isoformat() if len(development_df) > 0 else None
    },
    'frozen_methodology': {
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
    }
}

output_file = '/Users/aryanagarwal/experiments/profitability_lab/hostile_test/final_holdout_results.json'
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_file}")

# Create checkpoint
checkpoint_file = '/Users/aryanagarwal/VOL_HOSTILE_15_FINAL_HOLDOUT.json'
# We'll compute hashes
with open('/Users/aryanagarwal/phase15_final_holdout.py', 'rb') as f:
    script_hash = hashlib.sha256(f.read()).hexdigest()
with open(output_file, 'rb') as f:
    output_hash = hashlib.sha256(f.read()).hexdigest()

checkpoint = {
    'checkpoint': 'VOL_HOSTILE_15_FINAL_HOLDOUT',
    'timestamp': datetime.now().isoformat(),
    'data_hash': '743efdef3f7860d580fcb11c4c8f42589bb328b7ab4584b9ab72f9803e7f8d1e',
    'script_file': 'phase15_final_holdout.py',
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
        'holdout_start_index': holdout_start_idx,
        'holdout_size': len(holdout_df),
        'development_size': len(development_df)
    },
    'test_result': {
        'results': results
    }
}

with open(checkpoint_file, 'w') as f:
    json.dump(checkpoint, f, indent=2)

print(f"Checkpoint saved to {checkpoint_file}")
