"""
Tests for alpha.backtest.cost_model and for both engines' cost paths.

The cost model is what stands between a measured edge and a claim of profit, so
every part of it is exercised here: the fee ladder, the break-even solve, the CI on
the mean, and the gate that decides whether a book may be called tradeable.
"""
import json

import numpy as np
import pandas as pd
import pytest

from alpha.backtest import VectorizedBacktester, event_driven
from alpha.backtest.cost_model import (
    BINANCE_SPOT_VIP0_BPS_PER_SIDE,
    MIN_OBSERVATIONS_FOR_CI,
    cost_sensitivity,
    mean_significance,
)


def _cs(**kw):
    """cost_sensitivity with the boilerplate filled in."""
    args = dict(gross_pnl=10.0, costs=1.0, commission=0.001, slippage=0.0005,
               unit_values=[5.0] * 40)
    args.update(kw)
    return cost_sensitivity(**args)


class TestVenueAssumptions:
    def test_reference_fee_is_the_published_vip0_rate(self):
        # Binance spot VIP0: 0.1% maker AND 0.1% taker.
        assert BINANCE_SPOT_VIP0_BPS_PER_SIDE == pytest.approx(10.0)

    def test_sample_floor_is_pinned(self):
        # Lowering this invalidates every verdict ever issued against it.
        assert MIN_OBSERVATIONS_FOR_CI == 30

    def test_the_ladder_brackets_the_venue_fee(self):
        cs = _cs()
        fees = [s['fee_bps_per_side'] for s in cs['scenarios']]
        assert fees[0] == 0.0
        assert BINANCE_SPOT_VIP0_BPS_PER_SIDE in fees
        assert fees == sorted(fees)

    def test_funding_is_declared_not_modelled(self):
        cs = _cs()
        assert cs['funding_modelled'] is False
        assert 'NOT modeled' in cs['funding_note']

    def test_a_commission_below_the_venue_fee_is_flagged(self):
        # This repo's config default is 5 bps; slippage + spread are what make the
        # combined rate reach the venue level. Say which one is under-modelled.
        cs = _cs(commission=0.0005, slippage=0.0003, spread=0.0002)
        assert cs['commission_below_venue_fee'] is True
        assert cs['modelled_cost_bps_per_side'] == pytest.approx(10.0)
        cs2 = _cs(commission=0.001, slippage=0.0)
        assert cs2['commission_below_venue_fee'] is False


class TestCostSensitivityArithmetic:
    def test_net_is_gross_minus_costs(self):
        cs = _cs(gross_pnl=10.0, costs=2.5)
        assert cs['net_pnl'] == pytest.approx(7.5)
        assert cs['clears_modelled_costs'] is True

    def test_gross_is_kept_visible_rather_than_replaced(self):
        cs = _cs()
        assert cs['gross_pnl'] == pytest.approx(10.0)
        assert cs['net_pnl'] < cs['gross_pnl']

    def test_costs_fall_monotonically_as_the_fee_rises(self):
        cs = _cs(gross_pnl=10.0, costs=1.0)
        nets = [s['net_pnl'] for s in cs['scenarios']]
        assert nets == sorted(nets, reverse=True)

    def test_venue_fee_scenario_equals_the_explicit_venue_number(self):
        cs = _cs(commission=0.0005, slippage=0.0005)
        venue = [s for s in cs['scenarios']
                 if s['fee_bps_per_side'] == BINANCE_SPOT_VIP0_BPS_PER_SIDE][0]
        assert venue['net_pnl'] == pytest.approx(cs['net_pnl_at_venue_fee'])

    def test_zero_fee_row_still_charges_the_non_fee_costs(self):
        # At a zero exchange fee the book still pays slippage: calling this row
        # "gross" would overstate the edge.
        cs = _cs(gross_pnl=1.0, costs=3.0, commission=0.001, slippage=0.0005)
        zero = [s for s in cs['scenarios'] if s['fee_bps_per_side'] == 0.0][0]
        # scale(0) = 0.0005/0.0015 = 1/3 -> cost 1.0 -> net 0.0
        assert zero['net_pnl'] == pytest.approx(0.0)
        assert zero['clears'] is False
        assert cs['net_pnl_at_zero_fee'] == pytest.approx(0.0)

    def test_spread_is_treated_as_a_non_fee_cost(self):
        cs = _cs(commission=0.001, slippage=0.0002, spread=0.0003, costs=2.0,
                 gross_pnl=4.0)
        assert cs['modelled_spread_bps_per_side'] == pytest.approx(3.0)
        zero = [s for s in cs['scenarios'] if s['fee_bps_per_side'] == 0.0][0]
        # non-fee share = (0.0002+0.0003)/0.0015 = 1/3 of 2.0
        assert zero['net_pnl'] == pytest.approx(4.0 - 2.0 / 3)

    def test_round_trip_pays_the_cost_twice(self):
        cs = _cs(commission=0.001, slippage=0.0005)
        assert cs['modelled_cost_bps_per_side'] == pytest.approx(15.0)
        assert cs['modelled_cost_bps_per_round_trip'] == pytest.approx(30.0)
        assert cs['min_gross_bps_per_round_trip_to_break_even'] == pytest.approx(30.0)


class TestBreakEven:
    def test_hand_computed_break_even(self):
        # gross 10, costs 1 at a 15 bps modelled rate (10 fee + 5 slippage).
        # cost multiplier m = 10/1 = 10 -> total rate 150 bps -> fee = 145 bps.
        cs = _cs(gross_pnl=10.0, costs=1.0, commission=0.001, slippage=0.0005)
        assert cs['break_even_bps_per_side'] == pytest.approx(145.0)
        assert 'zero fee already clears' in cs['break_even_basis']

    def test_break_even_is_never_a_negative_fee(self):
        # gross 1.0 vs costs 100 at 15 bps: even the slippage-only cost (1/3 of
        # the rate -> 33.3) exceeds the edge, so no venue fee can save it.
        cs = _cs(gross_pnl=1.0, costs=100.0, commission=0.001, slippage=0.0005,
                 unit_values=[-99.0])
        assert cs['break_even_bps_per_side'] is None
        assert 'zero exchange fee' in cs['break_even_basis']
        assert cs['clears_modelled_costs'] is False
        assert all(not s['clears'] for s in cs['scenarios'])

    def test_no_costs_leaves_break_even_undefined(self):
        cs = _cs(costs=0.0, gross_pnl=50.0)
        assert cs['break_even_bps_per_side'] is None
        assert 'never traded' in cs['break_even_basis']

    def test_a_losing_book_has_no_break_even(self):
        cs = _cs(gross_pnl=-5.0, costs=1.0, unit_values=[-1.25] * 40)
        assert cs['break_even_bps_per_side'] is None
        assert all(not s['clears'] for s in cs['scenarios'])

    def test_every_scenario_agrees_with_the_break_even(self):
        for gross, costs in ((10.0, 1.0), (0.2, 1.0), (0.0, 1.0), (5.0, 0.0)):
            cs = _cs(gross_pnl=gross, costs=costs)
            be = cs['break_even_bps_per_side']
            for s in cs['scenarios']:
                if be is None:
                    assert s['clears'] == (costs == 0 and gross > 0), (gross, costs, s)
                else:
                    assert s['clears'] == (s['fee_bps_per_side'] < be), (gross, be, s)


class TestMeanSignificance:
    def test_hand_computed_interval(self):
        sig = mean_significance([10.0, -10.0])
        assert sig['n'] == 2
        assert sig['mean'] == pytest.approx(0.0)
        assert sig['std_err'] == pytest.approx(10.0)
        assert sig['t_stat'] == pytest.approx(0.0)
        assert sig['ci95_low'] == pytest.approx(-19.59963985)
        assert sig['ci95_high'] == pytest.approx(19.59963985)
        assert sig['ci_excludes_zero'] is False
        assert sig['ci_includes_zero'] is True

    def test_a_clear_signal_is_detected(self):
        sig = mean_significance([10.0, 12.0, 8.0, 11.0, 9.0, 10.5])
        assert sig['mean'] > 0
        assert sig['ci_excludes_zero'] is True
        assert sig['ci95_low'] > 0

    def test_negative_ci_excludes_zero_but_is_not_a_cost_claim(self):
        sig = mean_significance([-10.0, -12.0, -8.0, -11.0, -9.0, -10.5])
        assert sig['ci_excludes_zero'] is True
        assert sig['ci95_high'] < 0

    def test_zero_variance_does_not_fabricate_an_interval(self):
        sig = mean_significance([5.0, 5.0, 5.0])
        assert sig['std_err'] == pytest.approx(0.0)
        assert sig['t_stat'] is None
        assert sig['ci_excludes_zero'] is None
        assert sig['ci_includes_zero'] is None
        assert 'zero variance' in sig['note']

    def test_one_observation_has_no_interval(self):
        sig = mean_significance([5.0])
        assert sig['n'] == 1
        assert sig['mean'] is None
        assert sig['ci_excludes_zero'] is None
        assert sig['reliable_sample'] is False

    def test_reliability_uses_the_floor_not_a_lower_number(self):
        assert mean_significance([1.0] * 29)['reliable_sample'] is False
        assert mean_significance([1.0] * 30)['reliable_sample'] is True

    def test_basis_is_stated_so_cis_are_not_comparable_across_engines(self):
        assert mean_significance([1.0, 2.0])['basis'] == 'per realized round trip'
        assert mean_significance([1.0, 2.0], basis='per bar')['basis'] == 'per bar'


class TestTradeableClaimGate:
    def test_all_four_gates_must_pass(self):
        # 40 round trips, all positive but not identical (identical values have no
        # spread, so no interval could exist).
        cs = _cs(gross_pnl=10.0, costs=1.0, commission=0.001, slippage=0.0005,
                 unit_values=[1.5 + 0.01 * (i % 7) for i in range(40)])
        assert cs['tradeable_claim_allowed'] is True
        assert cs['claim_blockers'] == []
        assert cs['gates']['clears_modelled_costs'] is True
        assert cs['gates']['clears_venue_fee'] is True
        assert cs['gates']['sample_is_reliable'] is True
        assert cs['gates']['ci_excludes_zero_positive'] is True

    def test_a_thin_edge_clears_gross_but_not_the_venue_fee(self):
        # gross 0.5 vs costs 1.0: profitable looking at a zero fee, not at VIP0.
        cs = _cs(gross_pnl=0.5, costs=1.0, commission=0.001, slippage=0.0)
        assert cs['net_pnl_at_zero_fee'] > 0
        assert cs['clears_venue_fee'] is False
        assert cs['tradeable_claim_allowed'] is False
        assert 'clears_venue_fee' in cs['claim_blockers']

    def test_an_unproven_ci_blocks_a_claim_without_calling_it_a_loss(self):
        cs = _cs(gross_pnl=10.0, costs=1.0, unit_values=[10.0, -10.0, 10.0, -10.0])
        assert cs['significance']['ci_includes_zero'] is True
        assert cs['tradeable_claim_allowed'] is False
        assert set(cs['claim_blockers']) == {'ci_excludes_zero_positive', 'sample_is_reliable'}
        assert 'UNPROVEN' in cs['claim_note']

    def test_a_book_that_clears_costs_but_is_too_small_to_test_is_blocked(self):
        cs = _cs(unit_values=[5.0 + 0.1 * i for i in range(5)])
        assert cs['clears_venue_fee'] is True
        assert cs['gates']['sample_is_reliable'] is False
        assert cs['tradeable_claim_allowed'] is False

    def test_the_output_is_json_serialisable(self):  # noqa: PLR0915
        # A report that cannot be dumped is a report nobody can audit.
        cs = _cs()
        assert json.loads(json.dumps(cs))['gates']['clears_venue_fee'] is True

    def test_gates_are_plain_bools_not_numpy_bools(self):
        # `np.True_ is True` is False: a numpy bool silently fails every
        # `is True` / `is False` check downstream, including the gates above.
        cs = _cs(gross_pnl=np.float64(10.0), costs=np.float64(1.0),
                 unit_values=[np.float64(1.5 + 0.01 * (i % 7)) for i in range(40)])
        for name, value in cs['gates'].items():
            assert value is True or value is False, name
        assert cs['tradeable_claim_allowed'] is True
        for s in cs['scenarios']:
            assert s['clears'] is True or s['clears'] is False


def _vectorized(tmp_path, prices, signals, commission=0.0005, slippage=0.0003,
                spread=0.0002):
    """Run the vectorized engine on an inline config file (no repo config bias)."""
    import yaml

    dates = pd.date_range('2020-01-01', periods=len(prices), freq='D')
    prices = np.asarray(prices, dtype=float)
    data = {'A': pd.DataFrame({
        'open': prices, 'high': prices, 'low': prices, 'close': prices,
        'volume': np.full(len(prices), 1e6)}, index=dates)}
    sig = {'A': pd.Series(signals, index=dates, dtype=float)}
    config = {'universe': {'equity': ['A']},
              'backtest': {'initial_capital': 100000,
                           'costs': {'commission': commission, 'slippage': slippage,
                                     'spread': spread}}}
    path = tmp_path / 'settings.yaml'
    path.write_text(yaml.safe_dump(config))
    bt = VectorizedBacktester(str(path))
    return bt, bt.run_backtest(signals=sig, data=data, initial_capital=100000)


class TestVectorizedEngineReportsNet:
    def test_gross_and_net_are_both_reported(self, tmp_path):
        # Flat price with one entry and one exit: zero gross, positive costs.
        bt, results = _vectorized(tmp_path, [100.0] * 6, [0, 1, 1, 1, 0, 0])
        totals = results['cost_totals']
        cs = results['cost_sensitivity']
        assert totals['gross'] == pytest.approx(0.0)
        assert totals['costs'] > 0
        assert cs['net_pnl'] == pytest.approx(totals['gross'] - totals['costs'])
        assert cs['clears_modelled_costs'] is False

    def test_costs_are_turnover_times_the_combined_rate(self, tmp_path):
        # Two units of turnover (0->1, 1->0) at 5+3+2 = 10 bps = 0.002 total.
        bt, results = _vectorized(tmp_path, [100.0, 101.0, 102.0], [0, 1, 0])
        totals = results['cost_totals']
        assert totals['turnover'] == pytest.approx(2.0)
        assert totals['cost_rate_per_side'] == pytest.approx(0.001)
        assert totals['costs'] == pytest.approx(0.002)

    def test_holding_loses_the_fee_even_when_the_price_runs(self, tmp_path):
        # Entered on bar 1 (100->110), so the position earns bar 2's move
        # (110->120 = 9.09%), never the +10% that produced the signal.
        gross = 120 / 110 - 1
        bt, gross_results = _vectorized(tmp_path, [100.0, 110.0, 120.0], [0, 1, 1],
                                        commission=0.0, slippage=0.0, spread=0.0)
        bt, net_results = _vectorized(tmp_path, [100.0, 110.0, 120.0], [0, 1, 1],
                                      commission=0.001, slippage=0.0, spread=0.0)
        assert gross_results['cost_totals']['costs'] == pytest.approx(0.0)
        assert gross_results['metrics']['total_return'] == pytest.approx(gross)
        # One unit of turnover (flat -> long) pays the 10 bps entry fee.
        assert gross_results['cost_totals']['turnover'] == pytest.approx(1.0)
        assert net_results['metrics']['total_return'] == pytest.approx(gross - 0.001)
        assert net_results['cost_sensitivity']['gross_pnl'] == pytest.approx(gross)
        assert net_results['cost_sensitivity']['net_pnl'] == pytest.approx(gross - 0.001)

    def test_the_config_default_commission_is_flagged_as_half_the_venue_fee(self, tmp_path):
        bt, results = _vectorized(tmp_path, [100.0, 101.0, 102.0], [0, 1, 0])
        cs = results['cost_sensitivity']
        assert cs['modelled_commission_bps_per_side'] == pytest.approx(5.0)
        assert cs['commission_below_venue_fee'] is True

    def test_the_ladder_uses_the_venue_fee_not_the_config_commission(self, tmp_path):
        bt, results = _vectorized(tmp_path, [100.0, 101.0, 102.0], [0, 1, 0])
        cs = results['cost_sensitivity']
        venue = [s for s in cs['scenarios']
                 if s['fee_bps_per_side'] == BINANCE_SPOT_VIP0_BPS_PER_SIDE][0]
        # turnover 2 units; at 10 bps fee + 5 bps slip/spread -> 0.003 of cost.
        assert venue['net_pnl'] == pytest.approx(cs['gross_pnl'] - 2 * 0.0015)

    def test_win_rate_is_labelled_as_a_per_bar_rate(self, tmp_path):
        bt, results = _vectorized(tmp_path, [100.0, 101.0, 102.0, 103.0], [0, 1, 1, 0])
        sheet = bt.get_tear_sheet()
        assert 'positive BARS' in sheet
        assert 'GROSS vs NET' in sheet
        assert 'Tradeable claim allowed: False' in sheet

    def test_profit_factor_is_none_rather_than_inf_when_nothing_lost(self, tmp_path):
        # Costless, so the entry fee does not manufacture a losing bar: this book
        # genuinely has no negative observation, which is what makes the ratio
        # undefined rather than a division by zero.
        bt, results = _vectorized(tmp_path, [100.0, 101.0, 102.0, 103.0], [0, 1, 1, 0],
                                  commission=0.0, slippage=0.0, spread=0.0)
        assert results['metrics']['profit_factor'] is None
        assert 'inf' not in bt.get_tear_sheet()
        assert 'undefined' in bt.get_tear_sheet()

    def test_a_book_with_losses_still_reports_a_ratio(self, tmp_path):
        bt, results = _vectorized(tmp_path, [100.0, 103.0, 100.0, 104.0], [0, 1, 1, 0])
        pf = results['metrics']['profit_factor']
        assert pf is not None
        assert np.isfinite(pf)

    def test_no_lookahead_the_position_is_still_lagged_one_bar(self, tmp_path):
        # A signal on bar i earns bar i+1's return, never bar i's.
        bt, results = _vectorized(tmp_path, [100.0, 200.0, 200.0], [0, 1, 0],
                                  commission=0.0, slippage=0.0, spread=0.0)
        # Doubling on bar 1 is not earned (position was flat); the 0% move on
        # bar 2 is earned with a long.
        assert results['cost_totals']['gross'] == pytest.approx(0.0)

    def test_both_engines_agree_on_the_venue_reference(self, tmp_path):
        """The two engines report different units, but they must agree on which
        venue fee they assumed and on funding not being modelled."""
        bt, vec = _vectorized(tmp_path, [100.0, 110.0], [0, 1])
        evt = event_driven.EventDrivenBacktester().run_backtest(
            signals={'A': pd.Series([1.0, 0.0],
                                    index=pd.date_range('2020-01-01', periods=2)),
                     },
            data={'A': pd.DataFrame(
                {'close': [100.0, 110.0]},
                index=pd.date_range('2020-01-01', periods=2))},
            commission=0.001, slippage=0.0)
        assert vec['cost_sensitivity']['venue'] == evt['cost_sensitivity']['venue']
        assert vec['cost_sensitivity']['funding_modelled'] is False
        assert evt['cost_sensitivity']['funding_modelled'] is False
