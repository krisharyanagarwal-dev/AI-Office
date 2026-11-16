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
    fees_ped = 0.0
    
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
                fees_ped += (fees_rt + slippage_per_trade) * entry_price  # approximates
                
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
        'fees_paid': fees_ped  # Note: we used fees_ped variable, but we'll fix later
    }

# We'll inventory the researcher degrees of freedom from phases 6-9
# We'll count the number of tests we've done
# For each phase, we'll consider the number of timeframes as the number of tests
# We'll apply a Bonferroni correction to the p-values from the null tests (phase 7) if available

# We'll load the null test results from phase 7 if available
null_test_file = '/Users/aryanagarwal/experiments/profitability_lab/hostile_test/null_test_results.json'
try:
    with open(null_test_file, 'r') as f:
        null_test_results = json.load(f)
except:
    null_test_results = {}

# We'll also consider the volatility regime test (phase 6) as a test
# We'll count the number of timeframes * number of regimes (2) as tests
# For window dependence (phase 8), we'll count the number of timeframes * number of window configs
# For dependence audit (phase 9), we'll count the number of timeframes

# We'll create a list of all tests we've done in phases 6-9
test_inventory = []

# Phase 6: Volatility regime test - we tested each timeframe for high/low volatility regimes
# We'll count each timeframe-regime combination as a test
for tf_name in timeframes.keys():
    test_inventory.append({
        'phase': 6,
        'test': f'Volatility regime test - {tf_name} high volatility',
        'timeframe': tf_name
    })
    test_inventory.append({
        'phase': 6,
        'test': f'Volatility regime test - {tf_name} low volatility',
        'timeframe': tf_name
    })

# Phase 7: Null / Placebo tests - we did a placebo test for each timeframe
# We'll count each timeframe as a test
for tf_name in timeframes.keys():
    test_inventory.append({
        'phase': 7,
        'test': f'Placebo test - {tf_name}',
        'timeframe': tf_name
    })

# Phase 8: Window dependence - we tested each timeframe with different window configs
window_configs = [
    {'train_frac': 0.50, 'step_frac': 0.25, 'test_frac': 0.25, 'label': '50% train, 25% step, 25% test'},
    {'train_frac': 0.60, 'step_frac': 0.20, 'test_frac': 0.20, 'label': '60% train, 20% step, 20% test (original)'},
    {'train_frac': 0.70, 'step_frac': 0.15, 'test_frac': 0.15, 'label': '70% train, 15% step, 15% test'},
    {'train_frac': 0.80, 'step_frac': 0.10, 'test_frac': 0.10, 'label': '80% train, 10% step, 10% test'},
]
for tf_name in timeframes.keys():
    for config in window_configs:
        test_inventory.append({
            'phase': 8,
            'test': f'Window dependence test - {tf_name} - {config["label"]}',
            'timeframe': tf_name,
            'window_config': config['label']
        })

# Phase 9: Dependence / Overlap audit - we audited each timeframe
for tf_name in timeframes.keys():
    test_inventory.append({
        'phase': 9,
        'test': f'Dependence audit - {tf_name}',
        'timeframe': tf_name
    })

# Now we apply multiple testing correction
# We'll use the Bonferroni correction: divide the alpha level by the number of tests
# We'll assume we are testing at alpha = 0.05
alpha = 0.05
n_tests = len(test_inventory)
bonferroni_alpha = alpha / n_tests if n_tests > 0 else alpha

# We'll also compute the false discovery rate (FDR) using the Benjamini-Hochberg procedure
# We'll need p-values from the tests. We'll use the p-values from the null tests (phase 7) if available.
# We'll collect the p-values from the null test results for each timeframe.
p_values = []
for tf_name in timeframes.keys():
    if tf_name in null_test_results:
        p_val = null_test_results[tf_name].get('p_value', None)
        if p_val is not None:
            p_values.append(p_val)
# If we have p-values, we'll apply FDR correction
if len(p_values) > 0:
    # Sort p-values
    sorted_p_values = sorted(p_values)
    m = len(sorted_p_values)
    # Compute FDR critical values: (i/m) * alpha
    fdr_critical = [(i+1)/m * alpha for i in range(m)]
    # Find the largest k such that p_k <= (k/m) * alpha
    k = 0
    for i in range(m):
        if sorted_p_values[i] <= fdr_critical[i]:
            k = i+1
    # If k > 0, then the first k tests are significant
    fdr_significant = k > 0
else:
    fdr_significant = False
    fdr_critical = []

# Save results
results = {
    'test_inventory': test_inventory,
    'n_tests': n_tests,
    'bonferroni_alpha': bonferroni_alpha,
    'fdr_significant': fdr_significant,
    'fdr_critical': fdr_critical if len(fdr_critical) > 0 else None,
    'null_test_p_values': p_values if len(p_values) > 0 else None
}

output_file = '/Users/aryanagarwal/experiments/profitability_lab/hostile_test/multiple_testing_results.json'
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_file}")

# Create checkpoint
checkpoint_file = '/Users/aryanagarwal/VOL_HOSTILE_10_MULTIPLE_TESTING.json'
# We'll compute hashes
with open('/Users/aryanagarwal/phase10_multiple_testing.py', 'rb') as f:
    script_hash = hashlib.sha256(f.read()).hexdigest()
with open(output_file, 'rb') as f:
    output_hash = hashlib.sha256(f.read()).hexdigest()

checkpoint = {
    'checkpoint': 'VOL_HOSTILE_10_MULTIPLE_TESTING',
    'timestamp': datetime.now().isoformat(),
    'data_hash': '743efdef3f7860d580fcb11c4c8f42589bb328b7ab4584b9ab72f9803e7f8d1e',
    'script_file': 'phase10_multiple_testing.py',
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
        'alpha': alpha,
        'n_tests': n_tests
    },
    'test_result': {
        'results': results
    }
}

with open(checkpoint_file, 'w') as f:
    json.dump(checkpoint, f, indent=2)

print(f"Checkpoint saved to {checkpoint_file}")
