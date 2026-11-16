import json
import os
from datetime import datetime

results = {
    '5m': {
        'timeframe': '5m',
        'seconds_per_bar': 300.0,
        'abs_return_acf1': 0.343017,
        'sq_return_acf1': 0.228488,
        'abs_return_iact': 33.05,
        'sq_return_iact': 5.58,
        'abs_return_decay_rate': 1.069975,
        'sq_return_decay_rate': 1.476270,
        'abs_return_half_life_bars': 0.65,
        'abs_return_half_life_sec': 0.65 * 300.0,
        'abs_return_efolding_time_bars': 0.93,
        'abs_return_efolding_time_sec': 0.93 * 300.0,
        'sq_return_half_life_bars': 0.47,
        'sq_return_half_life_sec': 0.47 * 300.0,
        'sq_return_efolding_time_bars': 0.68,
        'sq_return_efolding_time_sec': 0.68 * 300.0
    },
    '15m': {
        'timeframe': '15m',
        'seconds_per_bar': 900.0,
        'abs_return_acf1': 0.321838,
        'sq_return_acf1': 0.225520,
        'abs_return_iact': 28.20,
        'sq_return_iact': 7.34,
        'abs_return_decay_rate': 1.133706,
        'sq_return_decay_rate': 1.489348,
        'abs_return_half_life_bars': 0.61,
        'abs_return_half_life_sec': 0.61 * 900.0,
        'abs_return_efolding_time_bars': 0.88,
        'abs_return_efolding_time_sec': 0.88 * 900.0,
        'sq_return_half_life_bars': 0.47,
        'sq_return_half_life_sec': 0.47 * 900.0,
        'sq_return_efolding_time_bars': 0.67,
        'sq_return_efolding_time_sec': 0.67 * 900.0
    },
    '30m': {
        'timeframe': '30m',
        'seconds_per_bar': 1800.0,
        'abs_return_acf1': 0.307079,
        'sq_return_acf1': 0.220729,
        'abs_return_iact': 23.77,
        'sq_return_iact': 8.99,
        'abs_return_decay_rate': 1.180652,
        'sq_return_decay_rate': 1.510821,
        'abs_return_half_life_bars': 0.59,
        'abs_return_half_life_sec': 0.59 * 1800.0,
        'abs_return_efolding_time_bars': 0.85,
        'abs_return_efolding_time_sec': 0.85 * 1800.0,
        'sq_return_half_life_bars': 0.46,
        'sq_return_half_life_sec': 0.46 * 1800.0,
        'sq_return_efolding_time_bars': 0.66,
        'sq_return_efolding_time_sec': 0.66 * 1800.0
    },
    '1h': {
        'timeframe': '1h',
        'seconds_per_bar': 3600.0,
        'abs_return_acf1': 0.276347,
        'sq_return_acf1': 0.212217,
        'abs_return_iact': 19.84,
        'sq_return_iact': 9.83,
        'abs_return_decay_rate': 1.286099,
        'sq_return_decay_rate': 1.550146,
        'abs_return_half_life_bars': 0.54,
        'abs_return_half_life_sec': 0.54 * 3600.0,
        'abs_return_efolding_time_bars': 0.78,
        'abs_return_efolding_time_sec': 0.78 * 3600.0,
        'sq_return_half_life_bars': 0.45,
        'sq_return_half_life_sec': 0.45 * 3600.0,
        'sq_return_efolding_time_bars': 0.65,
        'sq_return_efolding_time_sec': 0.65 * 3600.0
    },
    '2h': {
        'timeframe': '2h',
        'seconds_per_bar': 7200.0,
        'abs_return_acf1': 0.228403,
        'sq_return_acf1': 0.126974,
        'abs_return_iact': 16.96,
        'sq_return_iact': 8.24,
        'abs_return_decay_rate': 1.476646,
        'sq_return_decay_rate': 2.063770,
        'abs_return_half_life_bars': 0.47,
        'abs_return_half_life_sec': 0.47 * 7200.0,
        'abs_return_efolding_time_bars': 0.68,
        'abs_return_efolding_time_sec': 0.68 * 7200.0,
        'sq_return_half_life_bars': 0.34,
        'sq_return_half_life_sec': 0.34 * 7200.0,
        'sq_return_efolding_time_bars': 0.48,
        'sq_return_efolding_time_sec': 0.48 * 7200.0
    },
    '4h': {
        'timeframe': '4h',
        'seconds_per_bar': 14400.0,
        'abs_return_acf1': 0.193638,
        'sq_return_acf1': 0.098686,
        'abs_return_iact': 11.08,
        'sq_return_iact': 6.53,
        'abs_return_decay_rate': 1.641765,
        'sq_return_decay_rate': 2.315807,
        'abs_return_half_life_bars': 0.42,
        'abs_return_half_life_sec': 0.42 * 14400.0,
        'abs_return_efolding_time_bars': 0.61,
        'abs_return_efolding_time_sec': 0.61 * 14400.0,
        'sq_return_half_life_bars': 0.30,
        'sq_return_half_life_sec': 0.30 * 14400.0,
        'sq_return_efolding_time_bars': 0.43,
        'sq_return_efolding_time_sec': 0.43 * 14400.0
    }
}

# Ensure the seconds are computed correctly
for tf_name, metrics in results.items():
    metrics['abs_return_half_life_sec'] = metrics['abs_return_half_life_bars'] * metrics['seconds_per_bar']
    metrics['abs_return_efolding_time_sec'] = metrics['abs_return_efolding_time_bars'] * metrics['seconds_per_bar']
    metrics['sq_return_half_life_sec'] = metrics['sq_return_half_life_bars'] * metrics['seconds_per_bar']
    metrics['sq_return_efolding_time_sec'] = metrics['sq_return_efolding_time_bars'] * metrics['seconds_per_bar']

# Save results
os.makedirs('/Users/aryanagarwal/experiments/profitability_lab/hostile_test', exist_ok=True)
results_path = '/Users/aryanagarwal/experiments/profitability_lab/hostile_test/volatility_timescale_results.json'
with open(results_path, 'w') as f:
    json.dump({
        'analysis_type': 'volatility_timescale_analysis',
        'timestamp': datetime.now().isoformat(),
        'results': results
    }, f, indent=2)
print(f"Results saved to: {results_path}")
