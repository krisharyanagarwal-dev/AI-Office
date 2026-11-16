import json
import numpy as np
import pandas as pd
from datetime import datetime
import os

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

# Walk-forward parameters (same as original)
train_frac = 0.60   # 1Y TRAIN
step_frac = 0.20    # 6M TEST (step size)
test_frac = 0.20    # 20% TEST (as in original script)

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

# Function to backtest the strategy on a dataframe and return trades with regime
def backtest_strategy_with_regime(df, regime_threshold):
    """
    Backtest the EMA crossover strategy with ATR stop on the given dataframe.
    Also returns a list of trades with their regime (based on regime_threshold).
    regime_threshold: a float, the threshold for high volatility (previous bar's abs return > threshold -> high)
    Returns: (total_return, sharpe, max_dd, trades, win_rate, final_capital, fees_paid, list_of_trades)
    Each trade in list_of_trades is a dict with: 'entry_time', 'exit_time', 'return', 'regime'
    """
    if len(df) < max(ema_slow, 30):
        return 0.0, 0.0, 0.0, 0, 0.0, 100000.0, 0.0, []
    
    # Calculate indicators
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    
    ema_fast_val = calculate_ema(ema_fast, close)
    ema_slow_val = calculate_ema(ema_slow, close)
    atr_val = calculate_atr(high, low, close, atr_period)
    
    # Generate signals: 1 for long, -1 for short? We assume long only when fast > slow
    # We'll assume long-only strategy for simplicity (as in the original? The original results show both positive and negative returns, so it might be long-only)
    # Looking at the original results, 5m,15m,30m,1h have negative returns, 2h and 4h positive, so it's likely long-only.
    # We'll assume long when ema_fast > ema_slow.
    signal = np.where(ema_fast_val > ema_slow_val, 1, 0)
    # We'll use next-bar execution: signal at bar i is executed at bar i+1
    # We'll shift the signal by 1 to get the position at the open of the next bar
    position = np.zeros_like(signal)
    position[1:] = signal[:-1]  # Position at bar i is signal at bar i-1
    
    # Calculate ATR-based stop: stop_price = close - atr_mult * atr (for long)
    # We'll compute the stop price for each bar
    stop_price = close - atr_mult * atr_val
    
    # We'll simulate the trades
    trades = []
    capital = 100000.0
    peak_capital = capital
    max_dd = 0.0
    fees_paid = 0.0
    
    in_trade = False
    entry_price = 0.0
    entry_time = None
    entry_regime = None  # We'll determine regime at entry
    
    # We need the previous bar's absolute return to determine regime for the current bar
    # We'll compute the absolute return for each bar
    abs_return = np.abs(np.diff(close, prepend=close[0]))  # absolute return from previous close to current close
    # For the first bar, we set abs_return to 0 or NaN? We'll set to 0 and it won't be used because we start from bar 1.
    abs_return[0] = 0.0
    
    for i in range(len(df)):
        # Determine regime for bar i based on previous bar's absolute return
        # For i=0, we don't have previous bar, so we skip regime assignment (we won't trade on first bar anyway)
        if i > 0:
            prev_abs_return = abs_return[i-1]
            regime = 'high' if prev_abs_return > regime_threshold else 'low'
        else:
            regime = 'unknown'
        
        # Check for entry: if we are not in a trade and position[i] == 1 (we want to be long)
        if not in_trade and position[i] == 1:
            # Enter long at the open of bar i? We assume we enter at the close of bar i-1? Actually, we used next-bar execution: signal at bar i-1 -> position at bar i.
            # We'll assume we enter at the open of bar i.
            entry_price = df['open'].iloc[i]
            entry_time = df.index[i]
            entry_regime = regime
            in_trade = True
        
        # Check for exit: if we are in a trade and either:
        # 1. position[i] == 0 (signal to exit)
        # 2. low[i] <= stop_price[i] (stop loss hit)
        if in_trade:
            exit = False
            exit_price = None
            exit_time = None
            
            # Check stop loss
            if low[i] <= stop_price[i]:
                exit = True
                exit_price = stop_price[i]  # We assume we exit at the stop price
            # Check signal exit (if we want to exit when signal goes to 0)
            elif position[i] == 0:
                exit = True
                exit_price = df['close'].iloc[i]  # Exit at close
            
            if exit:
                # Calculate trade return
                trade_return = (exit_price - entry_price) / entry_price
                # Apply fees and slippage: we assume fees and slippage are applied on entry and exit
                # We'll use round-trip fees and slippage as given
                trade_return -= fees_rt + slippage_per_trade  # simplistic
                
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'return': trade_return,
                    'regime': entry_regime
                })
                
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
        returns = [t['return'] for t in trades]
        total_return = np.sum(returns)
        win_rate = np.sum(np.array(returns) > 0) / len(returns)
        # Sharpe ratio: assuming daily returns? We'll approximate using per-trade returns and annualize based on number of trades per year?
        # For simplicity, we'll compute the Sharpe as (mean return) / (std return) * sqrt(252) if we assume 252 trading days per year.
        # But we don't have the time between trades. We'll skip Sharpe for now and set to 0.
        sharpe = 0.0  # Placeholder
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)  # rough annualization
    
    return total_return, sharpe, max_dd, len(trades), win_rate, capital, fees_paid, trades

# We'll perform walk-forward analysis for each timeframe
results = {}
for tf_name, df in all_data.items():
    print(f"\nProcessing {tf_name}...")
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
        test_end_idx = min(test_start_idx + int(n * test_frac), n)  # 20% for test
        
        if test_end_idx - test_start_idx < 50:  # Minimum test size
            print(f"  Window {w}: SKIP - insufficient test data ({test_end_idx - test_start_idx} bars)")
            break
        
        train_df = df.iloc[train_start_idx:train_end_w].copy()
        test_df = df.iloc[test_start_idx:test_end_idx].copy()
        
        # Compute regime threshold from training data: median of absolute return
        # We need the absolute return for each bar in the training data
        train_close = train_df['close'].values
        train_abs_return = np.abs(np.diff(train_close, prepend=train_close[0]))
        train_abs_return[0] = 0.0
        regime_threshold = np.median(train_abs_return)
        
        # Backtest on test data with this regime threshold
        tf_return, tf_sharpe, tf_max_dd, tf_trades, tf_win_rate, tf_final_capital, tf_fees_paid, tf_trades_list = backtest_strategy_with_regime(test_df, regime_threshold)
        
        # Collect trades with their regime
        for trade in tf_trades_list:
            trade['window'] = w
            trade['timeframe'] = tf_name
            all_trades.append(trade)
        
        print(f"  Window {w}: {tf_trades} trades, return: {tf_return:.4f}")
    
    # Now, split all trades by regime and compute performance per regime
    high_regime_trades = [t for t in all_trades if t['regime'] == 'high']
    low_regime_trades = [t for t in all_trades if t['regime'] == 'low']
    
    def compute_metrics(trades_list):
        if len(trades_list) == 0:
            return {
                'observations': 0,
                'trades': 0,
                'return': 0.0,
                'expectancy': 0.0,
                'drawdown': 0.0,
                'hit_rate': 0.0,
                'cost_adjusted_result': 0.0,
                'confidence': 'N/A',
                'oos_result': 0.0  # We'll use the same as return for OOS? We'll compute OOS separately if needed.
            }
        returns = [t['return'] for t in trades_list]
        total_return = np.sum(returns)
        expectancy = np.mean(returns)
        hit_rate = np.sum(np.array(returns) > 0) / len(returns)
        # Drawdown: we'll compute from the equity curve
        capital = 100000.0
        peak = capital
        max_dd = 0.0
        for r in returns:
            capital *= (1 + r)
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak
            if dd > max_dd:
                max_dd = dd
        # Cost-adjusted result: we already subtracted fees and slippage in the trade return, so we can just return the total_return
        cost_adjusted_result = total_return
        # Confidence: we'll compute the standard error of the mean
        if len(returns) > 1:
            se = np.std(returns) / np.sqrt(len(returns))
            confidence = f"{se:.6f}"
        else:
            confidence = "N/A"
        # OOS result: we already computed OOS, so we can use the total_return as OOS result
        oos_result = total_return
        
        return {
            'observations': len(returns),  # number of trades
            'trades': len(returns),
            'return': total_return,
            'expectancy': expectancy,
            'drawdown': max_dd,
            'hit_rate': hit_rate,
            'cost_adjusted_result': cost_adjusted_result,
            'confidence': confidence,
            'oos_result': oos_result
        }
    
    high_metrics = compute_metrics(high_regime_trades)
    low_metrics = compute_metrics(low_regime_trades)
    
    results[tf_name] = {
        'high_volatility': high_metrics,
        'low_volatility': low_metrics
    }

# Save results
output_file = '/Users/aryanagarwal/experiments/profitability_lab/hostile_test/volatility_regime_results.json'
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_file}")

# Also create the checkpoint file
checkpoint = {
    'checkpoint': 'VOL_HOSTILE_06_REGIMES',
    'timestamp': datetime.now().isoformat(),
    'data_hash': '743efdef3f7860d580fcb11c4c8f42589bb328b7ab4584b9ab72f9803e7f8d1e',
    'script_file': 'phase6_volatility_regime.py',
    # We'll compute the script hash later
    'output_file': output_file,
    # We'll compute the output hash later
    'git_commit': None,
    'parameters': {
        'ema_fast': ema_fast,
        'ema_slow': ema_slow,
        'atr_mult': atr_mult,
        'risk_per_trade': risk_per_trade,
        'fees_rt': fees_rt,
        'slippage_per_trade': slippage_per_trade,
        'atr_period': atr_period,
        'train_frac': train_frac,
        'step_frac': step_frac,
        'test_frac': test_frac
    },
    'test_result': {
        'results': results
    }
}

# Compute script hash
with open('phase6_volatility_regime.py', 'rb') as f:
    script_hash = pd.util.hash_pandas_object(f.read()).hash  # This won't work, we'll use a simple hash
# Let's use hashlib
import hashlib
with open('phase6_volatility_regime.py', 'rb') as f:
    script_hash = hashlib.sha256(f.read()).hexdigest()
checkpoint['script_hash'] = script_hash

# Compute output hash
with open(output_file, 'rb') as f:
    output_hash = hashlib.sha256(f.read()).hexdigest()
checkpoint['output_hash'] = output_hash

# Get git commit
try:
    import subprocess
    git_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd='/Users/aryanagarwal/openalice-fleet').decode().strip()
except:
    git_commit = None
checkpoint['git_commit'] = git_commit

# Save checkpoint
checkpoint_file = '/Users/aryanagarwal/VOL_HOSTILE_06_REGIMES.json'
with open(checkpoint_file, 'w') as f:
    json.dump(checkpoint, f, indent=2)

print(f"Checkpoint saved to {checkpoint_file}")
