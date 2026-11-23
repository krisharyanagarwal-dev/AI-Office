"""Tests for the repo risk governor as the carry book's pre-trade gate.

Two production breaks are pinned here:

  * a delta-flat carry book must be measured by its true gross, otherwise the
    governor reads a spot-long/perp-short pair as zero exposure and lets any
    size through;
  * only a losing day may trip the daily-loss cap - a profitable day must not
    be treated as a loss.
"""
from risk import LimitStatus, RiskGovernor, RiskLimits


def _governor(**limits) -> RiskGovernor:
    return RiskGovernor(RiskLimits(**limits))


def test_symbol_exposure_uses_the_gross_notional_when_the_record_carries_one():
    """Catches: the governor reading a delta-flat carry book as zero exposure."""
    governor = _governor(max_symbol_exposure_pct=0.15)
    governor.limits.positions["BTCUSDT"] = {
        "quantity": 0.0,
        "avg_entry_price": 0.0,
        "gross_notional": 20_000.0,
    }
    result = governor.check_symbol_exposure("BTCUSDT", 10_000.0)
    assert result.status is LimitStatus.FAIL
    assert "exposure" in result.reason


def test_symbol_exposure_keeps_the_quantity_fallback_when_no_gross_is_recorded():
    """Catches: a gross-aware rewrite that breaks the existing position format."""
    governor = _governor(max_symbol_exposure_pct=0.15)
    governor.limits.positions["BTCUSDT"] = {
        "quantity": 100.0,
        "avg_entry_price": 100.0,
    }
    result = governor.check_symbol_exposure("BTCUSDT", 10_000.0)
    assert result.status is LimitStatus.FAIL
    assert "exposure" in result.reason


def test_total_exposure_sums_the_gross_notionals_of_a_delta_flat_book():
    """Catches: signed netting hiding 40,000 of gross behind a zero net."""
    governor = _governor(max_total_exposure_pct=0.60)
    governor.limits.positions["BTCUSDT"] = {"gross_notional": 20_000.0}
    governor.limits.positions["ETHUSDT"] = {"gross_notional": 20_000.0}
    result = governor.check_total_exposure(10_000.0)
    assert result.status is LimitStatus.FAIL
    assert "total exposure" in result.reason


def test_total_exposure_keeps_the_signed_fallback_for_records_without_gross():
    """Catches: changing the netting rule for every other consumer of the governor."""
    governor = _governor(max_total_exposure_pct=0.60)
    governor.limits.positions["LONG"] = {"quantity": 100.0, "avg_entry_price": 100.0}
    governor.limits.positions["SHORT"] = {"quantity": -100.0, "avg_entry_price": 100.0}
    result = governor.check_total_exposure(10_000.0)
    assert result.status is LimitStatus.PASS


def test_a_profitable_day_does_not_trip_the_daily_loss_cap():
    """Catches: abs(daily_pnl) treating a +500 day as a 5% loss."""
    governor = _governor(max_daily_loss_pct=0.03, start_of_day_equity=10_000.0)
    governor.limits.daily_pnl = 500.0
    result = governor.check_daily_loss()
    assert result.status is LimitStatus.PASS
    assert result.reason is None


def test_a_losing_day_trips_the_daily_loss_cap():
    """Catches: a sign-blind loss cap that lets real losses through."""
    governor = _governor(max_daily_loss_pct=0.03, start_of_day_equity=10_000.0)
    governor.limits.daily_pnl = -500.0
    result = governor.check_daily_loss()
    assert result.status is LimitStatus.FAIL
    assert "daily loss" in result.reason


def test_a_flat_day_passes_the_daily_loss_cap():
    governor = _governor(max_daily_loss_pct=0.03, start_of_day_equity=10_000.0)
    governor.limits.daily_pnl = 0.0
    assert governor.check_daily_loss().status is LimitStatus.PASS
