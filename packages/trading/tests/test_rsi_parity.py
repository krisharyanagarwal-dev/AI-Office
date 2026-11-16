"""
Parity tests: alpha-system RSI vs trading-bot's PRODUCTION RSI.

These import the real production functions from trading-bot and compare bar by
bar against alpha-system. They do not re-derive production's behaviour from a
spec -- they call it.

If trading-bot is not importable the tests skip rather than silently passing,
because "the comparison did not run" must never look like "the comparison
passed".

Deterministic fixtures only: every input series is generated from a fixed seed,
so a failure is reproducible.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ALPHA = Path(__file__).resolve().parents[1]
TRADING = Path('/Users/aryanagarwal/trading-bot')
sys.path.insert(0, str(ALPHA))


def _load_production():
    """Import trading-bot's TechnicalIndicators, or skip."""
    if not TRADING.exists():
        pytest.skip('trading-bot not present; production parity cannot be checked')
    sys.path.insert(0, str(TRADING))
    try:
        from strategies.strategies import TechnicalIndicators
        return TechnicalIndicators
    except Exception as exc:  # pragma: no cover
        pytest.skip(f'could not import production TechnicalIndicators: {exc}')


def _ohlcv(n=600, seed=20260101):
    """Deterministic OHLCV frame, one ticker."""
    rng = np.random.RandomState(seed)
    idx = pd.date_range('2023-01-01', periods=n, freq='5min')
    close = pd.Series(100 + np.cumsum(rng.randn(n) * 0.4), index=idx)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([open_, close], axis=1).max(axis=1) + 0.2
    low = pd.concat([open_, close], axis=1).min(axis=1) - 0.2
    volume = pd.Series(rng.uniform(80, 130, n), index=idx)
    data = pd.DataFrame({'open': open_, 'high': high, 'low': low,
                         'close': close, 'volume': volume})
    return data


def _first_difference(a: pd.Series, b: pd.Series, atol=0.0):
    """Return (index_label, a, b) of the FIRST differing bar, or None.

    NaN-aware: NaN vs NaN is agreement. NaN vs a number is a difference.
    """
    a = a.reset_index(drop=True)
    b = b.reset_index(drop=True)
    if len(a) != len(b):
        return ('<length>', len(a), len(b))
    for i in range(len(a)):
        av, bv = a.iloc[i], b.iloc[i]
        if pd.isna(av) and pd.isna(bv):
            continue
        if pd.isna(av) != pd.isna(bv):
            return (i, av, bv)
        if abs(float(av) - float(bv)) > atol:
            return (i, av, bv)
    return None


# --- A/B: production RSI vs alpha-system RSI, bar for bar -------------------

@pytest.mark.parametrize('period', [7, 14, 21])
@pytest.mark.parametrize('seed', [20260101, 999, 4242])
def test_rsi_exact_parity_with_production(period, seed):
    TI = _load_production()
    from alpha.factors.rsi import rsi as alpha_rsi

    data = _ohlcv(seed=seed)
    close = data['close']

    prod = TI.rsi(close, period)
    mine = alpha_rsi(close, period, method='rolling')

    assert len(prod) == len(mine), 'length mismatch'
    diff = _first_difference(pd.Series(prod), pd.Series(mine))
    assert diff is None, f'RSI diverges at bar {diff[0]}: production={diff[1]} alpha={diff[2]}'


def test_rsi_parity_across_many_seeds():
    TI = _load_production()
    from alpha.factors.rsi import rsi as alpha_rsi
    for seed in range(20):
        close = _ohlcv(n=400, seed=seed)['close']
        diff = _first_difference(
            pd.Series(TI.rsi(close, 14)), pd.Series(alpha_rsi(close, 14))
        )
        assert diff is None, f'seed {seed} diverges at bar {diff[0]}'


# --- momentum.RSIFactor now also matches production ------------------------

def test_momentum_rsi_factor_parity_with_production():
    TI = _load_production()
    from alpha.factors.momentum import RSIFactor

    data = _ohlcv()
    prices = data[['close']]
    out = RSIFactor(periods=[14]).compute(prices)['rsi_14']

    prod = pd.Series(TI.rsi(data['close'], 14))
    # momentum.RSIFactor ends with .stack(), which DROPS the warmup NaN rows
    # (600 -> 587 for period 14). That is correct production-shaped behaviour, so
    # compare the surviving values against production's non-NaN slice.
    mine = out.droplevel(1) if isinstance(out.index, pd.MultiIndex) else out
    mine = pd.Series(mine.reset_index(drop=True))
    assert len(mine) == int(prod.notna().sum()) - 0, (
        f'stacked rows {len(mine)} != production non-NaN {int(prod.notna().sum())}'
    )
    diff = _first_difference(prod.dropna().reset_index(drop=True), mine)
    assert diff is None, f'momentum.RSIFactor diverges at bar {diff[0]}'


# --- zero-loss / zero-gain / mixed / warmup --------------------------------

def test_all_gains_gives_100_not_empty():
    """The bug: .replace(0, NaN) made this frame empty."""
    from alpha.factors.momentum import RSIFactor
    n = 60
    rising = pd.DataFrame({'close': pd.Series(np.arange(1.0, n + 1))})
    out = RSIFactor(periods=[14]).compute(rising)
    assert len(out) > 0, 'all-gain window produced an EMPTY frame'
    assert out['rsi_14'].max() == pytest.approx(100.0)


def test_all_losses_gives_0():
    TI = _load_production()
    from alpha.factors.rsi import rsi as alpha_rsi
    n = 60
    falling = pd.Series(np.arange(float(n), 0.0, -1.0))
    prod, mine = TI.rsi(falling, 14), alpha_rsi(falling, 14)
    diff = _first_difference(pd.Series(prod), pd.Series(mine))
    assert diff is None, f'all-loss diverges at {diff}'
    assert mine.dropna().iloc[-1] == pytest.approx(0.0)


def test_mixed_gains_and_losses_parity():
    TI = _load_production()
    from alpha.factors.rsi import rsi as alpha_rsi
    close = _ohlcv(seed=7)['close']
    diff = _first_difference(pd.Series(TI.rsi(close, 14)),
                             pd.Series(alpha_rsi(close, 14)))
    assert diff is None, f'mixed diverges at bar {diff[0]}'


def test_warmup_is_nan_and_matches_production_exactly():
    TI = _load_production()
    from alpha.factors.rsi import rsi as alpha_rsi
    close = _ohlcv(n=40)['close']
    prod, mine = TI.rsi(close, 14), alpha_rsi(close, 14)
    # First period-1 bars have no full window in either implementation.
    assert prod.iloc[:13].isna().all(), 'production should be NaN during warmup'
    assert mine.iloc[:13].isna().all(), 'alpha should be NaN during warmup'
    assert _first_difference(pd.Series(prod), pd.Series(mine)) is None


def test_flat_series_is_nan_in_both():
    """0/0 is genuinely undefined; production yields NaN and so must alpha."""
    TI = _load_production()
    from alpha.factors.rsi import rsi as alpha_rsi
    flat = pd.Series([100.0] * 40)
    prod, mine = TI.rsi(flat, 14), alpha_rsi(flat, 14)
    assert _first_difference(pd.Series(prod), pd.Series(mine)) is None


def test_insufficient_history_all_nan():
    from alpha.factors.rsi import rsi as alpha_rsi
    tiny = pd.Series([1.0, 2.0, 3.0])
    assert alpha_rsi(tiny, 14).isna().all()


# --- C/D: production RsiVolumeStrategy vs alpha equivalent -----------------

def _ohlcv_crossing(seed, n=900):
    """Deterministic OHLCV engineered to actually trigger production signals.

    A plain random walk almost never satisfies production's four conditions at
    once (RSI cross AND 1.5x volume AND the EMA50/200 side), so a random fixture
    yields zero fires on BOTH sides -- a parity test that passes while comparing
    nothing. This fixture spikes volume on exactly the bars where RSI crosses 30
    or 70, which is what makes the comparison meaningful.
    """
    TI = _load_production()
    idx = pd.date_range('2023-01-01', periods=n, freq='5min')
    rng = np.random.RandomState(seed)
    t = np.arange(n)
    phase = (t % 60) / 60.0
    saw = np.where(phase < 0.5, phase * 2 - 0.5, 1.5 - phase * 2)
    close = pd.Series(100 + 12 * saw + rng.randn(n) * 0.25, index=idx)
    r = TI.rsi(close, 14)
    spike = ((r.shift(1) >= 30) & (r < 30)) | ((r.shift(1) <= 70) & (r > 70))
    volume = pd.Series(rng.uniform(70, 90, n), index=idx)
    volume[spike] = rng.uniform(220, 280, int(spike.sum()))
    return pd.DataFrame({'open': close, 'high': close + 0.2, 'low': close - 0.2,
                         'close': close, 'volume': volume})


def _production_rsi_volume_signals(data, idxs, config=None):
    """Drive the REAL production RsiVolumeStrategy, return signal per bar."""
    sys.path.insert(0, str(TRADING))
    try:
        from strategies.registry import RsiVolumeStrategy
    except Exception as exc:
        pytest.skip(f'could not import production RsiVolumeStrategy: {exc}')

    from strategies.strategies import Signal as ProdSignal

    strat = RsiVolumeStrategy(config or {})
    out = {}
    for i in idxs:
        setup = strat.analyze_setup(data, i)
        if setup is None:
            out[i] = 0.0
        elif setup.direction == ProdSignal.BUY:
            out[i] = 1.0
        elif setup.direction == ProdSignal.SELL:
            out[i] = -1.0
        else:
            out[i] = 0.0
    return pd.Series(out)


@pytest.mark.parametrize('seed', [1, 2, 3, 4, 5])
def test_rsi_volume_strategy_parity(seed):
    from alpha.factors.rsi import RsiVolumeStrategyFactor

    data = _ohlcv_crossing(seed=seed)
    prices = data[['close']].rename(columns={'close': 'BTC'})
    volumes = data[['volume']].rename(columns={'volume': 'BTC'})

    mine = RsiVolumeStrategyFactor().compute(prices, volumes)['BTC_rsi_volume_signal']
    mine = mine.reset_index(drop=True)

    idxs = range(201, len(data))
    prod = _production_rsi_volume_signals(data, idxs)

    diff = _first_difference(prod, mine.iloc[201:].reset_index(drop=True))
    assert diff is None, (
        f'RsiVolume diverges at bar {diff[0]} '
        f'(production={diff[1]}, alpha={diff[2]})'
    )


def test_rsi_volume_pre_min_bars_is_nan():
    """Production returns None for idx < min_bars; alpha must be NaN, not 0."""
    from alpha.factors.rsi import RsiVolumeStrategyFactor
    data = _ohlcv(n=260)
    mine = RsiVolumeStrategyFactor().compute(
        data[['close']].rename(columns={'close': 'BTC'}),
        data[['volume']].rename(columns={'volume': 'BTC'}),
    )['BTC_rsi_volume_signal']
    assert mine.iloc[:200].isna().all(), 'pre-min_bars bars must be NaN'
    assert mine.iloc[200:].notna().any(), 'post-min_bars bars must be evaluated'


def test_rsi_volume_requires_cross_not_level():
    """A level-only implementation would fire far more often than production."""
    from alpha.factors.rsi import RsiVolumeStrategyFactor
    data = _ohlcv(n=700, seed=555)
    mine = RsiVolumeStrategyFactor().compute(
        data[['close']].rename(columns={'close': 'BTC'}),
        data[['volume']].rename(columns={'volume': 'BTC'}),
    )['BTC_rsi_volume_signal']
    fires = int((mine == 1.0).sum() + (mine == -1.0).sum())
    total = int(mine.notna().sum())
    assert fires < total * 0.25, (
        f'{fires} fires in {total} eligible bars looks level-based, not cross-based'
    )


# --- the default cannot drift ----------------------------------------------

def test_default_method_is_production_rolling():
    from alpha.factors import rsi as mod
    assert mod._DEFAULT_METHOD == 'rolling'


def test_wilder_is_available_but_never_default():
    from alpha.factors import rsi as mod
    assert 'wilder' in mod._RSI_METHODS
    close = _ohlcv(n=300)['close']
    wilder = mod._RSI_METHODS['wilder'](close, 14)
    rolling = mod._RSI_METHODS['rolling'](close, 14)
    assert _first_difference(pd.Series(wilder), pd.Series(rolling)) is not None, (
        'wilder and rolling are identical; documenting the choice is theatre'
    )


def test_default_call_equals_rolling():
    from alpha.factors.rsi import rsi as alpha_rsi
    close = _ohlcv(n=200)['close']
    assert _first_difference(
        pd.Series(alpha_rsi(close, 14)), pd.Series(alpha_rsi(close, 14, 'rolling'))
    ) is None

def test_rsi_volume_fixture_is_not_vacuous():
    """Guard: the parity fixture must make production actually fire.

    Without this, a fixture where neither side produces a signal would report
    perfect parity while comparing nothing. This is the exact failure mode hit
    during development.
    """
    data = _ohlcv_crossing(seed=1)
    prod = _production_rsi_volume_signals(data, range(201, len(data)))
    fires = int((prod != 0).sum())
    assert fires > 0, 'fixture produces zero production signals; parity would be vacuous'
    assert (prod == 1).any(), 'fixture never triggers a BUY'
    assert (prod == -1).any(), 'fixture never triggers a SELL'


@pytest.mark.parametrize('seed', [1, 2, 3, 4, 5])
def test_rsi_volume_parity_is_exact_not_approximate(seed):
    """Both directions, every bar, no tolerance."""
    from alpha.factors.rsi import RsiVolumeStrategyFactor
    data = _ohlcv_crossing(seed=seed)
    prod = _production_rsi_volume_signals(data, range(201, len(data)))
    mine = RsiVolumeStrategyFactor().compute(
        data[['close']].rename(columns={'close': 'BTC'}),
        data[['volume']].rename(columns={'volume': 'BTC'}),
    )['BTC_rsi_volume_signal'].iloc[201:].reset_index(drop=True)
    diff = _first_difference(prod.reset_index(drop=True), mine)
    assert diff is None, f'seed {seed} diverges at bar {diff[0]}'
    assert (prod != 0).sum() > 0, 'no signals fired; comparison would be vacuous'
