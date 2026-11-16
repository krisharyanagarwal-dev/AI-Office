import pandas as pd
import numpy as np

# -------------------------------------------------
# Configuration
# -------------------------------------------------
INITIAL_CAPITAL = 100_000.0
POSITION_SIZE_FRAC = 0.10  # 10% of capital per trade
FEE_PER_SIDE = 0.0005      # 0.05% fee per side
SLIPPAGE_PER_SIDE = 0.0005 # 0.05% slippage per side
# Round-trip cost per trade = 2*(FEE_PER_SIDE + SLIPPAGE_PER_SIDE) = 0.0020 (0.20%)
# We'll apply cost on entry and exit separately.

# Data split ratios
TRAIN_RATIO = 0.60
VAL_RATIO = 0.20
# TEST_RATIO = 0.20 (remaining)

# Bars per year for 5-minute data
MINUTES_PER_DAY = 60 * 24
BARS_PER_DAY = MINUTES_PER_DAY // 5
BARS_PER_YEAR = BARS_PER_DAY * 365
ANNUALIZATION_FACTOR = np.sqrt(BARS_PER_YEAR)

# Parameter grids
FAST_EMA_RANGE = list(range(5, 51, 5))   # 5,10,...,50
SLOW_EMA_RANGE = list(range(20, 101, 10)) # 20,30,...,100
VWAP_THRESHOLDS = [0.0, 0.002, 0.004, 0.006, 0.008, 0.01]  # fraction of VWAP

# -------------------------------------------------
# Helper functions
# -------------------------------------------------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP reset at each calendar day."""
    typical = (df['high'] + df['low'] + df['close']) / 3.0
    # group by date to reset each day
    dates = df.index.date
    cum_vol = df['volume'].groupby(dates).cumsum()
    cum_tpv = (typical * df['volume']).groupby(dates).cumsum()
    return cum_tpv / cum_vol

def generate_signals(df: pd.DataFrame, fast: int, slow: int, vwap_thresh: float, use_filter: bool) -> pd.Series:
    """
    Returns a signal series (1 for long, 0 for flat) shifted to avoid lookahead.
    """
    fast_ema = ema(df['close'], fast)
    slow_ema = ema(df['close'], slow)
    # EMA crossover condition based on previous bar
    ema_cross = (fast_ema > slow_ema).astype(int)
    # shift so signal at t is based on info up to t-1
    ema_signal = ema_cross.shift(1).fillna(0).astype(int)

    if not use_filter:
        return ema_signal

    # VWAP filter: require close > VWAP * (1 + vwap_thresh) using previous bar's VWAP
    vwap_series = vwap(df)
    vwap_cond = (df['close'] > vwap_series * (1.0 + vwap_thresh)).astype(int)
    vwap_signal = vwap_cond.shift(1).fillna(0).astype(int)

    # Combine: long only when both conditions are true
    return (ema_signal & vwap_signal).astype(int)

def backtest(df: pd.DataFrame, signal: pd.Series) -> dict:
    """
    Simulate trading based on signal (1 = long, 0 = flat).
    Returns dict with performance metrics.
    """
    capital = INITIAL_CAPITAL
    position = 0  # 0 = flat, 1 = long
    entry_price = 0.0
    equity_curve = [capital]
    trades = []  # list of dicts per trade

    for i in range(len(df)):
        price = df['close'].iloc[i]
        sig = signal.iloc[i]

        # Exit on signal change to flat
        if position == 1 and sig == 0:
            # Compute gross return
            gross_ret = (price / entry_price) - 1.0
            # Costs: fee and slippage on entry and exit (each side)
            # We already accounted for slippage in entry_price? We'll apply costs here.
            # Entry cost already applied when we entered? We'll apply both entry and exit costs now.
            # Simpler: apply round-trip cost = 2*(FEE_PER_SIDE + SLIPPAGE_PER_SIDE) = 0.0020
            net_ret = gross_ret - 2*(FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
            capital *= (1.0 + net_ret)
            trades.append({
                'entry_price': entry_price,
                'exit_price': price,
                'gross_ret': gross_ret,
                'net_ret': net_ret,
            })
            position = 0

        # Entry on signal change to long
        if position == 0 and sig == 1:
            position = 1
            entry_price = price  # entry price at this bar's close (we will apply cost at exit)

        # Update equity curve (mark-to-market)
        if position == 1:
            equity = capital * (price / entry_price)
        else:
            equity = capital
        equity_curve.append(equity)

    # If still in position at end, close at last price
    if position == 1:
        price = df['close'].iloc[-1]
        gross_ret = (price / entry_price) - 1.0
        net_ret = gross_ret - 2*(FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
        capital *= (1.0 + net_ret)
        trades.append({
            'entry_price': entry_price,
            'exit_price': price,
            'gross_ret': gross_ret,
            'net_ret': net_ret,
        })

    if not trades:
        return {
            'total_return': 0.0,
            'sharpe': 0.0,
            'max_dd': 0.0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'num_trades': 0,
        }

    # Compute returns per trade
    trade_returns = [t['net_ret'] for t in trades]
    total_return = capital / INITIAL_CAPITAL - 1.0

    # Sharpe: annualized using trade returns? Better to use equity curve returns.
    # Compute daily (bar) returns from equity curve
    equity_series = pd.Series(equity_curve, index=df.index.insert(0, df.index[0]))  # align length
    bar_ret = equity_series.pct_change().fillna(0.0)
    sharpe = bar_ret.mean() / bar_ret.std() * ANNUALIZATION_FACTOR if bar_ret.std() > 0 else 0.0

    # Max drawdown
    roll_max = equity_series.cummax()
    dd = (equity_series - roll_max) / roll_max
    max_dd = dd.min()

    # Win rate and profit factor
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r < 0]
    win_rate = len(wins) / len(trade_returns) if trade_returns else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else 0.0

    return {
        'total_return': total_return,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'num_trades': len(trades),
    }

def evaluate_parameters(df_train: pd.DataFrame, df_val: pd.DataFrame, fast: int, slow: int, vwap_thresh: float, use_filter: bool) -> dict:
    """Evaluate a parameter set on validation set."""
    signal = generate_signals(df_val, fast, slow, vwap_thresh, use_filter)
    return backtest(df_val, signal)

def main():
    # Load data
    df = pd.read_parquet('/Users/aryanagarwal/trading-bot/data/btc_5m_5year.parquet')
    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    n = len(df)
    train_end = int(n * TRAIN_RATIO)
    val_end = int(n * (TRAIN_RATIO + VAL_RATIO))

    df_train = df.iloc[:train_end]
    df_val = df.iloc[train_end:val_end]
    df_test = df.iloc[val_end:]

    print(f"Data split: Train={len(df_train)}, Validation={len(df_val)}, Test={len(df_test)}")

    # Grid search on Train to get candidate parameters
    best_sharpe_train = -np.inf
    best_params_train = None

    for fast in FAST_EMA_RANGE:
        for slow in SLOW_EMA_RANGE:
            if fast >= slow:
                continue
            for thresh in VWAP_THRESHOLDS:
                # Baseline
                res = evaluate_parameters(df_train, df_val, fast, slow, thresh, use_filter=False)
                if res['sharpe'] > best_sharpe_train:
                    best_sharpe_train = res['sharpe']
                    best_params_train = (fast, slow, thresh, False)
                # OF version
                res_of = evaluate_parameters(df_train, df_val, fast, slow, thresh, use_filter=True)
                if res_of['sharpe'] > best_sharpe_train:
                    best_sharpe_train = res_of['sharpe']
                    best_params_train = (fast, slow, thresh, True)

    print(f"Best parameters from Train: fast={best_params_train[0]}, slow={best_params_train[1]}, vwap_thresh={best_params_train[2]}, use_filter={best_params_train[3]}")

    # Evaluate the best parameter set on Validation to select final parameters
    fast_val, slow_val, vwap_thresh_val, use_filter_val = best_params_train
    val_metrics = evaluate_parameters(df_val, df_val, fast_val, slow_val, vwap_thresh_val, use_filter_val)
    print(f"Validation metrics for selected params: {val_metrics}")

    # Final evaluation on Test set
    test_metrics = backtest(df_test, generate_signals(df_test, fast_val, slow_val, vwap_thresh_val, use_filter_val))

    # Also evaluate baseline with its own best parameters from Train (without filter) for comparison
    # We need to find best baseline params from Train (without filter)
    best_sharpe_baseline_train = -np.inf
    best_baseline_params = None
    for fast in FAST_EMA_RANGE:
        for slow in SLOW_EMA_RANGE:
            if fast >= slow:
                continue
            res = evaluate_parameters(df_train, df_val, fast, slow, 0.0, use_filter=False)
            if res['sharpe'] > best_sharpe_baseline_train:
                best_sharpe_baseline_train = res['sharpe']
                best_baseline_params = (fast, slow)
    # Evaluate baseline on Test
    baseline_test_metrics = backtest(df_test, generate_signals(df_test, best_baseline_params[0], best_baseline_params[1], 0.0, use_filter=False))

    # Print comparison table
    print("\n" + "="*60)
    print(f"{'Metric':<20} {'Baseline':>12} {'OF-Filter':>12} {'Delta':>12}")
    print("-"*60)
    metrics = ['total_return', 'sharpe', 'max_dd', 'win_rate', 'profit_factor', 'num_trades']
    for m in metrics:
        b = baseline_test_metrics[m]
        o = test_metrics[m]
        delta = o - b
        if m in ['total_return', 'max_dd', 'win_rate']:
            print(f"{m:<20} {b:>12.2%} {o:>12.2%} {delta:>+12.2%}")
        elif m in ['sharpe', 'profit_factor']:
            print(f"{m:<20} {b:>12.4f} {o:>12.4f} {delta:>+12.4f}")
        else:
            print(f"{m:<20} {b:>12.0f} {o:>12.0f} {delta:>+12.0f}")
    print("="*60)

    # Decision rule
    if (test_metrics['sharpe'] >= baseline_test_metrics['sharpe'] + 0.10) and (test_metrics['max_dd'] > baseline_test_metrics['max_dd']):
        print("\nVERDICT: ✅ Clear Win – OF Filter shows higher Sharpe (+0.10) and better (less negative) MaxDD.")
        print("RECOMMENDATION: Adopt the OF filter. Next experiment: test robustness with walk-forward optimization or different VWAP definitions (e.g., anchored VWAP).")
    elif test_metrics['sharpe'] > baseline_test_metrics['sharpe']:
        print("\nVERDICT: ⚠️ Marginal – OF Filter improves Sharpe but MaxDD not clearly better.")
        print("RECOMMENDATION: Consider the filter only if you value the slight edge; otherwise stay with Baseline. Next experiment: test different VWAP thresholds or add a volume filter to improve trade quality.")
    else:
        print("\nVERDICT: ❌ No Value – OF Filter did not add value (Sharpe equal or worse).")
        print("RECOMMENDATION: Reject the OF filter. Next experiment: investigate other order-flow proxies (e.g., signed volume imbalance) or test on higher frequency data.")

if __name__ == '__main__':
    main()