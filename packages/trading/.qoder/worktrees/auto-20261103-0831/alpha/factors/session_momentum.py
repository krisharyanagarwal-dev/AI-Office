"""
Session-based momentum factors for alpha-system.

Design
------
Classic intraday session effect: an asset that moved during one session tends
to drift in the same direction during the next, and the effect is strongest
across adjacent liquid sessions. This module measures momentum *within* named
UTC sessions and reports the carry from one session to the next.

Session boundaries (UTC)
------------------------
    asia    00:00 - 07:59
    london  07:00 - 15:59   (overlaps asia by one hour)
    ny      13:00 - 21:59   (overlaps london by three hours)
    off     22:00 - 23:59

The windows overlap on purpose: they are liquidity windows, not a partition, and
overlapping sessions mean a bar can contribute to more than one. Resampling to
each window independently keeps the arithmetic simple and makes the overlap
explicit rather than implicit.

No costs are modelled. Output is gross of fees, slippage and funding; use
``paper-benchmark/cost_model.py`` before treating any of this as tradeable.
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from alpha.factors.base import FactorBase, FactorConfig

# Inclusive-start, exclusive-end UTC windows.
SESSION_WINDOWS: Dict[str, tuple] = {
    "asia": (0, 8),
    "london": (7, 16),
    "ny": (13, 22),
}

_DEFAULT_SESSIONS = ["asia", "london", "ny"]


class SessionMomentumFactor(FactorBase):
    """
    Intraday return per session, plus the lagged carry between sessions.

    Emits, per session:
        {session}_ret          return from session open to session close
        {session}_carry        previous session's return for the same ticker
    """

    @property
    def category(self) -> str:
        return "momentum"

    def __init__(
        self,
        sessions: Optional[List[str]] = None,
        **params
    ):
        # `sessions is None` means "use the defaults"; an explicit empty list
        # means "no sessions", so the check must not be a bare truthiness test.
        chosen = list(_DEFAULT_SESSIONS if sessions is None else sessions)
        unknown = [s for s in chosen if s not in SESSION_WINDOWS]
        if unknown:
            raise ValueError(
                f"unknown session(s) {unknown}; expected a subset of "
                f"{sorted(SESSION_WINDOWS)}"
            )
        config = FactorConfig(
            name="SessionMomentum",
            category="momentum",
            description="Intraday session returns and their lagged carry",
            params={'sessions': chosen},
            dependencies=["momentum"],
            tags=["intraday", "session", "overnight"],
        )
        super().__init__(config, **params)

    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise ValueError("prices index must be a DatetimeIndex")

        sessions = self.params.get('sessions', list(_DEFAULT_SESSIONS))

        # Work in UTC. Converting here (rather than trusting the caller's tz)
        # keeps the session boundaries meaningful regardless of input timezone.
        index = prices.index
        if index.tz is None:
            index_utc = index.tz_localize("UTC")
        else:
            index_utc = index.tz_convert("UTC")
        hours = index_utc.hour

        results = {}
        for name in sessions:
            start_h, end_h = SESSION_WINDOWS[name]
            mask = (hours >= start_h) & (hours < end_h)

            session_close = prices.loc[mask].resample("D").last()
            session_open = prices.loc[mask].resample("D").first()

            # A day with no bar inside the window yields NaN for both; the
            # division below is guarded so it cannot raise.
            with np.errstate(divide="ignore", invalid="ignore"):
                ret = (session_close - session_open) / session_open

            daily = ret.stack(future_stack=True)
            results[f'{name}_ret'] = daily
            # Carry is the previous observed session for that ticker, so a day
            # with no session bar does not fabricate a zero return.
            results[f'{name}_carry'] = daily.groupby(level=1).shift(1)

        # No sessions requested is a legitimate configuration, and pd.concat
        # raises on an empty dict, so return an explicit empty frame.
        if not results:
            return pd.DataFrame()
        return pd.concat(results, axis=1)


class SessionOverlapFactor(FactorBase):
    """
    How much of a session's move happened in the overlap with the next session.

    A breakout that starts in one session and continues into the next is a
    different animal from one that dies at the boundary. This reports the
    fraction of the total session return that was already present at the
    overlap boundary.

    Values are bounded in [-1, 1] by construction; a zero-move session gives 0.
    """

    @property
    def category(self) -> str:
        return "momentum"

    def __init__(
        self,
        sessions: Optional[List[str]] = None,
        **params
    ):
        # `sessions is None` means "use the defaults"; an explicit empty list
        # means "no sessions", so the check must not be a bare truthiness test.
        chosen = list(_DEFAULT_SESSIONS if sessions is None else sessions)
        config = FactorConfig(
            name="SessionOverlap",
            category="momentum",
            description="Fraction of a session's move present at the next overlap",
            params={'sessions': chosen},
            dependencies=["momentum"],
            tags=["intraday", "session"],
        )
        super().__init__(config, **params)

    def compute(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise ValueError("prices index must be a DatetimeIndex")

        sessions = self.params.get('sessions', list(_DEFAULT_SESSIONS))
        index_utc = (
            prices.index.tz_localize("UTC")
            if prices.index.tz is None else prices.index.tz_convert("UTC")
        )
        hours = index_utc.hour

        # Overlap boundary = the later session's start hour, which is inside the
        # earlier session because the windows are deliberately overlapping.
        starts = {name: SESSION_WINDOWS[name][0] for name in sessions}
        ends = {name: SESSION_WINDOWS[name][1] for name in sessions}
        ordered = sorted(sessions, key=lambda s: starts[s])

        results = {}
        for earlier, later in zip(ordered, ordered[1:]):
            boundary_h = starts[later]

            early_mask = (hours >= starts[earlier]) & (hours < boundary_h)

            early = prices.loc[early_mask].resample("D").last()
            full = prices.loc[
                (hours >= starts[earlier]) & (hours < ends[earlier])
            ].resample("D").last()
            open_ = prices.loc[
                (hours >= starts[earlier]) & (hours < ends[earlier])
            ].resample("D").first()

            with np.errstate(divide="ignore", invalid="ignore"):
                total = (full - open_) / open_
                early_part = (early - open_) / open_

            # Guard the ratio: a session with no net move has no meaningful split.
            denominator = total.replace(0, np.nan)
            share = (early_part / denominator).clip(-1, 1).fillna(0.0)
            results[f'{earlier}_to_{later}_share'] = share.stack(future_stack=True)

        # A single session has no adjacent pair, so there is nothing to report.
        # pd.concat raises on an empty dict, so return an explicit empty frame
        # rather than blowing up on a legitimate configuration.
        if not results:
            return pd.DataFrame()
        return pd.concat(results, axis=1)