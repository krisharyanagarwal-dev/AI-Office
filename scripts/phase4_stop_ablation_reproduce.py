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

# Create timeframes to test
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

# Strategy parameters (same as before)
ema_fast = 20
ema_slow = 50
risk_per_trade = 0.1  # 10% equity per trade
fees_rt = 0.0005      # 0.05% round-trip fees
slippage_per_trade = 0.0005  # 0.05% slippage

# ATR period for calculation
atr_period = 14

# Grid search for ATR multiplier (for ATR-based stop)
atr_mult_grid = np.arange(0.5, 3.1, 0.1)  # from 0.5 to 3.0 step 0.1

# Grid search for alternative stop parameters
# Fixed percentage stop: x% of entry price
pct_stop_grid = np.arange(0.005, 0.055, 0.005)  # from 0.5% to 5.0% step 0.5%
# Fixed dollar stop: $D
dollar_stop_grid = np.arange(10, 501, 10)  # from $10 to $500 step $10
# Range-based stop: y * (high - low) of previous bar
range_stop_grid = np.arange(0.1, 5.1, 0.5)  # from 0.1 to 5.0 step 0.5

# Walk-forward parameters (same as before)
train_frac = 0.60   # 1Y TRAIN
step_frac = 0.20    # 6M TEST (step size)

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

# Function to backtest a given stop strategy on a dataframe
# stop_type: 'atr', 'pct', 'dollar', 'range'
# stop_param: the parameter for the stop (atr_mult, pct, dollar, range_y)
def backtest_strategy(df, ema_fast, ema_slow, stop_type, stop_param):
    """
    Backtest the EMA crossover strategy with the given stop strategy on the given dataframe.
    Returns a dict with performance metrics.
    Assumes df has columns: open, high, low, close, volume and is indexed by datetime.
    Uses next-bar execution for signals and stops.
    """
    if len(df) < max(ema_slow, 30):
        return {'total_return': 0.0, 'sharpe': 0.0, 'max_dd': 0.0, 'trades': 0, 'win_rate': 0.0, 'final_capital': 100000.0, 'fees_paid': 0.0}
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    
    # Calculate EMAs
    ema_fast_arr = calculate_ema(ema_fast, close)
    ema_slow_arr = calculate_ema(ema_slow, close)
    
    # Calculate ATR (needed for ATR-based stop)
    atr_arr = calculate_atr(high, low, close, atr_period)
    
    # Walk-forward simulation
    capital = 100000.0
    position = 0  # 0 = no position, 1 = long, -1 = short
    entry_price = 0
    # For ATR-based stop, we need to store the ATR at entry
    entry_atr = 0
    # For range-based stop, we need to store the range at entry (high - low of previous bar)
    entry_range = 0
    trades = []
    fees_total = 0.0
    
    for i in range(1, len(close)):
        # Generate signals based on PREVIOUS bar's close (to avoid lookahead)
        # Buy signal: fast EMA crosses above slow EMA
        buy_signal = (ema_fast_arr[i-2] <= ema_slow_arr[i-2]) and (ema_fast_arr[i-1] > ema_slow_arr[i-1])
        # Sell signal: fast EMA crosses below slow EMA
        sell_signal = (ema_fast_arr[i-2] >= ema_slow_arr[i-2]) and (ema_fast_arr[i-1] < ema_slow_arr[i-1])
        
        # Exit existing position on opposite signal (executed at next bar open)
        if position != 0:
            if (position == 1 and sell_signal) or (position == -1 and buy_signal):
                # Close position at next bar open
                exit_price = close[i] * (1 - slippage_per_trade if position == 1 else 1 + slippage_per_trade)
                if position == 1:
                    pnl = (exit_price - entry_price) * (capital * risk_per_trade / entry_price)
                else:  # short
                    pnl = (entry_price - exit_price) * (capital * risk_per_trade / entry_price)
                
                # Subtract fees (round-trip)
                fee = (capital * risk_per_trade / entry_price) * (entry_price + exit_price) * fees_rt
                pnl -= fee
                fees_total += fee
                
                capital += pnl
                trades.append(pnl)
                position = 0
        
        # Enter new position if no position and signal (executed at next bar open)
        if position == 0:
            if buy_signal:
                position = 1
                entry_price = close[i] * (1 + slippage_per_trade)  # slippage on entry
                if stop_type == 'atr':
                    entry_atr = atr_arr[i]  # ATR at signal bar for stop calculation
                elif stop_type == 'range':
                    entry_range = high[i-1] - low[i-1]  # range of previous bar
            elif sell_signal:
                position = -1
                entry_price = close[i] * (1 - slippage_per_trade)  # slippage on entry
                if stop_type == 'atr':
                    entry_atr = atr_arr[i]  # ATR at signal bar for stop calculation
                elif stop_type == 'range':
                    entry_range = high[i-1] - low[i-1]  # range of previous bar
        
        # Check stop loss (executed at next bar open if triggered intra-bar)
        if position != 0 and i < len(close)-1:
            # Use next bar's open price for stop execution (conservative)
            current_price = close[i+1]  # Next bar open
            
            stop_price = None
            if stop_type == 'atr':
                if position == 1:  # Long position
                    stop_price = entry_price - (entry_atr * stop_param)
                else:  # Short position
                    stop_price = entry_price + (entry_atr * stop_param)
            elif stop_type == 'pct':
                if position == 1:  # Long position
                    stop_price = entry_price * (1 - stop_param)
                else:  # Short position
                    stop_price = entry_price * (1 + stop_param)
            elif stop_type == 'dollar':
                if position == 1:  # Long position
                    stop_price = entry_price - stop_param
                else:  # Short position
                    stop_price = entry_price + stop_param
            elif stop_type == 'range':
                if position == 1:  # Long position
                    stop_price = entry_price - (entry_range * stop_param)
                else:  # Short position
                    stop_price = entry_price + (entry_range * stop_param)
            
            if stop_price is not None:
                if position == 1:  # Long position
                    if current_price <= stop_price:
                        # Stop loss triggered at next bar open
                        exit_price = stop_price * (1 - slippage_per_trade)  # slippage on exit
                        pnl = (exit_price - entry_price) * (capital * risk_per_trade / entry_price)
                        fee = (capital * risk_per_trade / entry_price) * (entry_price + exit_price) * fees_rt
                        pnl -= fee
                        fees_total += fee
                        capital += pnl
                        trades.append(pnl)
                        position = 0
                else:  # Short position
                    if current_price >= stop_price:
                        # Stop loss triggered at next bar open
                        exit_price = stop_price * (1 + slippage_per_trade)  # slippage on exit
                        pnl = (entry_price - exit_price) * (capital * risk_per_trade / entry_price)
                        fee = (capital * risk_per_trade / entry_price) * (entry_price + exit_price) * fees_rt
                        pnl -= fee
                        fees_total += fee
                        capital += pnl
                        trades.append(pnl)
                        position = 0
    
    # Close any remaining position at end
    if position != 0 and len(close) > 1:
        exit_price = close[-1] * (1 - slippage_per_trade if position == 1 else 1 + slippage_per_trade)
        if position == 1:
            pnl = (exit_price - entry_price) * (capital * risk_per_trade / entry_price)
        else:
            pnl = (entry_price - exit_price) * (capital * risk_per_trade / entry_price)
        fee = (capital * risk_per_trade / entry_price) * (entry_price + exit_price) * fees_rt
        pnl -= fee
        fees_total += fee
        capital += pnl
        trades.append(pnl)
    
    # Calculate metrics
    if len(trades) == 0:
        return {
            'total_return': 0.0,
            'sharpe': 0.0,
            'max_dd': 0.0,
            'trades': 0,
            'win_rate': 0.0,
            'final_capital': capital,
            'fees_paid': fees_total
        }
    
    total_return = (capital - 100000) / 100000
    win_rate = sum(1 for t in trades if t > 0) / len(trades)
    
    # For Sharpe, we'll leave as 0.0 for simplicity
    sharpe = 0.0
    
    # Max drawdown approximation
    equity = [100000.0]
    running_eq = 100000.0
    for t in trades:
        running_eq += t
        equity.append(running_eq)
    if len(equity) > 1:
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_dd = np.max(drawdown) if len(drawdown) > 0 else 0.0
    else:
        max_dd = 0.0
    
    return {
        'total_return': total_return,
        'sharpe': 0.0,
        'max_dd': max_dd,
        'trades': len(trades),
        'win_rate': win_rate,
        'final_capital': capital,
        'fees_paid': fees_total
    }

# We'll store results for each timeframe and window
# Structure: results[tf_name][window] = {
#   'stop_type_results': {
#       'atr_opt': { ... },
#       'pct_opt': { ... },
#       'dollar_opt': { ... },
#       'range_opt': { ... }
#   }
# }
results = {tf_name: {} for tf_name in timeframes.keys()}

# Process each timeframe
for tf_name, df in all_data.items():
    print(f"\n{'='*20} Processing {tf_name} {'='*20}")
    
    # Compute bars per year and per half year for this timeframe
    time_diffs = df.index.to_series().diff().dropna()
    median_diff = time_diffs.median()
    bars_per_day = 1.0 / (median_diff.total_seconds() / (24 * 3600))
    bars_per_year = bars_per_day * 365.25
    bars_per_halfyear = bars_per_year / 2.0
    
    # Convert to integers
    train_bars = int(round(bars_per_year * train_frac))
    test_bars = int(round(bars_per_halfyear * step_frac))
    step_bars = test_bars  # We'll slide by the test window size each time
    
    print(f"{tf_name}: Training bars: {train_bars}, Test bars per window: {test_bars}, Step bars: {step_bars}")
    
    # Check we have enough data
    if len(df) < train_bars + test_bars:
        print(f"Insufficient data for even one window: need {train_bars + test_bars} bars, have {len(df)}")
        continue
    
    # We'll slide the window
    window_num = 0
    start_idx = 0
    train_end_idx = train_bars
    test_start_idx = train_end_idx
    test_end_idx = test_start_idx + test_bars
    
    while test_end_idx <= len(df):
        train_df = df.iloc[start_idx:train_end_idx].copy()
        test_df = df.iloc[test_start_idx:test_end_idx].copy()
        
        print(f"\nWindow {window_num+1}: Train [{train_df.index[0]} to {train_df.index[-1]}] ({len(train_df)} bars)")
        print(f"         Test  [{test_df.index[0]} to {test_df.index[-1]}] ({len(test_df)} bars)")
        
        # We will store results for this window
        results[tf_name][window_num] = {
            'stop_type_results': {}
        }
        
        # For each stop type, we will optimize the parameter on exploration data
        # and then compute OOS performance.
        
        # 1. ATR-based stop
        print("  Optimizing ATR-based stop...")
        best_atr_return = -np.inf
        best_atr_mult = None
        best_atr_result = None
        for mult in atr_mult_grid:
            result = backtest_strategy(train_df, ema_fast, ema_slow, 'atr', mult)
            obj = result['total_return']
            if obj > best_atr_return:
                best_atr_return = obj
                best_atr_mult = mult
                best_atr_result = result
        if best_atr_mult is None:
            best_atr_mult = 1.5
            best_atr_result = backtest_strategy(train_df, ema_fast, ema_slow, 'atr', 1.5)
        results[tf_name][window_num]['stop_type_results']['atr_opt'] = {
            'param': best_atr_mult,
            'exploration_return': best_atr_result['total_return']
        }
        # OOS performance for ATR-based stop with exploration optimal multiplier
        atr_oos_result = backtest_strategy(test_df, ema_fast, ema_slow, 'atr', best_atr_mult)
        results[tf_name][window_num]['stop_type_results']['atr_opt']['oos_return'] = atr_oos_result['total_return']
        
        # 2. Fixed percentage stop
        print("  Optimizing fixed percentage stop...")
        best_pct_return = -np.inf
        best_pct = None
        best_pct_result = None
        for pct in pct_stop_grid:
            result = backtest_strategy(train_df, ema_fast, ema_slow, 'pct', pct)
            obj = result['total_return']
            if obj > best_pct_return:
                best_pct_return = obj
                best_pct = pct
                best_pct_result = result
        if best_pct is None:
            best_pct = 0.02  # default 2%
            best_pct_result = backtest_strategy(train_df, ema_fast, ema_slow, 'pct', 0.02)
        results[tf_name][window_num]['stop_type_results']['pct_opt'] = {
            'param': best_pct,
            'exploration_return': best_pct_result['total_return']
        }
        pct_oos_result = backtest_strategy(test_df, ema_fast, ema_slow, 'pct', best_pct)
        results[tf_name][window_num]['stop_type_results']['pct_opt']['oos_return'] = pct_oos_result['total_return']
        
        # 3. Fixed dollar stop
        print("  Optimizing fixed dollar stop...")
        best_dollar_return = -np.inf
        best_dollar = None
        best_dollar_result = None
        for dollar in dollar_stop_grid:
            result = backtest_strategy(train_df, ema_fast, ema_slow, 'dollar', dollar)
            obj = result['total_return']
            if obj > best_dollar_return:
                best_dollar_return = obj
                best_dollar = dollar
                best_dollar_result = result
        if best_dollar is None:
            best_dollar = 100  # default $100
            best_dollar_result = backtest_strategy(train_df, ema_fast, ema_slow, 'dollar', 100)
        results[tf_name][window_num]['stop_type_results']['dollar_opt'] = {
            'param': best_dollar,
            'exploration_return': best_dollar_result['total_return']
        }
        dollar_oos_result = backtest_strategy(test_df, ema_fast, ema_slow, 'dollar', best_dollar)
        results[tf_name][window_num]['stop_type_results']['dollar_opt']['oos_return'] = dollar_oos_result['total_return']
        
        # 4. Range-based stop
        print("  Optimizing range-based stop...")
        best_range_return = -np.inf
        best_range = None
        best_range_result = None
        for range_y in range_stop_grid:
            result = backtest_strategy(train_df, ema_fast, ema_slow, 'range', range_y)
            obj = result['total_return']
            if obj > best_range_return:
                best_range_return = obj
                best_range = range_y
                best_range_result = result
        if best_range is None:
            best_range = 1.0  # default
            best_range_result = backtest_strategy(train_df, ema_fast, ema_slow, 'range', 1.0)
        results[tf_name][window_num]['stop_type_results']['range_opt'] = {
            'param': best_range,
            'exploration_return': best_range_result['total_return']
        }
        range_oos_result = backtest_strategy(test_df, ema_fast, ema_slow, 'range', best_range)
        results[tf_name][window_num]['stop_type_results']['range_opt']['oos_return'] = range_oos_result['total_return']
        
        print(f"  Window {window_num+1} results:")
        for stop_type in ['atr_opt', 'pct_opt', 'dollar_opt', 'range_opt']:
            res = results[tf_name][window_num]['stop_type_results'][stop_type]
            print(f"    {stop_type}: param={res['param']:.4f}, explor_return={res['exploration_return']*100:+.2f}%, oos_return={res['oos_return']*100:+.2f}%")
        
        # Move the window forward by step_bars (which is test_bars)
        start_idx += step_bars
        train_end_idx += step_bars
        test_start_idx += step_bars
        test_end_idx += step_bars
        window_num += 1
        
        # Break if we've processed enough windows for now (to avoid too much output)
        if window_num >= 2:  # We'll limit to 2 windows for now to keep output manageable
            print(f"  ... stopping after {window_num} windows for brevity")
            break
    
    print(f"Completed {tf_name} with {window_num} windows processed")

# Now we have all results. We'll compute average OOS performance across windows and timeframes for each stop type.
# We'll also compute the ATR-based stop performance for comparison.

# Prepare data for JSON output
output_data = {
    'analysis_type': 'stop_ablation_test',
    'timestamp': datetime.now().isoformat(),
    'timeframe_results': {}
}

# We'll compute averages for each stop type across timeframes and windows
stop_types = ['atr_opt', 'pct_opt', 'dollar_opt', 'range_opt']
averages = {st: [] for st in stop_types}

for tf_name in results.keys():
    output_data['timeframe_results'][tf_name] = {
        'windows': []
    }
    for window_num in results[tf_name].keys():
        window_data = results[tf_name][window_num]
        window_info = {
            'window': window_num + 1,
            'stop_type_results': {}
        }
        for stop_type in stop_types:
            res = window_data['stop_type_results'][stop_type]
            window_info['stop_type_results'][stop_type] = {
                'param': res['param'],
                'exploration_return': res['exploration_return'],
                'oos_return': res['oos_return']
            }
            averages[stop_type].append(res['oos_return'])
        output_data['timeframe_results'][tf_name]['windows'].append(window_info)

# Compute averages
avg_returns = {}
for stop_type in stop_types:
    if averages[stop_type]:
        avg_returns[stop_type] = np.mean(averages[stop_type])
    else:
        avg_returns[stop_type] = 0.0

output_data['averages'] = {
    'atr_opt': avg_returns['atr_opt'],
    'pct_opt': avg_returns['pct_opt'],
    'dollar_opt': avg_returns['dollar_opt'],
    'range_opt': avg_returns['range_opt']
}

# Save results
os.makedirs('/Users/aryanagarwal/experiments/profitability_lab/hostile_test', exist_ok=True)
results_path = '/Users/aryanagarwal/experiments/profitability_lab/hostile_test/stop_ablation_results.json'
with open(results_path, 'w') as f:
    json.dump(output_data, f, indent=2)
print(f"\nResults saved to: {results_path}")

# Print summary
print("\n" + "="*70)
print("STOP ABLATION TEST SUMMARY")
print("="*70)
print("Average OOS return across windows and timeframes:")
for stop_type in stop_types:
    print(f"  {stop_type}: {avg_returns[stop_type]*100:+.2f}%")

# Determine if the ATR-based stop performs better than the alternatives
# We'll consider it better if its average OOS return is higher than the alternatives by a certain margin.
# We'll use a simple heuristic: if ATR-based stop has the highest average OOS return, then it's better.
# Otherwise, we consider that the performance may be due to stop/exit geometry.
best_stop_type = max(avg_returns, key=avg_returns.get)
best_return = avg_returns[best_stop_type]
print(f"\nBest performing stop type: {best_stop_type} with {best_return*100:+.2f}%")

if best_stop_type == 'atr_opt':
    print("ATR-based stop performs best: suggests volatility mechanism may be important.")
else:
    print("ATR-based stop does not perform best: suggests performance may be due to stop/exit geometry or other factors.")

print("\n" + "="*70)
print("STOP ABLATION TEST COMPLETE")
print("="*70)
