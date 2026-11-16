import json
import numpy as np
import pandas as pd
from datetime import datetime

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

def autocorr(x, lag=1):
    """Compute autocorrelation at given lag"""
    if len(x) <= lag:
        return np.nan
    return np.corrcoef(x[:-lag], x[lag:])[0,1]

def integrated_autocorr_time(x, max_lag=1000):
    """Compute integrated autocorrelation time up to max_lag"""
    n = len(x)
    if n < 2:
        return np.nan
    acf = np.zeros(max_lag)
    for k in range(max_lag):
        if k >= n:
            acf[k] = np.nan
        else:
            acf[k] = autocorr(x, k)
    # Truncate at first negative autocorrelation
    for k in range(max_lag):
        if np.isnan(acf[k]) or acf[k] < 0:
            max_lag = k
            break
    # Integrated autocorrelation time: 1 + 2 * sum_{k=1}^{M} acf(k)
    if max_lag > 0:
        iact = 1 + 2 * np.sum(acf[1:max_lag])
    else:
        iact = np.nan
    return iact, acf

def compute_timescale_metrics(returns, timeframe_label, seconds_per_bar):
    """Compute volatility timescale metrics from returns series"""
    # Absolute returns
    abs_returns = np.abs(returns)
    # Squared returns
    sq_returns = returns ** 2
    
    # Compute autocorrelation at lag 1 for absolute and squared returns
    abs_acf1 = autocorr(abs_returns, lag=1)
    sq_acf1 = autocorr(sq_returns, lag=1)
    
    # Compute integrated autocorrelation time for absolute and squared returns
    abs_iact, abs_acf = integrated_autocorr_time(abs_returns, max_lag=100)
    sq_iact, sq_acf = integrated_autocorr_time(sq_returns, max_lag=100)
    
    # Decay rate (lambda) approximated from ACF at lag 1: assuming exponential decay, acf(1) = exp(-lambda)
    # So lambda = -log(acf(1)) if acf(1) > 0 and <1
    if abs_acf1 > 0 and abs_acf1 < 1:
        abs_decay_rate = -np.log(abs_acf1)
    else:
        abs_decay_rate = np.nan
    if sq_acf1 > 0 and sq_acf1 < 1:
        sq_decay_rate = -np.log(sq_acf1)
    else:
        sq_decay_rate = np.nan
    
    # Half-life: ln(2) / decay_rate
    if abs_decay_rate > 0:
        abs_half_life = np.log(2) / abs_decay_rate
    else:
        abs_half_life = np.nan
    if sq_decay_rate > 0:
        sq_half_life = np.log(2) / sq_decay_rate
    else:
        sq_half_life = np.nan
    
    # E-folding time: 1 / decay_rate
    if abs_decay_rate > 0:
        abs_efolding_time = 1 / abs_decay_rate
    else:
        abs_efolding_time = np.nan
    if sq_decay_rate > 0:
        sq_efolding_time = 1 / sq_decay_rate
    else:
        sq_efolding_time = np.nan
    
    # Convert to clock time (seconds)
    abs_half_life_sec = abs_half_life * seconds_per_bar if not np.isnan(abs_half_life) else np.nan
    abs_efolding_time_sec = abs_efolding_time * seconds_per_bar if not np.isnan(abs_efolding_time) else np.nan
    sq_half_life_sec = sq_half_life * seconds_per_bar if not np.isnan(sq_half_life) else np.nan
    sq_efolding_time_sec = sq_efolding_time * seconds_per_bar if not np.isnan(sq_efolding_time) else np.nan
    
    return {
        'timeframe': timeframe_label,
        'seconds_per_bar': seconds_per_bar,
        'abs_return_acf1': abs_acf1,
        'sq_return_acf1': sq_acf1,
        'abs_return_iact': abs_iact,
        'sq_return_iact': sq_iact,
        'abs_return_decay_rate': abs_decay_rate,
        'sq_return_decay_rate': sq_decay_rate,
        'abs_return_half_life_bars': abs_half_life,
        'abs_return_half_life_sec': abs_half_life_sec,
        'abs_return_efolding_time_bars': abs_efolding_time,
        'abs_return_efolding_time_sec': abs_efolding_time_sec,
        'sq_return_half_life_bars': sq_half_life,
        'sq_return_half_life_sec': sq_half_life_sec,
        'sq_return_efolding_time_bars': sq_efolding_time,
        'sq_return_efolding_time_sec': sq_efolding_time_sec
    }

# Compute seconds per bar for each timeframe
# We'll compute from the median time difference in the 5m data
time_diffs = data_5m.index.to_series().diff().dropna()
median_diff_5m = time_diffs.median()
seconds_per_5m_bar = median_diff_5m.total_seconds()
print(f"Median 5m bar duration: {seconds_per_5m_bar} seconds")

results = {}
for tf_name, df in all_data.items():
    # Compute simple returns: (close_t - close_{t-1}) / close_{t-1}
    close = df['close'].values
    returns = np.diff(close) / close[:-1]
    # Prepend NaN to align with index
    returns = np.concatenate([[np.nan], returns])
    
    # Get seconds per bar for this timeframe
    # We can compute from the index difference
    time_diffs_tf = df.index.to_series().diff().dropna()
    median_diff_tf = time_diffs_tf.median()
    seconds_per_bar = median_diff_tf.total_seconds()
    
    print(f"\n{tf_name}: {len(df)} bars, median bar duration: {seconds_per_bar} seconds")
    
    metrics = compute_timescale_metrics(returns, tf_name, seconds_per_bar)
    results[tf_name] = metrics

# Print summary
print("\n" + "="*70)
print("VOLATILITY TIMESCALE METRICS")
print("="*70)
for tf_name, metrics in results.items():
    print(f"\n{tf_name}:")
    print(f"  Absolute return ACF(1): {metrics['abs_return_acf1']:.6f}")
    print(f"  Squared return ACF(1):  {metrics['sq_return_acf1']:.6f}")
    print(f"  Absolute return IACT:   {metrics['abs_return_iact']:.2f} bars")
    print(f"  Squared return IACT:    {metrics['sq_return_iact']:.2f} bars")
    print(f"  Absolute return decay rate: {metrics['abs_return_decay_rate']:.6f}")
    print(f"  Squared return decay rate:  {metrics['sq_return_decay_rate']:.6f}")
    print(f"  Absolute return half-life: {metrics['abs_return_half_life_bars']:.2f} bars ({metrics['abs_return_half_life_sec']/60:.2f} min)")
    print(f"  Squared return half-life:  {metrics['sq_return_half_life_bars']:.2f} bars ({metrics['sq_return_half_life_sec']/60:.2f} min)")
    print(f"  Absolute return e-folding time: {metrics['abs_return_efolding_time_bars']:.2f} bars ({metrics['abs_return_efolding_time_sec']/60:.2f} min)")
    print(f"  Squared return e-folding time:  {metrics['sq_return_efolding_time_bars']:.2f} bars ({metrics['sq_return_efolding_time_sec']/60:.2f} min)")

# Save results
os.makedirs('/Users/aryanagarwal/experiments/profitability_lab/hostile_test', exist_ok=True)
results_path = '/Users/aryanagarwal/experiments/profitability_lab/hostile_test/volatility_timescale_results.json'
with open(results_path, 'w') as f:
    json.dump({
        'analysis_type': 'volatility_timescale_analysis',
        'timestamp': datetime.now().isoformat(),
        'results': results
    }, f, indent=2)
print(f"\nResults saved to: {results_path}")
