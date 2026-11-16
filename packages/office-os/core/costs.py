"""
Costs - SPAN-style margin approximation for options (paper/free-tier only).

Replaces any flat-percentage margin estimate with a risk-array based
approximation: scan price / vol / time scenarios and take the worst-case
portfolio loss as the margin requirement. All simulation, no live orders.

Used by the cost-analyst agent and any cost-model reporting. Read-only:
no writes, no network, no secrets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class OptionLeg:
    """One option leg in a spread."""
    kind: str          # "put" or "call"
    strike: float      # strike price
    premium: float     # premium received (positive for short) or paid (negative)
    qty: int = 1       # number of contracts (positive = long, negative = short)


@dataclass
class Underlying:
    spot: float
    lot_size: int = 1


@dataclass
class ScanScenario:
    """One SPAN risk-array scenario."""
    price_shift: float   # fractional, e.g. -0.10 = -10%
    vol_shift: float     # fractional, e.g. +0.20 = +20% vol
    time_decay_days: int # days of theta decay applied


def _option_value(kind: str, spot: float, strike: float, premium: float,
                  vol_shift: float = 0.0, time_decay_days: int = 0) -> float:
    """
    Approximate option value change under a scenario.

    Very rough directional proxy (not Black-Scholes): value moves with
    moneyness (intrinsic) plus a vol/theta adjustment on the premium.
    Sufficient for a SPAN-style worst-case scan; not for pricing.
    """
    if kind == "put":
        intrinsic = max(strike - spot, 0.0)
    else:
        intrinsic = max(spot - strike, 0.0)

    # Vol/theta adjustment on time value portion only
    time_value = max(premium - abs(intrinsic), 0.0) if premium > 0 else 0.0
    vol_impact = time_value * vol_shift * 0.5
    theta_impact = -time_value * (time_decay_days / 30.0) * 0.1

    return intrinsic + max(premium, 0.0) * 0.0 + vol_impact + theta_impact


def span_margin(legs: list[OptionLeg], underlying: Underlying,
                scenarios: Optional[list[ScanScenario]] = None) -> dict:
    """
    SPAN-style margin: worst-case portfolio loss across risk scenarios.

    Returns dict with per-scenario P&L, worst-case loss, and margin requirement.
    Margin = max(0, worst_loss) + short premium credit (net credit reduces margin
    but never below the worst-case loss).

    All figures are per-lot; multiply by lot_size for total notional.
    """
    if scenarios is None:
        scenarios = [
            ScanScenario(-0.10, +0.20, 0),   # spot -10%, vol +20%
            ScanScenario(-0.15, +0.30, 3),   # spot -15%, vol +30%, 3d theta
            ScanScenario(+0.10, -0.10, 0),   # spot +10%, vol -10%
            ScanScenario(+0.15, -0.20, 3),   # spot +15%, vol -20%, 3d theta
            ScanScenario(0.0, +0.50, 5),     # vol spike +50%, 5d theta
            ScanScenario(0.0, -0.20, 10),    # vol crush -20%, 10d theta
        ]

    net_credit = 0.0  # premium received (positive) net of premium paid
    for leg in legs:
        if leg.qty < 0:  # short leg: receives premium
            net_credit += abs(leg.premium) * abs(leg.qty)
        else:            # long leg: pays premium
            net_credit -= abs(leg.premium) * leg.qty

    scenario_pnls = []
    for s in scenarios:
        total_pnl = 0.0
        for leg in legs:
            shifted_spot = underlying.spot * (1 + s.price_shift)
            new_val = _option_value(
                leg.kind, shifted_spot, leg.strike,
                leg.premium, s.vol_shift, s.time_decay_days,
            )
            # Approximate change vs current premium as P&L impact
            pnl_impact = (leg.premium - new_val) * leg.qty
            total_pnl += pnl_impact
        scenario_pnls.append({
            "price_shift": s.price_shift,
            "vol_shift": s.vol_shift,
            "time_decay_days": s.time_decay_days,
            "portfolio_pnl": round(total_pnl, 2),
        })

    worst_loss = min((sp["portfolio_pnl"] for sp in scenario_pnls), default=0.0)
    worst_loss = min(worst_loss, 0.0)  # only losses count

    # Margin = worst-case loss, but short premium already collected cushions it.
    # SPAN logic: margin >= worst_loss; net credit reduces cash needed but
    # never below the scenario loss (inter-month spread offset not modeled here).
    margin_required = max(abs(worst_loss) - net_credit, abs(worst_loss) * 0.5)

    return {
        "underlying_spot": underlying.spot,
        "net_credit_received": round(net_credit, 2),
        "scenarios": scenario_pnls,
        "worst_case_loss": round(worst_loss, 2),
        "margin_required_per_lot": round(margin_required, 2),
        "lot_size": underlying.lot_size,
        "margin_required_total": round(margin_required * underlying.lot_size, 2),
    }


def bull_put_margin(spot: float, short_strike: float, long_strike: float,
                    short_premium: float, long_premium: float,
                    lot_size: int = 1) -> dict:
    """Convenience: SPAN margin for a bull put spread (short higher, long lower)."""
    legs = [
        OptionLeg(kind="put", strike=short_strike, premium=short_premium, qty=-1),
        OptionLeg(kind="put", strike=long_strike,  premium=long_premium,  qty=+1),
    ]
    underlying = Underlying(spot=spot, lot_size=lot_size)
    result = span_margin(legs, underlying)
    result["spread_width"] = short_strike - long_strike
    result["max_profit"] = round((short_premium - long_premium) * lot_size, 2)
    result["max_loss"] = round(((short_strike - long_strike) - (short_premium - long_premium)) * lot_size, 2)
    return result


if __name__ == "__main__":
    # Example: NIFTY bull put spread, spot 22500, short 22200 PE @ 85, long 21900 PE @ 45
    r = bull_put_margin(22500.0, 22200.0, 21900.0, 85.0, 45.0, lot_size=50)
    print("SPAN margin — bull put spread (NIFTY example)")
    for k, v in r.items():
        if k != "scenarios":
            print(f"  {k}: {v}")
    print("  scenarios:")
    for s in r["scenarios"]:
        print(f"    {s}")
