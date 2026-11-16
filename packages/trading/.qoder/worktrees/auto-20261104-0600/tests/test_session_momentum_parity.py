"""
Tests for the session momentum factors.

Properties pinned here:

  * session windows are UTC and the documented ones
  * carry[t] == ret[t-1] per ticker, with no carry before the first session
  * a day with no bar inside a window contributes nothing rather than a zero
  * the overlap share is bounded in [-1, 1] and survives a zero-move session
  * an unknown session name is rejected up front
"""

import numpy as np
import pandas as pd
import pytest

from alpha.factors.session_momentum import (
    SESSION_WINDOWS,
    SessionMomentumFactor,
    SessionOverlapFactor,
)


@pytest.fixture
def intraday():
    idx = pd.date_range("2024-03-04", periods=24 * 10, freq="h", tz="UTC")
    rng = np.random.default_rng(11)
    return pd.DataFrame(
        {"BTC": 100 + np.cumsum(rng.normal(0, 0.2, len(idx)))}, index=idx
    )


@pytest.fixture
def flat_intraday():
    idx = pd.date_range("2024-03-04", periods=24 * 5, freq="h", tz="UTC")
    return pd.DataFrame({"FLAT": np.full(len(idx), 100.0)}, index=idx)


def test_session_windows_are_the_documented_utc_ranges():
    assert SESSION_WINDOWS == {
        "asia": (0, 8),
        "london": (7, 16),
        "ny": (13, 22),
    }
    for name, (start, end) in SESSION_WINDOWS.items():
        assert 0 <= start < end <= 24, name


def test_emits_ret_and_carry_per_session(intraday):
    out = SessionMomentumFactor().compute(intraday)
    for session in ("asia", "london", "ny"):
        assert f"{session}_ret" in out.columns
        assert f"{session}_carry" in out.columns


def test_carry_is_previous_session_return(intraday):
    out = SessionMomentumFactor(sessions=["asia"]).compute(intraday)
    ret = out["asia_ret"].unstack()["BTC"]
    carry = out["asia_carry"].unstack()["BTC"]

    assert carry.index.equals(ret.index)
    assert np.isnan(carry.iloc[0]), "no carry before the first session"
    for i in range(1, len(ret)):
        assert np.isclose(carry.iloc[i], ret.iloc[i - 1]), f"carry broken at {i}"


def test_carry_is_per_ticker_not_across_tickers():
    idx = pd.date_range("2024-03-04", periods=24 * 4, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "A": 100 + np.cumsum(np.r_[np.zeros(1), np.full(len(idx) - 1, 1.0)]),
            "B": 100 + np.cumsum(np.r_[np.zeros(1), np.full(len(idx) - 1, -1.0)]),
        },
        index=idx,
    )
    out = SessionMomentumFactor(sessions=["asia"]).compute(frame)
    carry = out["asia_carry"].unstack()
    # Ticker A rises and B falls, so a shared (accidentally row-wise) carry
    # would give them the same sign. Per-ticker carry must not.
    finite = carry.dropna()
    if len(finite) >= 2:
        assert finite["A"].iloc[-1] > 0
        assert finite["B"].iloc[-1] < 0


def test_session_return_uses_open_and_close(intraday):
    out = SessionMomentumFactor(sessions=["asia"]).compute(intraday)
    ret = out["asia_ret"].unstack()["BTC"]
    manual = []
    for _, day in intraday["BTC"].groupby(intraday.index.date):
        window = day.between_time("00:00", "07:59")
        if window.empty:
            continue
        manual.append((window.iloc[-1] - window.iloc[0]) / window.iloc[0])
    assert np.allclose(ret.dropna().values, np.array(manual))


def test_flat_market_session_return_is_zero_not_nan(flat_intraday):
    out = SessionMomentumFactor(sessions=["asia"]).compute(flat_intraday)
    ret = out["asia_ret"].unstack()["FLAT"].dropna()
    assert ret.eq(0.0).all()


def test_naive_index_is_converted_to_utc(intraday):
    """A tz-naive index must be localized to UTC, not crash or shift."""
    naive = intraday.tz_localize(None)
    out = SessionMomentumFactor(sessions=["asia"]).compute(naive)
    ret = out["asia_ret"].unstack()["BTC"].dropna()
    assert len(ret) > 0


def test_unknown_session_is_rejected():
    with pytest.raises(ValueError, match="unknown session"):
        SessionMomentumFactor(sessions=["lunch"])


def test_non_datetime_index_is_rejected():
    frame = pd.DataFrame({"X": [1.0, 2.0, 3.0]}, index=[0, 1, 2])
    with pytest.raises(ValueError, match="DatetimeIndex"):
        SessionMomentumFactor().compute(frame)


def test_overlap_columns_and_bounds(intraday):
    out = SessionOverlapFactor().compute(intraday)
    assert "asia_to_london_share" in out.columns
    assert "london_to_ny_share" in out.columns
    for column in out.columns:
        values = out[column].dropna()
        assert values.between(-1.0, 1.0).all(), f"{column} escaped [-1, 1]"


def test_overlap_zero_move_session_is_zero(flat_intraday):
    out = SessionOverlapFactor().compute(flat_intraday)
    for column in out.columns:
        values = out[column].dropna()
        assert values.eq(0.0).all(), f"{column} should be 0 on a flat market"


def test_overlap_share_is_finite(intraday):
    out = SessionOverlapFactor().compute(intraday)
    for column in out.columns:
        assert np.isfinite(out[column].dropna()).all()


def test_session_subset_is_respected(intraday):
    out = SessionMomentumFactor(sessions=["ny"]).compute(intraday)
    assert "ny_ret" in out.columns
    assert "asia_ret" not in out.columns
    assert "london_ret" not in out.columns


def test_single_session_overlap_has_no_columns(intraday):
    out = SessionOverlapFactor(sessions=["asia"]).compute(intraday)
    assert len(out.columns) == 0


def test_factor_metadata(intraday):
    factor = SessionMomentumFactor(sessions=["asia", "london"])
    assert factor.category == "momentum"
    assert factor.config.name == "SessionMomentum"
    assert factor.get_params()["sessions"] == ["asia", "london"]

    overlap = SessionOverlapFactor()
    assert overlap.category == "momentum"
    assert overlap.config.name == "SessionOverlap"


def test_empty_session_input_yields_empty_frame(intraday):
    empty = intraday.iloc[0:0]
    out = SessionMomentumFactor(sessions=["asia"]).compute(empty)
    assert len(out) == 0

def test_empty_session_list_is_honoured_not_defaulted(intraday):
    """None means defaults; [] means none. A truthiness check conflates them."""
    empty = SessionMomentumFactor(sessions=[]).compute(intraday)
    assert len(empty) == 0
    assert len(empty.columns) == 0

    defaults = SessionMomentumFactor(sessions=None).compute(intraday)
    assert len(defaults.columns) == 6


def test_empty_overlap_frame_has_no_columns(intraday):
    assert len(SessionOverlapFactor(sessions=[]).compute(intraday).columns) == 0
