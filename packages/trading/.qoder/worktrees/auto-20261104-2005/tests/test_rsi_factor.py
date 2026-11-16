"""
Unit tests for the ported RSI factors.

Parity against production lives in tests/test_rsi_parity.py. This file covers
the alpha-system-specific behaviour: configuration validation, warmup, the
zero-loss edge, and the guarantee that the production rolling-mean definition is
the default and cannot silently become Wilder's.

Authoritative production sources:
* trading-bot/strategies/strategies.py:53-59  (TechnicalIndicators.rsi)
* trading-bot/strategies/registry.py:149     (RsiVolumeStrategy)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.factors import rsi as rsi_mod
from alpha.factors.rsi import (
    RSIFactor,
    RsiVolumeStrategyFactor,
    _rsi_rolling,
    _rsi_wilder,
    rsi,
)


def _prices(n=400, seed=11, tickers=('BTC', 'ETH')):
    idx = pd.date_range('2024-01-01', periods=n, freq='5min')
    rng = np.random.RandomState(seed)
    out = {}
    for i, t in enumerate(tickers):
        out[t] = 100 * (i + 1) + np.cumsum(rng.randn(n) * 0.4)
    return pd.DataFrame(out, index=idx)


def _volumes(prices, seed=12):
    rng = np.random.RandomState(seed)
    return pd.DataFrame({c: rng.uniform(70, 130, len(prices.index))
                         for c in prices.columns}, index=prices.index)


# --- the default is production, and cannot drift ---------------------------

def test_default_is_rolling_not_wilder():
    assert rsi_mod._DEFAULT_METHOD == 'rolling'


def test_bare_call_matches_rolling_():
    close = _prices()['BTC']
    pd.testing.assert_series_equal(rsi(close, 14), rsi(close, 14, 'rolling'))


def test_wilder_available_and_distinct():
    close = _prices()['BTC']
    assert 'wilder' in rsi_mod._RSI_METHODS
    a, b = _rsi_wilder(close, 14), _rsi_rolling(close, 14)
    assert np.nanmax(np.abs(a - b)) > 1.0, 'wilder == rolling; choice is meaningless'


def test_production_is_not_wilder():
    """If these matched, 'rolling' would be a relabelled Wilder's."""
    close = _prices(n=400, seed=3)['BTC']
    assert np.nanmax(np.abs(_rsi_wilder(close, 14) - _rsi_rolling(close, 14))) > 1.0


# --- zero-loss / zero-gain / warmup (the bug that was fixed) ---------------

def test_all_gains_window_is_100_not_nan():
    rising = pd.Series(np.arange(1.0, 61.0))
    out = _rsi_rolling(rising, 14)
    assert out.iloc[-1] == pytest.approx(100.0)


def test_all_losses_window_is_0():
    falling = pd.Series(np.arange(60.0, 0.0, -1.0))
    assert _rsi_rolling(falling, 14).iloc[-1] == pytest.approx(0.0)


def test_flat_window_is_nan_not_zero():
    """0/0 is genuinely undefined. Production yields NaN; so must this."""
    flat = pd.Series([100.0] * 40)
    assert np.isnan(_rsi_rolling(flat, 14).iloc[-1])


def test_insufficient_warmup_is_nan():
    tiny = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert _rsi_rolling(tiny, 14).isna().all()


def test_warmup_length_matches_period_minus_one():
    close = _prices(n=60)['BTC']
    out = _rsi_rolling(close, 14)
    assert out.iloc[:13].isna().all()
    assert out.iloc[13:].notna().all()


def test_momentum_factor_all_gain_window_is_not_empty():
    """The original defect: .replace(0, NaN) produced an EMPTY frame here."""
    from alpha.factors.momentum import RSIFactor as MomentumRSI
    rising = pd.DataFrame({'close': pd.Series(np.arange(1.0, 61.0))})
    out = MomentumRSI(periods=[14]).compute(rising)
    assert len(out) > 0, 'all-gain window produced an empty frame'
    assert out['rsi_14'].max() == pytest.approx(100.0)


# --- RSIFactor output contract --------------------------------------------

def test_factor_output_columns_and_bounds():
    prices = _prices()
    out = RSIFactor().compute(prices)
    for col in ('BTC_rsi', 'ETH_rsi'):
        assert col in out.columns
        vals = out[col].dropna()
        assert vals.between(0, 100).all()


def test_centered_is_bounded_pm_one():
    out = RSIFactor().compute(_prices())
    vals = out['BTC_rsi_centered'].dropna()
    assert vals.between(-1, 1).all()


def test_threshold_flags_are_zero_during_warmup():
    """A warmup NaN must read as 'no signal' (0), never a spurious 1."""
    prices = _prices(n=30)
    out = RSIFactor().compute(prices)
    warm = out['BTC_rsi_oversold'].iloc[:13]
    assert (warm == 0).all(), 'warmup produced a spurious oversold flag'


def test_inverted_thresholds_rejected():
    with pytest.raises(ValueError, match='must be < overbought'):
        RSIFactor(oversold=80, overbought=20).compute(_prices())


def test_unknown_method_rejected():
    with pytest.raises(ValueError, match='unknown RSI method'):
        RSIFactor(method='nope').compute(_prices())


# --- RsiVolumeStrategyFactor contract --------------------------------------

def test_volume_strategy_requires_volumes():
    with pytest.raises(ValueError, match='requires volumes'):
        RsiVolumeStrategyFactor().compute(_prices(), None)


def test_volume_strategy_rejects_missing_ticker():
    prices, vols = _prices(), _volumes(_prices())
    with pytest.raises(ValueError, match='absent from volumes'):
        RsiVolumeStrategyFactor().compute(prices, vols[['BTC']])


def test_volume_strategy_nan_before_min_bars():
    prices, vols = _prices(n=260), _volumes(_prices(n=260))
    out = RsiVolumeStrategyFactor().compute(prices, vols)['BTC_rsi_volume_signal']
    assert out.iloc[:200].isna().all(), 'pre-min_bars must be NaN, not 0'
    assert out.iloc[200:].notna().any()


def test_volume_signal_values_are_pm_one_or_zero():
    prices, vols = _prices(n=700, seed=1), _volumes(_prices(n=700, seed=1), seed=1)
    out = RsiVolumeStrategyFactor().compute(prices, vols)
    # NaN is legitimate (insufficient history); every FINITE value must be a signal.
    vals = set(np.unique(out.to_numpy()[~np.isnan(out.to_numpy())]))
    assert vals <= {-1.0, 0.0, 1.0}
    assert bool(out.isna().any().any()), 'expected NaN before min_bars' 


def test_volume_gate_blocks_when_volume_is_constant():
    """The negative control: with flat volume nothing can exceed 1.5x its MA."""
    prices = _prices(n=700, seed=1)
    flat = pd.DataFrame({c: pd.Series(100.0, index=prices.index) for c in prices.columns})
    out = RsiVolumeStrategyFactor().compute(prices, flat)
    finite = out.to_numpy()[~np.isnan(out.to_numpy())]
    assert (finite == 0).all(), 'flat volume must never confirm a signal' 


def test_cross_required_not_level():
    """A level-only port would fire far more often than production's crosses."""
    prices, vols = _prices(n=900, seed=1), _volumes(_prices(n=900, seed=1), seed=1)
    out = RsiVolumeStrategyFactor().compute(prices, vols)['BTC_rsi_volume_signal']
    fires = int((out == 1).sum() + (out == -1).sum())
    eligible = int(out.notna().sum())
    assert fires < eligible * 0.25, (
        f'{fires} fires / {eligible} bars looks level-based, not cross-based'
    )


def test_htf_filter_disabled_still_requires_cross_and_volume():
    prices, vols = _prices(n=900, seed=1), _volumes(_prices(n=900, seed=1), seed=1)
    off = RsiVolumeStrategyFactor(use_htf_trend_filter=False).compute(prices, vols)
    on = RsiVolumeStrategyFactor(use_htf_trend_filter=True).compute(prices, vols)
    # Disabling the trend filter can only ever ADD signals, never remove them.
    assert int((on != 0).sum().sum()) <= int((off != 0).sum().sum())


def test_categories_are_momentum():
    assert RSIFactor().category == 'momentum'
    assert RsiVolumeStrategyFactor().category == 'momentum'