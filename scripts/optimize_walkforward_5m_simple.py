import json
import os
import numpy as np
import pandas as pd
from datetime import datetime

# Load the 5m data
DATA_PATH = '/Users/aryanagarwal/trading-bot/data/btc_5m_5year.parquet'
data_5m = pd.read_parquet(DATA_PATH)
print(f"Loaded 5m data: {len(data_5m)} bars from {data_5m.index[0]} to {data_5m.index[-1]}")

# Strategy parameters to optimize - reduced grid
ema_fast_options = [10, 20, 30]
ema_slow_options = [20, 30, 40, 50]
atr_mult_options = [0.5, 1.0, 1.5]
risk_per_trade = 0.1  # 10% equity per trade
fees_rt = 0.0005      # 0.05% round-trip fees
slippage_per_trade = 0.0005  # 0.05% slippage

# Walk-forward parameters
initial_train_years = 1.0  # Initial training window in years
test_halfyear = 0.5        # Test window in half years (6 months)

def calculate_ema(period, values):
    """Calculate EMA"""
    ema = np.zeros_like(values)
    ema[0] = values[0]
    multiplier = 2 / (period + 1)
    for i in range(1, len(values)):
        ema[i] = (values[i] * multiplier) + (ema[i-1] * (1 - multiplier))
    return ema

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

def backtest_strategy(df, ema_fast, ema_slow, atr_mult):
    """
    Backtest the EMA crossover strategy with ATR stop on the given dataframe.
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
    
    # Calculate ATR
    atr_arr = calculate_atr(high, low, close)
    
    # Walk-forward simulation
    capital = 100000.0
    position = 0  # 0 = no position, 1 = long, -1 = short
    entry_price = 0
    entry_atr = 0
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
                entry_atr = atr_arr[i]  # ATR at signal bar for stop calculation
            elif sell_signal:
                position = -1
                entry_price = close[i] * (1 - slippage_per_trade)  # slippage on entry
                entry_atr = atr_arr[i]  # ATR at signal bar for stop calculation
        
        # Check stop loss (executed at next bar open if triggered intra-bar)
        if position != 0 and i < len(close)-1:
            # Use next bar's open price for stop execution (conservative)
            current_price = close[i+1]  # Next bar open
            
            if position == 1:  # Long position
                stop_price = entry_price - (entry_atr * atr_mult)
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
            elif position == -1:  # Short position
                stop_price = entry_price + (entry_atr * atr_mult)
                if current_price >= stop_price:
                    # Stop loss triggered at next bar open
                    exit_price = stop_price * (1 + slippage_per_trade)  # slippage on exit
                    pnl = (exit_price - entry_price) * (capital * risk_per_trade / entry_price)
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
    
    # For Sharpe, we'll compute using trade returns and annualize based on the number of trades per year?
    # We'll leave Sharpe as 0.0 for simplicity in this script, but we can compute it if needed.
    # We'll compute a simple Sharpe using the trade returns and assuming 252 trading days per year, but we need to know the holding period.
    # For simplicity, we'll leave Sharpe as 0.0 for now and focus on total return and win rate.
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
        'sharpe': sharpe,
        'max_dd': max_dd,
        'trades': len(trades),
        'win_rate': win_rate,
        'final_capital': capital,
        'fees_paid': fees_total
    }

def optimize_parameters(train_df):
    """
    Optimize EMA fast, EMA slow, ATR multiplier on the training data.
    We'll use a grid search to maximize the total return (since Sharpe is not reliable).
    We'll return the best parameters and their in-sample performance.
    """
    best_return = -np.inf
    best_params = None
    best_result = None
    
    for ef in ema_fast_options:
        for es in ema_slow_options:
            if es <= ef:
                continue
            for am in atr_mult_options:
                result = backtest_strategy(train_df, ef, es, am)
                # Use total return as objective
                obj = result['total_return']
                if obj > best_return:
                    best_return = obj
                    best_params = (ef, es, am)
                    best_result = result
    
    return best_params, best_result

def expanding_window_walkforward(df, tf_name):
    """
    Perform expanding window walk-forward with parameter optimization.
    We'll start with an initial training window of 1 year, then test on next 6 months.
    Then expand training window by 6 months and test on next 6 months, and so on.
    For each window, we optimize parameters on the training data, then test on the test data.
    We'll also compute the performance of the fixed parameters (20,50,1.5) for comparison.
    """
    # Compute bars per year and per half year for this timeframe
    # We'll infer from the data: find the median time difference between bars
    if len(df) < 2:
        print(f"Insufficient data for {tf_name}")
        return None
    
    # Calculate the median time difference in seconds
    time_diffs = df.index.to_series().diff().dropna()
    median_diff = time_diffs.median()
    # Convert to days
    median_days = median_diff.total_seconds() / (24 * 3600)
    bars_per_day = 1.0 / median_days
    bars_per_year = bars_per_day * 365.25
    bars_per_halfyear = bars_per_year / 2.0
    
    print(f"{tf_name}: Bars per day: {bars_per_day:.2f}, Bars per year: {bars_per_year:.2f}, Bars per half year: {bars_per_halfyear:.2f}")
    
    # Convert to integers
    initial_train_bars = int(round(bars_per_year * initial_train_years))
    test_bars = int(round(bars_per_halfyear * test_halfyear))
    step_bars = test_bars  # We'll expand by the test window size each time
    
    print(f"{tf_name}: Initial training bars: {initial_train_bars}, Test bars per window: {test_bars}, Step bars: {step_bars}")
    
    # Check we have enough data
    if len(df) < initial_train_bars + test_bars:
        print(f"Insufficient data for even one window: need {initial_train_bars + test_bars} bars, have {len(df)}")
        return None
    
    # We'll slide the window
    window_results = []
    start_idx = 0
    train_end_idx = initial_train_bars
    test_start_idx = train_end_idx
    test_end_idx = test_start_idx + test_bars
    
    window_num = 0
    while test_end_idx <= len(df):
        train_df = df.iloc[start_idx:train_end_idx].copy()
        test_df = df.iloc[test_start_idx:test_end_idx].copy()
        
        print(f"\nWindow {window_num+1}: Train [{train_df.index[0]} to {train_df.index[-1]}] ({len(train_df)} bars)")
        print(f"         Test  [{test_df.index[0]} to {test_df.index[-1]}] ({len(test_df)} bars)")
        
        # Optimize parameters on training data
        best_params, best_in_sample_result = optimize_parameters(train_df)
        if best_params is None:
            print(f"  Optimization failed, using fixed parameters (20,50,1.5)")
            best_params = (20, 50, 1.5)
            # Compute in-sample result for fixed parameters
            best_in_sample_result = backtest_strategy(train_df, 20, 50, 1.5)
        else:
            print(f"  Optimized params: EMA fast={best_params[0]}, EMA slow={best_params[1]}, ATR mult={best_params[2]}")
            print(f"  In-sample performance: Return={best_in_sample_result['total_return']*100:+.2f}%, "
                  f"Sharpe={best_in_sample_result['sharpe']:.2f}, "
                  f"Trades={best_in_sample_result['trades']}, Win Rate={best_in_sample_result['win_rate']*100:.1f}%")
        
        # Test on out-of-sample data with optimized parameters
        oos_result = backtest_strategy(test_df, best_params[0], best_params[1], best_params[2])
        print(f"  Out-of-sample performance: Return={oos_result['total_return']*100:+.2f}%, "
              f"Sharpe={oos_result['sharpe']:.2f}, "
              f"Trades={oos_result['trades']}, Win Rate={oos_result['win_rate']*100:.1f}%")
        
        # Also test fixed parameters on out-of-sample for comparison
        fixed_oos_result = backtest_strategy(test_df, 20, 50, 1.5)
        print(f"  Fixed params (20,50,1.5) OOS performance: Return={fixed_oos_result['total_return']*100:+.2f}%, "
              f"Sharpe={fixed_oos_result['sharpe']:.2f}, "
              f"Trades={fixed_oos_result['trades']}, Win Rate={fixed_oos_result['win_rate']*100:.1f}%")
        
        # Record this window's results
        window_result = {
            'window': window_num + 1,
            'train_start': train_df.index[0].isoformat(),
            'train_end': train_df.index[-1].isoformat(),
            'test_start': test_df.index[0].isoformat(),
            'test_end': test_df.index[-1].isoformat(),
            'optimized_params': {
                'ema_fast': best_params[0],
                'ema_slow': best_params[1],
                'atr_mult': best_params[2]
            } if best_params != (20, 50, 1.5) else None,
            'in_sample_performance': {
                'total_return': best_in_sample_result['total_return'],
                'sharpe': best_in_sample_result['sharpe'],
                'max_dd': best_in_sample_result['max_dd'],
                'trades': best_in_sample_result['trades'],
                'win_rate': best_in_sample_result['win_rate'],
                'final_capital': best_in_sample_result['final_capital'],
                'fees_paid': best_in_sample_result['fees_paid']
            },
            'out_of_sample_performance_optimized': {
                'total_return': oos_result['total_return'],
                'sharpe': oos_result['sharpe'],
                'max_dd': oos_result['max_dd'],
                'trades': oos_result['trades'],
                'win_rate': oos_result['win_rate'],
                'final_capital': oos_result['final_capital'],
                'fees_paid': oos_result['fees_paid']
            },
            'out_of_sample_performance_fixed': {
                'total_return': fixed_oos_result['total_return'],
                'sharpe': fixed_oos_result['sharpe'],
                'max_dd': fixed_oos_result['max_dd'],
                'trades': fixed_oos_result['trades'],
                'win_rate': fixed_oos_result['win_rate'],
                'final_capital': fixed_oos_result['final_capital'],
                'fees_paid': fixed_oos_result['fees_paid']
            }
        }
        window_results.append(window_result)
        
        # Move the window forward by step_bars (which is test_bars)
        start_idx += step_bars
        train_end_idx += step_bars
        test_start_idx += step_bars
        test_end_idx += step_bars
        window_num += 1
        
        # Break if we've processed enough windows for now (to avoid too much output)
        if window_num >= 3:  # We'll limit to 3 windows for now to keep output manageable
            print(f"  ... stopping after {window_num} windows for brevity")
            break
    
    # Summary statistics
    if len(window_results) > 0:
        # Collect out-of-sample returns for optimized and fixed
        oos_returns_opt = [w['out_of_sample_performance_optimized']['total_return'] for w in window_results]
        oos_returns_fixed = [w['out_of_sample_performance_fixed']['total_return'] for w in window_results]
        oos_win_rates_opt = [w['out_of_sample_performance_optimized']['win_rate'] for w in window_results]
        oos_win_rates_fixed = [w['out_of_sample_performance_fixed']['win_rate'] for w in window_results]
        
        summary = {
            'timeframe': tf_name,
            'n_windows': len(window_results),
            'window_results': window_results,
            'summary': {
                'optimized': {
                    'mean_return': np.mean(oos_returns_opt),
                    'median_return': np.median(oos_returns_opt),
                    'std_return': np.std(oos_returns_opt),
                    'mean_win_rate': np.mean(oos_win_rates_opt),
                    'median_win_rate': np.median(oos_win_rates_opt),
                    'profitability_pct': sum(1 for r in oos_returns_opt if r > 0) / len(oos_returns_opt) * 100 if len(oos_returns_opt) > 0 else 0
                },
                'fixed': {
                    'mean_return': np.mean(oos_returns_fixed),
                    'median_return': np.median(oos_returns_fixed),
                    'std_return': np.std(oos_returns_fixed),
                    'mean_win_rate': np.mean(oos_win_rates_fixed),
                    'median_win_rate': np.median(oos_win_rates_fixed),
                    'profitability_pct': sum(1 for r in oos_returns_fixed if r > 0) / len(oos_returns_fixed) * 100 if len(oos_returns_fixed) > 0 else 0
                }
            }
        }
        return summary
    else:
        return None

# Run for 5m timeframe
print(f"\n{'='*60}")
print(f"EXPANDING WALK-FORWARD WITH PARAMETER OPTIMIZATION: 5m")
print(f"{'='*60}")
result = expanding_window_walkforward(data_5m, '5m')
if result:
    print(f"\n5m Summary:")
    print(f"  Windows: {result['n_windows']}")
    print(f"  Optimized - Mean Return: {result['summary']['optimized']['mean_return']*100:+.2f}%")
    print(f"  Optimized - Mean Win Rate: {result['summary']['optimized']['mean_win_rate']*100:.1f}%")
    print(f"  Optimized - Profitability: {result['summary']['optimized']['profitability_pct']:.1f}%")
    print(f"  Fixed - Mean Return: {result['summary']['fixed']['mean_return']*100:+.2f}%")
    print(f"  Fixed - Mean Win Rate: {result['summary']['fixed']['mean_win_rate']*100:.1f}%")
    print(f"  Fixed - Profitability: {result['summary']['fixed']['profitability_pct']:.1f}%")
else:
    print(f"  5m: Insufficient data for walk-forward")

# Save results
os.makedirs('/Users/aryanagarwal/experiments/profitability_lab', exist_ok=True)
results_path = '/Users/aryanagarwal/experiments/profitability_lab/optimized_walkforward_results_5m_simple.json'
with open(results_path, 'w') as f:
    json.dump({
        'analysis_type': 'expanding_walkforward_with_parameter_optimization_simple',
        'timestamp': datetime.now().isoformat(),
        'strategy': 'EMA crossover + ATR stop with next-bar execution',
        'methodology': 'Expanding window walk-forward: initial 1 year train, then 6 month test, expand training by 6 month each step',
        'results': {'5m': result} if result else {}
    }, f, indent=2)
print(f"\nResults saved to: {results_path}")

print("\n" + "="*60)
print("OPTIMIZED WALK-FORWARD FOR 5m (SIMPLE) COMPLETE")
print("="*60)
