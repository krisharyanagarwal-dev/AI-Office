"""
Volatility breakout factors for alpha-system.

Design
------
A Donchian channel breakout: the factor is positive when price makes a new
high over the channel window (excluding the current bar, so the signal cannot
reference its own extreme) and negative on a new low.

The exclusion of the current bar is the whole point. ``rolling(window).max()``
*including* the present bar makes the breakout condition true on exactly the
bar that sets the extreme, which turns the factor into a restatement of the
high. Shifting the channel by one bar is what makes it a genuine
look-ahead-free signal, so the shift is not optional and is asserted by a test.

Cost note
---------
No fees, slippage or funding are modelled anywhere in this module. Output is
gross. Use ``paper-benchmark/cost_model.py`` before treating any signal here as
tradeable.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from alpha.factors.base import FactorBase, FactorConfig


class VolatilityBreakoutFactor(FactorBase):
    """
    Donchian channel breakout, signed and scaled by channel width.

    Emits one column per lookback:
        breakout_{lb}      +1/-1/0 position in the channel, scaled by how far
                           past the channel price sits, as a fraction of width.
        channel_width_{lb} the channel width in return units, which is the
                           realised range the signal is measured against.
    """

    @property
    def category(self) -> str:
        return "breakout"

    def __init__(
        self,
        lookbacks: List[int] = [20, 55, 100],
        scale: bool = True,
        **params
    ):
        config = FactorConfig(
            name="VolatilityBreakout",
            category="breakout",
            description="Donchian channel breakout, scaled by channel width",
            params={'lookbacks': lookbacks, 'scale': scale},
            dependencies=["momentum"],
            tags=["trend", "breakout", "channel"],
        )
        super().__init__(config, **params)

    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        lookbacks = self.params.get('lookbacks', [20, 55, 100])
        scale = self.params.get('scale', True)

        results = {}
        for lb in lookbacks:
            # shift(1) so the channel excludes the current bar; without this the
            # breakout condition is trivially true on the bar making the extreme.
            prior_high = prices.rolling(lb).max().shift(1)
            prior_low = prices.rolling(lb).min().shift(1)
            width = (prior_high - prior_low) / prices

            # Initialise to 0.0, not NaN: 0 means "inside the channel", and the
            # branch below keys off raw == 0. Starting from NaN would make every
            # in-channel bar NaN instead, silently voiding the factor.
            raw = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
            raw = raw.mask(prices >= prior_high, 1.0)
            raw = raw.mask(prices <= prior_low, -1.0)

            if scale:
                # Position within the channel, in [-1, 1]. A zero-width channel
                # carries no breakout information at all, so it maps to 0.0 (no
                # position) rather than NaN. NaN is reserved for the genuine
                # warmup period where the channel does not exist yet.
                midpoint = (prior_high + prior_low) / 2
                half_width = (width / 2).replace(0, np.nan)
                scaled = ((prices - midpoint) / half_width).clip(-1, 1)
                # A zero-width channel means no position, so it maps to 0.0.
                # mask(width == 0) rather than fillna: warmup, where the channel
                # does not exist yet, has width NaN and must stay NaN so callers
                # can tell "unknown" apart from "flat and directionless".
                scaled = scaled.mask(width == 0, 0.0)
                # Inside the channel the factor is the continuous position; on a
                # breakout it is that position signed by direction.
                value = scaled.where(raw == 0, raw * scaled)
            else:
                value = raw

            results[f'breakout_{lb}'] = value.stack(future_stack=True)
            results[f'channel_width_{lb}'] = width.stack(future_stack=True)

        return pd.concat(results, axis=1)


class ChannelExpansionFactor(FactorBase):
    """
    Channel expansion: how much the recent range exceeds the longer-run range.

    A breakout is only interesting when the market was previously quiet. This
    factor is the regime gate for VolatilityBreakoutFactor: high values mean the
    current range is an expansion, low values mean the market is compressed.

    Output is a ratio in [0, inf), not a signed position.
    """

    @property
    def category(self) -> str:
        return "breakout"

    def __init__(
        self,
        short: int = 20,
        long: int = 100,
        **params
    ):
        config = FactorConfig(
            name="ChannelExpansion",
            category="breakout",
            description="Short-window range divided by long-window range",
            params={'short': short, 'long': long},
            dependencies=["breakout"],
            tags=["regime", "volatility", "squeeze"],
        )
        super().__init__(config, **params)

    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        short = self.params.get('short', 20)
        long = self.params.get('long', 100)

        returns = prices.pct_change()

        short_range = returns.rolling(short).std()
        long_range = returns.rolling(long).std()

        # Guard both divisions. A zero long-run volatility means a flat market,
        # where expansion is undefined rather than infinite.
        expansion = (short_range / long_range.replace(0, np.nan)).clip(0, 20)

        results = {
            f'expansion_{short}_{long}': expansion.stack(future_stack=True),
            f'short_range_{short}': short_range.stack(future_stack=True),
            f'long_range_{long}': long_range.stack(future_stack=True),
        }

        return pd.concat(results, axis=1)