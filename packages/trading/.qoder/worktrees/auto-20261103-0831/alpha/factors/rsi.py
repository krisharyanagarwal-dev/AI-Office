"""
RSI factors for alpha-system, ported from trading-bot's production strategies.

Authoritative sources (read-only; trading-bot is NOT modified by this module)
---------------------------------------------------------------------------
* ``trading-bot/strategies/strategies.py:53-59`` -- TechnicalIndicators.rsi,
  the definition every live RSI strategy calls.
* ``trading-bot/strategies/registry.py:149``      -- RsiVolumeStrategy.
* ``trading-bot/strategies/registry.py:405-409``  -- the enabled environments.

The production RSI is a **simple rolling mean**, not Wilder's smoothing:

    delta = series.diff()
    gain  =  (delta.where(delta >  0, 0)).rolling(window=period).mean()
    loss  = (-delta.where(delta <  0, 0)).rolling(window=period).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))

Note what production does *not* do: it does not guard the division. With
loss == 0 the quotient is +inf and RSI is exactly 100; with gain == loss == 0
the quotient is NaN. That arithmetic is correct and is reproduced here rather
than "fixed", because alpha-system's previous implementation inserted
``.replace(0, np.nan)``, which turned a legitimate 100 into NaN and silently
dropped the factor on precisely the strong-uptrend bars a RSI signal exists to
catch. See tests/test_rsi_parity.py.

Wilder's smoothing is retained as an explicitly named alternative
(``method='wilder'``) because it is a legitimate research variant, but it is
**never** the default. ``wilder`` cannot become the default by accident: the
default lives in one place, ``_DEFAULT_METHOD``, asserted by a test.

Cost note
---------
The forensic audit for the source strategy recorded ``fees_modeled: False`` and
``slippage_modeled: False``. Its +16.7% return / 1.15 profit factor are gross of
fees, slippage and funding and are not an edge. Use trading-bot's
``paper-benchmark/cost_model.py`` (``cost_bps`` / ``break_even_bps``) before
treating any output here as tradeable.
"""

from typing import Optional

import numpy as np
import pandas as pd

from alpha.factors.base import FactorBase

# The one place the default RSI definition is chosen. Production parity depends
# on this being 'rolling'.
_DEFAULT_METHOD = 'rolling'


def _rsi_rolling(close: pd.Series, period: int) -> pd.Series:
    """Byte-for-byte the production formula at strategies/strategies.py:53-59.

    Deliberately no zero-division guard: production has none, and adding one
    changes 100 -> NaN on all-gain windows.
    """
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _rsi_simple(close: pd.Series, period: int) -> pd.Series:
    """Reproduces trading-bot/strategy.py::rsi_signal (research scripts only).

    Uses a simple mean of the last ``period`` gains/losses rather than a rolling
    window, so it is NOT interchangeable with the production path.
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)
    return rsi


def _rsi_wilder(close: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (alpha = 1/period). Named alternative, not default."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)
    return rsi.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return rsi


_RSI_METHODS = {
    'rolling': _rsi_rolling,
    'simple': _rsi_simple,
    'wilder': _rsi_wilder,
}


def _resolve_method(method) -> str:
    name = str(method).lower()
    if name not in _RSI_METHODS:
        raise ValueError(
            f"unknown RSI method {name!r}; expected one of {sorted(_RSI_METHODS)}"
        )
    return name


def rsi(series: pd.Series, period: int = 14, method: Optional[str] = None) -> pd.Series:
    """Canonical RSI accessor. Default matches production."""
    return _RSI_METHODS[_resolve_method(method or _DEFAULT_METHOD)](series, period)


class RSIFactor(FactorBase):
    """RSI level, centered form, and threshold state.

    Emits, per ticker:
      rsi            raw RSI in [0, 100]; NaN during warmup, and NaN on a
                     window with no gains and no losses (production parity)
      rsi_centered   (rsi - 50) / 50 in [-1, 1], the cross-sectionally
                     comparable form that neutralize() operates on
      rsi_oversold   1.0 where rsi < oversold
      rsi_overbought 1.0 where rsi > overbought

    Threshold flags are ``(rsi < oversold).astype(float)``, so a warmup NaN
    yields 0.0 ("no signal"), never a spurious 1.0.
    """

    @property
    def category(self) -> str:
        return 'momentum'

    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        period = int(self.params.get('period', 14))
        oversold = float(self.params.get('oversold', 30))
        overbought = float(self.params.get('overbought', 70))
        method = _resolve_method(self.params.get('method', _DEFAULT_METHOD))

        if oversold >= overbought:
            raise ValueError(
                f"oversold ({oversold}) must be < overbought ({overbought})"
            )

        results = {}
        for ticker in prices.columns:
            values = _RSI_METHODS[method](prices[ticker], period)
            results[f'{ticker}_rsi'] = values
            results[f'{ticker}_rsi_centered'] = (values - 50.0) / 50.0
            # NaN-safe: a comparison against NaN is False, so warmup yields 0.
            results[f'{ticker}_rsi_oversold'] = (values < oversold).astype(float)
            results[f'{ticker}_rsi_overbought'] = (values > overbought).astype(float)

        return pd.DataFrame(results)


class RsiVolumeStrategyFactor(FactorBase):
    """Port of trading-bot/strategies/registry.py:149 ``RsiVolumeStrategy``.

    Production semantics preserved exactly:

    * **cross** detection, not level checks -- the previous RSI must be at or
      beyond the threshold and the current RSI must cross it
    * ``volume > volume_ma * volume_multiplier`` (strict >)
    * HTF trend filter: buy requires fast EMA > slow EMA, sell requires the
      inverse; with the filter off, both directions are permitted
    * NaN in rsi / previous rsi / volume_ma suppresses the signal
    * min_bars = 201 by default (production: max(201, htf_slow+1, rsi+2, vol_ma+1))

    Output per ticker: +1 buy, -1 sell, 0 no signal, and NaN before min_bars so
    "not enough history" is distinguishable from "looked and found nothing".
    """

    @property
    def category(self) -> str:
        return 'momentum'

    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if volumes is None:
            raise ValueError(
                'RsiVolumeStrategyFactor requires volumes; volume confirmation '
                'is part of the production strategy, not an optional extra.'
            )

        rsi_period = int(self.params.get('rsi_period', 14))
        oversold = float(self.params.get('rsi_oversold', 30))
        overbought = float(self.params.get('rsi_overbought', 70))
        volume_multiplier = float(self.params.get('volume_multiplier', 1.5))
        volume_ma_period = int(self.params.get('volume_ma_period', 20))
        use_htf_trend_filter = bool(self.params.get('use_htf_trend_filter', True))
        htf_fast_period = int(self.params.get('htf_fast_period', 50))
        htf_slow_period = int(self.params.get('htf_slow_period', 200))
        method = _resolve_method(self.params.get('method', _DEFAULT_METHOD))

        if oversold >= overbought:
            raise ValueError(
                f"oversold ({oversold}) must be < overbought ({overbought})"
            )

        min_bars = int(self.params.get('min_bars', max(
            201, htf_slow_period + 1, rsi_period + 2, volume_ma_period + 1
        )))

        results = {}
        for ticker in prices.columns:
            if ticker not in volumes.columns:
                raise ValueError(
                    f'{ticker} present in prices but absent from volumes'
                )
            close = prices[ticker]
            values = _RSI_METHODS[method](close, rsi_period)
            volume = volumes[ticker]
            volume_ma = volume.rolling(window=volume_ma_period).mean()

            if use_htf_trend_filter:
                fast = close.ewm(span=htf_fast_period, adjust=False).mean()
                slow = close.ewm(span=htf_slow_period, adjust=False).mean()
                bullish = fast > slow
                bearish = fast < slow
            else:
                # Production sets bullish = bearish = True when the filter is off,
                # permitting both directions.
                bullish = pd.Series(True, index=close.index)
                bearish = pd.Series(True, index=close.index)

            signal = pd.Series(0.0, index=close.index)
            signal = signal.mask(values.isna() | values.shift(1).isna() | volume_ma.isna(), np.nan)

            buy = (
                (values.shift(1) >= oversold)
                & (values < oversold)
                & (volume > volume_ma * volume_multiplier)
                & bullish
            )
            sell = (
                (values.shift(1) <= overbought)
                & (values > overbought)
                & (volume > volume_ma * volume_multiplier)
                & bearish
            )
            signal = signal.mask(buy.fillna(False), 1.0)
            signal = signal.mask(sell.fillna(False), -1.0)

            # Before min_bars production returns None unconditionally.
            signal = signal.where(np.arange(len(signal)) >= min_bars - 1, np.nan)
            results[f'{ticker}_rsi_volume_signal'] = signal

        return pd.DataFrame(results)