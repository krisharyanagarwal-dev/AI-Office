"""
Cost model and inference for backtest results.

Gross edge is not profit. Every engine in this package routes its headline
numbers through here so that a result states, in the same object that carries
the P&L:

* the venue and fee assumed (Binance spot at VIP 0 charges 0.1% = 10 bps on
  BOTH maker and taker fills);
* the net P&L at that fee, plus a ladder of other fees;
* the fee at which the book stops paying (break-even);
* whether the mean per-unit P&L is distinguishable from zero at all.

A CI that includes zero means the edge is UNPROVEN. It is never read as
evidence that the book loses, and it never indicates a direction.
"""

# Binance spot at VIP 0 charges 0.1% (10 bps) on BOTH maker and taker fills.
# Used only as the reference venue when netting a book; it never overrides the
# rates actually passed to an engine.
BINANCE_SPOT_VIP0_BPS_PER_SIDE = 10.0

# Below this many observations a normal-approximation CI on the mean is not
# trustworthy, so it may not support a claim either way. Raising it is allowed;
# lowering it invalidates every verdict produced against it.
MIN_OBSERVATIONS_FOR_CI = 30

_Z_95 = 1.959963985  # two-sided 95% normal quantile

# The fee ladder every book is netted at, in bps per side.
_FEE_LADDER = (
    (0.0, 'zero exchange fee, non-fee costs still charged'),
    (5.0, '5 bps — half the Binance VIP0 fee'),
    (BINANCE_SPOT_VIP0_BPS_PER_SIDE, 'Binance spot VIP0 maker/taker'),
    (20.0, '2x VIP0'),
    (30.0, '3x VIP0, stressed'),
)


def mean_significance(pnls, basis='per realized round trip',
                      min_reliable_sample=MIN_OBSERVATIONS_FOR_CI):
    """t-style CI on the mean of a per-unit P&L list (normal approximation).

    ``basis`` says what one element is, because a CI on the mean of daily
    returns and a CI on the mean of round trips are different claims and must
    not be interchangeable in a report.
    """
    n = len(pnls)
    out = {
        'basis': basis,
        'n': int(n),
        'mean': None,
        'std_err': None,
        't_stat': None,
        'ci95_low': None,
        'ci95_high': None,
        'ci_excludes_zero': None,
        'ci_includes_zero': None,
        'reliable_sample': bool(n >= min_reliable_sample),
        'min_reliable_sample': int(min_reliable_sample),
    }
    if n < 2:
        out['note'] = 'fewer than 2 observations: no spread, so no interval exists'
        return out
    mean = float(sum(float(p) for p in pnls) / n)
    sd = float((sum((float(p) - mean) ** 2 for p in pnls) / (n - 1)) ** 0.5)
    se = sd / (n ** 0.5)
    out['mean'] = mean
    out['std_err'] = se
    if se > 0:
        low = mean - _Z_95 * se
        high = mean + _Z_95 * se
        out['t_stat'] = mean / se
        out['ci95_low'] = low
        out['ci95_high'] = high
        excludes = bool(low > 0 or high < 0)
        out['ci_excludes_zero'] = excludes
        out['ci_includes_zero'] = not excludes
    else:
        out['note'] = ('every observation settled at the same value: zero variance, '
                       'so no interval exists')
    return out


def cost_sensitivity(gross_pnl, costs, commission, slippage, unit_values,
                     spread=0.0, exit_cost_on_open_positions=0.0,
                     venue_fee_bps=BINANCE_SPOT_VIP0_BPS_PER_SIDE,
                     min_reliable_sample=MIN_OBSERVATIONS_FOR_CI,
                     basis='per realized round trip',
                     non_fee_note='slippage'):
    """Net a book at several venue fees and report the fee it stops paying at.

    Fill (or turnover) sizes are set by the signals and do not depend on the fee,
    so total cost scales exactly linearly with the per-side rate:
    ``net = gross - units * (fee + non_fee_costs)``. That makes the break-even
    fee solvable in closed form instead of needing a re-run — and the linearity
    itself is pinned by a test.

    Args:
        gross_pnl: P&L before any cost, same units as ``costs``.
        costs: cost actually charged at the modelled rates.
        commission: the modelled exchange-fee rate per side, as a fraction.
        slippage / spread: the modelled non-fee costs per side, as fractions.
        unit_values: per-observation P&L list for the CI (round trips, bars...).
        exit_cost_on_open_positions: fee a still-open position has not paid yet.
    """
    gross_pnl = float(gross_pnl)
    costs = float(costs)
    non_fee = float(slippage) + float(spread)
    modelled_rate = float(commission) + non_fee

    def scale(fee_bps):
        # Only the venue fee moves; slippage and spread stay at their modelled
        # rate, because a cheaper venue does not fill you better.
        return ((fee_bps / 1e4 + non_fee) / modelled_rate) if modelled_rate > 0 else 0.0

    scenarios = []
    for fee_bps, label in _FEE_LADDER:
        net = gross_pnl - costs * scale(fee_bps)
        scenarios.append({
            'fee_bps_per_side': float(fee_bps),
            'label': label,
            'net_pnl': float(net),
            'clears': bool(net > 0),
        })

    net_at_modelled = gross_pnl - costs
    net_at_venue = gross_pnl - costs * scale(venue_fee_bps)
    net_at_zero_fee = gross_pnl - costs * scale(0.0)
    if costs <= 0:
        break_even_bps = None
        break_even_basis = 'no costs were charged (the book never traded): break-even is undefined'
    elif net_at_zero_fee <= 0:
        # A negative fee is not a thing a venue can charge, so there is no fee at
        # which this book pays: the non-fee costs alone already eat the edge.
        break_even_bps = None
        break_even_basis = ('no fee clears this book: it loses money even at a zero '
                            f"exchange fee ({non_fee_note} alone exceeds the gross edge)")
    else:
        break_even_bps = (modelled_rate * (gross_pnl / costs) - non_fee) * 1e4
        break_even_basis = (f'per-side fee at which net P&L reaches zero, {non_fee_note} '
                            'held at its modelled rate; always positive here, since a zero '
                            'fee already clears')

    significance = mean_significance(unit_values, basis=basis,
                                    min_reliable_sample=min_reliable_sample)
    checks = {
        'clears_modelled_costs': bool(net_at_modelled > 0),
        'clears_venue_fee': bool(net_at_venue > 0),
        'sample_is_reliable': bool(significance['reliable_sample']),
        'ci_excludes_zero_positive': (significance['ci_excludes_zero'] is True
                                      and (significance['ci95_low'] or 0.0) > 0),
    }
    blockers = [name for name, ok in checks.items() if not ok]
    return {
        'venue': f'Binance spot (reference VIP0 = {venue_fee_bps:g} bps maker and taker per side)',
        'fee_basis': f'charged per side on traded notional; a round trip pays it twice; '
                     f'{non_fee_note} held at its modelled rate',
        'funding_modelled': False,
        'funding_note': (
            'Perpetual funding/carry is NOT modeled. These engines trade a fixed '
            'unit notional, i.e. a spot-style book where funding does not apply; '
            'reused on perps, every net figure here is optimistic by the carry.'
        ),
        'modelled_commission_bps_per_side': float(commission) * 1e4,
        'modelled_slippage_bps_per_side': float(slippage) * 1e4,
        'modelled_spread_bps_per_side': float(spread) * 1e4,
        'modelled_cost_bps_per_side': modelled_rate * 1e4,
        'modelled_cost_bps_per_round_trip': 2 * modelled_rate * 1e4,
        'min_gross_bps_per_round_trip_to_break_even': 2 * modelled_rate * 1e4,
        'commission_below_venue_fee': bool(float(commission) * 1e4 < venue_fee_bps),
        'gross_pnl': gross_pnl,
        'costs_at_modelled': costs,
        'net_pnl': float(net_at_modelled),
        'net_pnl_at_venue_fee': float(net_at_venue),
        'net_pnl_at_zero_fee': float(net_at_zero_fee),
        'exit_cost_on_open_positions': float(exit_cost_on_open_positions),
        'net_pnl_if_flat_at_end': float(net_at_modelled - exit_cost_on_open_positions),
        'clears_modelled_costs': bool(net_at_modelled > 0),
        'clears_venue_fee': bool(net_at_venue > 0),
        'break_even_bps_per_side': None if break_even_bps is None else float(break_even_bps),
        'break_even_basis': break_even_basis,
        'scenarios': scenarios,
        'significance': significance,
        'gates': checks,
        'tradeable_claim_allowed': not blockers,
        'claim_blockers': blockers,
        'claim_note': (
            'A CI that includes zero means the edge is UNPROVEN, not that the book '
            'loses; it blocks a claim, it never indicates a direction.'
        ),
    }
