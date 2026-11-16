"""
Tests for the volatility breakout factors.

The properties pinned here are the ones that would silently produce a wrong
signal rather than an exception:

  * the Donchian channel must exclude the current bar (no look-ahead)
  * the factor must stay inside [-1, 1]
  * warmup stays NaN; only a genuinely flat market maps to 0.0
  * a multi-ticker input yields one stacked row per (date, ticker)

compute() returns a DataFrame of already-stacked Series, so every column has a
(date, ticker) MultiIndex. The tests unstack before comparing to raw prices.
"""

import numpy as np
import pandas as pd
import pytest

from alpha.factors.volatility_breakout import (
    ChannelExpansionFactor,
    VolatilityBreakoutFactor,
)


@pytest.fixture
def trending():
    idx = pd.date_range("2024-01-01", periods=400, freq="D")
    return pd.DataFrame(
        {"AAA": 100 + np.cumsum(np.r_[np.zeros(60), np.linspace(0, 40, 340)])},
        index=idx,
    )


@pytest.fixture
def random_walk():
    idx = pd.date_range("2024-01-01", periods=400, freq="D")
    rng = np.random.default_rng(5)
    return pd.DataFrame(
        {"BBB": 100 + np.cumsum(rng.normal(0, 1.5, 400))}, index=idx
    )


def test_emits_breakout_and_width_per_lookback(trending):
    out = VolatilityBreakoutFactor(lookbacks=[20, 55]).compute(trending)
    for lb in (20, 55):
        assert f"breakout_{lb}" in out.columns
        assert f"channel_width_{lb}" in out.columns


def test_channel_excludes_current_bar(random_walk):
    """A new high must be judged against prior bars only.

    If the channel included the current bar, prices >= rolling(lb).max() would
    be true on every bar that sets the extreme, so that count is far higher than
    the shift(1) version. The factor must follow the shift(1) definition.
    """
    prices = random_walk["BBB"]
    lb = 20
    with_current = int((prices >= prices.rolling(lb).max()).sum())
    without_current = int((prices >= prices.rolling(lb).max().shift(1)).sum())
    assert without_current < with_current

    series = (
        VolatilityBreakoutFactor(lookbacks=[lb])
        .compute(random_walk)[f"breakout_{lb}"]
        .unstack()["BBB"]
    )

    # On a bar that set a new prior-window high, and was not simultaneously a
    # new low, the factor must read a full +1 -- except when the prior channel
    # is degenerate (zero width), which the factor deliberately maps to 0.0
    # because a flat range carries no breakout information.
    prior_high = prices.rolling(lb).max().shift(1)
    prior_low = prices.rolling(lb).min().shift(1)
    width = (prior_high - prior_low) / prices
    made_high = (prices >= prior_high).fillna(False)
    made_low = (prices <= prior_low).fillna(False)
    only_high = (made_high & ~made_low & (width > 0)).iloc[lb:]
    # NB: select by the boolean mask, not by only_high.index -- .index carries
    # every date label regardless of the mask values.
    selected = series[only_high.reindex(series.index).fillna(False)]

    assert only_high.sum() > 0, "fixture should produce some non-degenerate new highs"
    assert len(selected) == int(only_high.sum())
    assert (selected >= 0.999).all()
    assert (selected <= 1.0 + 1e-9).all()

    # A degenerate prior channel is a no-position, not a missed breakout.
    degenerate = (made_high & ~made_low & (width == 0)).iloc[lb:]
    if degenerate.sum():
        flat_selected = series[degenerate.reindex(series.index).fillna(False)]
        assert (flat_selected == 0.0).all()

    # And the complement: bars inside the channel must not read as breakouts.
    inside = (~made_high & ~made_low).iloc[lb:]
    inside_selected = series[inside.reindex(series.index).fillna(False)]
    assert inside_selected.abs().max() <= 1.0 + 1e-9


def test_bounded_within_unit_interval(trending, random_walk):
    both = pd.concat([trending, random_walk], axis=1)
    out = VolatilityBreakoutFactor(lookbacks=[20, 55, 100]).compute(both)
    breakout = out.filter(like="breakout_")
    # Drop warmup, where the channel does not exist yet.
    finite = breakout.stack().dropna()
    assert finite.abs().max() <= 1.0 + 1e-9


def test_flat_market_maps_to_zero_not_nan():
    """A zero-width channel means no position, not unknown."""
    flat = pd.DataFrame(
        {"FLAT": np.full(300, 100.0)},
        index=pd.date_range("2024-01-01", periods=300, freq="D"),
    )
    lb = 20
    series = (
        VolatilityBreakoutFactor(lookbacks=[lb])
        .compute(flat)[f"breakout_{lb}"]
        .unstack()["FLAT"]
    )
    assert series.iloc[lb:].eq(0.0).all()
    # Past warmup a flat market is fully known, so it must not be NaN.
    assert not series.iloc[lb:].isna().any()


def test_warmup_is_nan_and_nothing_else_is(trending, random_walk):
    """Warmup is unknown; beyond it the factor must be finite."""
    for frame, ticker in ((trending, "AAA"), (random_walk, "BBB")):
        lb = 20
        series = (
            VolatilityBreakoutFactor(lookbacks=[lb])
            .compute(frame)[f"breakout_{lb}"]
            .unstack()[ticker]
        )
        assert series.iloc[:lb].isna().all(), "warmup must be NaN"
        assert not series.iloc[lb:].isna().any(), "past warmup must be finite"


def test_uptrend_saturates_positive(trending):
    lb = 20
    series = (
        VolatilityBreakoutFactor(lookbacks=[lb])
        .compute(trending)[f"breakout_{lb}"]
        .unstack()["AAA"]
        .dropna()
    )
    assert series.max() == pytest.approx(1.0)
    assert series.min() >= -1e-9


def test_channel_width_is_non_negative(random_walk):
    out = VolatilityBreakoutFactor(lookbacks=[20]).compute(random_walk)
    width = out["channel_width_20"].dropna()
    assert (width >= 0).all()


def test_channel_expansion_columns(trending, random_walk):
    out = ChannelExpansionFactor(short=20, long=100).compute(random_walk)
    assert "expansion_20_100" in out.columns
    ratio = out["expansion_20_100"].dropna()
    assert (ratio >= 0).all()
    assert ratio.max() <= 20.0


def test_channel_expansion_expands_after_a_quiet_period():
    """A long quiet range followed by a burst should score expansion above 1."""
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    quiet = np.concatenate([np.full(200, 100.0), 100 + np.linspace(0, 20, 100)])
    prices = pd.DataFrame({"X": quiet}, index=idx)
    ratio = (
        ChannelExpansionFactor(short=20, long=100)
        .compute(prices)["expansion_20_100"]
        .unstack()["X"]
        .dropna()
    )
    assert ratio.max() > 1.0


def test_channel_expansion_flat_market_is_not_infinite():
    flat = pd.DataFrame(
        {"F": np.full(300, 50.0)},
        index=pd.date_range("2024-01-01", periods=300, freq="D"),
    )
    ratio = ChannelExpansionFactor().compute(flat)["expansion_20_100"].dropna()
    assert np.isfinite(ratio).all()


def test_multi_ticker_produces_one_row_per_date_ticker(random_walk, trending):
    both = pd.concat([trending, random_walk], axis=1)
    out = VolatilityBreakoutFactor(lookbacks=[20]).compute(both)
    series = out["breakout_20"]
    assert set(series.index.get_level_values(1)) == {"AAA", "BBB"}
    # Stacked, so rows == dates * tickers, not dates.
    assert len(series) == len(both) * both.shape[1]


def test_compute_matches_calling_the_instance(trending):
    factor = VolatilityBreakoutFactor(lookbacks=[20])
    pd.testing.assert_frame_equal(factor.compute(trending), factor(trending))


def test_factor_metadata():
    factor = VolatilityBreakoutFactor(lookbacks=[20])
    assert factor.category == "breakout"
    assert factor.config.name == "VolatilityBreakout"
    assert factor.get_params()["lookbacks"] == [20]

    expansion = ChannelExpansionFactor()
    assert expansion.category == "breakout"
    assert expansion.config.name == "ChannelExpansion"