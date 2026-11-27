"""
Sentiment signal backtest for Dost.

Event-study test of whether negative news/social sentiment (and a high
manipulation score) predicts negative forward N-day returns.

Because keyless web search only yields *current* sentiment (there is no
historical sentiment API), a look-ahead-free historical backtest of
sentiment is not possible. This module instead:

  1. Loads historical OHLCV per symbol (stored files first, optional live
     Yahoo Finance fetch).
  2. Scores current sentiment per symbol via the keyless news/social skills.
  3. Anchors at the most recent candle that still leaves forward data for
     the longest horizon (last candle - max_horizon), applies the current
     sentiment as the signal at that anchor, and computes forward returns
     over each horizon.
  4. Buckets results by sentiment and (optionally) manipulation-score
     tertile, aggregating mean forward return and win rate per bucket.

The output is flagged `look_ahead=True`: current sentiment applied to a
recent-past anchor is the best available signal today, not a
look-ahead-free historical backtest. The machinery is reusable once
historical sentiment becomes available.

Read-only: reads OHLCV and sentiment, writes a JSON report. No live orders,
no credentials.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dost/  (for `skills.*`, `trading.*`)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # AI-Office/ (for `from dost...`)

from dost.data_access import compute_returns, load_ohlcv_from_csv
from dost.trading.market_data import fetch_yahoo_finance, save_ohlcv_to_file

from skills.news_sentiment import get_news_sentiment
from skills.social_sentiment import get_social_sentiment


DEFAULT_HORIZONS = [1, 5, 10, 20]  # trading days

# NIFTY 50 universe (verified symbols, .NS suffix).
DEFAULT_UNIVERSE: List[str] = [
    "ADANIENT.NS", "ADANIPORTS.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJAJFINSV.NS", "BAJFINANCE.NS", "BEL.NS",
    "BHARTIARTL.NS", "CIPLA.NS", "COALINDIA.NS", "DIVISLAB.NS",
    "DRREDDY.NS", "EICHERMOT.NS", "ETERNAL.NS", "GRASIM.NS",
    "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HEROMOTOCO.NS",
    "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "ICICIPRULI.NS",
    "INDUSINDBK.NS", "INFY.NS", "ITC.NS", "JIOFIN.NS",
    "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS", "LTIM.NS",
    "M&M.NS", "MARUTI.NS", "MAXHEALTH.NS", "NESTLEIND.NS",
    "NTPC.NS", "ONGC.NS", "POWERGRID.NS", "RELIANCE.NS",
    "SBILIFE.NS", "SBIN.NS", "SUNPHARMA.NS", "TATACONSUM.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "TCS.NS", "TECHM.NS",
    "TITAN.NS", "TMPV.NS", "ULTRACEMCO.NS", "WIPRO.NS",
]

BACKTEST_DIR = Path(os.path.expanduser("~/.openclaw/backtests"))
SENTIMENT_DIR = BACKTEST_DIR / "sentiment"


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        if result != result or result in (float("inf"), float("-inf")):  # nan / inf
            return None
        return result
    except (TypeError, ValueError):
        return None


def _load_ohlcv(
    symbol: str,
    ohlcv_dir: Optional[Path] = None,
    use_live: bool = False,
    period: str = "1y",
    interval: str = "1d",
) -> List[Dict[str, Any]]:
    """Load OHLCV candles for one symbol, stored files first."""
    if ohlcv_dir is None:
        ohlcv_dir = Path(os.path.expanduser("~/.openclaw/market_data/ohlcv"))
    path = ohlcv_dir / f"{symbol}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    if use_live:
        candles = fetch_yahoo_finance(symbol, period=period, interval=interval)
        if candles:
            save_ohlcv_to_file(candles, symbol)
        return candles
    return []


def _forward_returns(
    candles: List[Dict[str, Any]],
    anchor_idx: int,
    horizons: List[int],
) -> Dict[str, Optional[float]]:
    """Forward simple returns from anchor_idx over each horizon (None if out of range)."""
    if anchor_idx < 0 or anchor_idx >= len(candles):
        return {f"{h}d": None for h in horizons}
    anchor_close = candles[anchor_idx].get("close", 0) or 0
    out: Dict[str, Optional[float]] = {}
    for h in horizons:
        target_idx = anchor_idx + h
        if target_idx >= len(candles) or anchor_close <= 0:
            out[f"{h}d"] = None
        else:
            target_close = candles[target_idx].get("close", 0) or 0
            out[f"{h}d"] = target_close / anchor_close - 1
    return out


def _bucket_tertiles(scores: List[Optional[float]]) -> List[Optional[str]]:
    """Bucket numeric scores into low/mid/high tertiles (None stays None)."""
    valid = [s for s in scores if s is not None]
    if len(valid) < 3:
        return [None] * len(scores)
    lo_cut, hi_cut = sorted(valid)[len(valid) // 3], sorted(valid)[2 * len(valid) // 3]
    buckets: List[Optional[str]] = []
    for s in scores:
        if s is None:
            buckets.append(None)
        elif s <= lo_cut:
            buckets.append("low")
        elif s >= hi_cut:
            buckets.append("high")
        else:
            buckets.append("mid")
    return buckets


@dataclass
class SymbolResult:
    symbol: str
    anchor_date: str
    anchor_price: float
    look_ahead: bool
    news_sentiment: Dict[str, Any]
    social_sentiment: Dict[str, Any]
    manipulation_score: Optional[float] = None
    forward_returns: Dict[str, Optional[float]] = field(default_factory=dict)
    forward_prices: Dict[str, Optional[float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def run_symbol_backtest(
    symbol: str,
    candles: List[Dict[str, Any]],
    news_sentiment: Dict[str, Any],
    social_sentiment: Dict[str, Any],
    manipulation_score: Optional[float] = None,
    anchor_offset: Optional[int] = None,
    horizons: List[int] = DEFAULT_HORIZONS,
) -> SymbolResult:
    """Backtest one symbol: sentiment at anchor -> forward returns over horizons.

    anchor_offset = candles before the end to anchor at. Defaults to the
    longest horizon so forward data exists for every horizon. anchor_offset=0
    anchors at the last candle (forward returns = None until future data
    arrives).
    """
    if not candles:
        return SymbolResult(
            symbol=symbol,
            anchor_date="",
            anchor_price=0.0,
            look_ahead=True,
            news_sentiment=news_sentiment,
            social_sentiment=social_sentiment,
            manipulation_score=manipulation_score,
        )

    max_h = max(horizons) if horizons else 0
    if anchor_offset is None:
        anchor_offset = max_h
    anchor_idx = len(candles) - 1 - anchor_offset
    if anchor_idx < 0:
        anchor_idx = 0

    anchor_candle = candles[anchor_idx]
    anchor_price = _to_float(anchor_candle.get("close")) or 0.0
    forward = _forward_returns(candles, anchor_idx, horizons)
    forward_prices: Dict[str, Optional[float]] = {}
    for h in horizons:
        target_idx = anchor_idx + h
        forward_prices[f"{h}d"] = (
            _to_float(candles[target_idx].get("close")) if target_idx < len(candles) else None
        )

    return SymbolResult(
        symbol=symbol,
        anchor_date=str(anchor_candle.get("timestamp_str", "")),
        anchor_price=anchor_price,
        look_ahead=anchor_idx < len(candles) - 1,
        news_sentiment=news_sentiment or {},
        social_sentiment=social_sentiment or {},
        manipulation_score=manipulation_score,
        forward_returns=forward,
        forward_prices=forward_prices,
    )


def _aggregate(
    results: List[SymbolResult],
    horizons: List[int],
) -> Dict[str, Any]:
    """Aggregate per-bucket mean forward return and win rate."""
    by_sentiment: Dict[str, Dict[str, List[float]]] = {}
    for h in horizons:
        key = f"{h}d"
        for bucket in ("negative", "neutral", "positive"):
            by_sentiment.setdefault(key, {}).setdefault(bucket, [])

    news_signal = [r.news_sentiment.get("signal", "neutral") for r in results]
    social_signal = [r.social_sentiment.get("signal", "neutral") for r in results]

    for r in results:
        for h in horizons:
            key = f"{h}d"
            ret = r.forward_returns.get(key)
            if ret is None:
                continue
            ns = r.news_sentiment.get("signal", "neutral")
            ss = r.social_sentiment.get("signal", "neutral")
            for sig, bucket_map in ((ns, by_sentiment[key]), (ss, by_sentiment[key])):
                bucket_map.setdefault(sig, []).append(ret)

    summary: Dict[str, Any] = {}
    for h in horizons:
        key = f"{h}d"
        hz: Dict[str, Any] = {}
        for bucket in ("negative", "neutral", "positive"):
            rets = by_sentiment.get(key, {}).get(bucket, [])
            if not rets:
                hz[bucket] = {"count": 0, "mean_forward_return": None, "win_rate": None}
                continue
            mean_ret = sum(rets) / len(rets)
            win_rate = sum(1 for r in rets if r > 0) / len(rets)
            hz[bucket] = {
                "count": len(rets),
                "mean_forward_return": round(mean_ret, 6),
                "win_rate": round(win_rate, 6),
            }
        summary[key] = hz

    # Manipulation-score tertiles (only when scores are present).
    scores = [r.manipulation_score for r in results if r.manipulation_score is not None]
    manip_summary: Dict[str, Any] = {}
    if scores:
        tertiles = _bucket_tertiles([r.manipulation_score for r in results])
        by_manip: Dict[str, Dict[str, List[float]]] = {}
        for h in horizons:
            key = f"{h}d"
            for bucket in ("low", "mid", "high"):
                by_manip.setdefault(key, {}).setdefault(bucket, [])
        for r, bucket in zip(results, tertiles):
            if bucket is None:
                continue
            for h in horizons:
                key = f"{h}d"
                ret = r.forward_returns.get(key)
                if ret is None:
                    continue
                by_manip.setdefault(key, {}).setdefault(bucket, []).append(ret)
        for h in horizons:
            key = f"{h}d"
            hz: Dict[str, Any] = {}
            for bucket in ("low", "mid", "high"):
                rets = by_manip.get(key, {}).get(bucket, [])
                if not rets:
                    hz[bucket] = {"count": 0, "mean_forward_return": None, "win_rate": None}
                    continue
                mean_ret = sum(rets) / len(rets)
                win_rate = sum(1 for r in rets if r > 0) / len(rets)
                hz[bucket] = {
                    "count": len(rets),
                    "mean_forward_return": round(mean_ret, 6),
                    "win_rate": round(win_rate, 6),
                }
            manip_summary[key] = hz

    return {
        "by_sentiment": summary,
        "by_manipulation_tertile": manip_summary,
        "symbol_count": len(results),
    }


def run_backtest(
    universe: List[str] = DEFAULT_UNIVERSE,
    sentiment_map: Optional[Dict[str, Dict[str, Any]]] = None,
    manipulation_map: Optional[Dict[str, float]] = None,
    ohlcv_dir: Optional[Path] = None,
    use_live: bool = False,
    horizons: List[int] = DEFAULT_HORIZONS,
    anchor_offset: Optional[int] = None,
) -> Dict[str, Any]:
    """Run the sentiment backtest over a universe of symbols.

    sentiment_map: symbol -> {"news": {...}, "social": {...}}. When a symbol
    is missing, the live news/social skills are fetched (degrading to neutral
    on failure). Pass an injected map for offline/deterministic runs.
    manipulation_map: symbol -> manipulation score for tertile bucketing.
    """
    sentiment_map = sentiment_map or {}
    manipulation_map = manipulation_map or {}
    results: List[SymbolResult] = []

    for symbol in universe:
        candles = _load_ohlcv(symbol, ohlcv_dir=ohlcv_dir, use_live=use_live)
        sm = sentiment_map.get(symbol)
        if sm is None:
            try:
                news = get_news_sentiment(symbol)
            except Exception:
                news = {"signal": "neutral", "score": 0.0, "reason": "fetch failed", "sources": 0}
            try:
                social = get_social_sentiment(symbol)
            except Exception:
                social = {"signal": "neutral", "score": 0.0, "reason": "fetch failed", "sources": 0}
        else:
            news = sm.get("news", {"signal": "neutral", "score": 0.0})
            social = sm.get("social", {"signal": "neutral", "score": 0.0})

        results.append(
            run_symbol_backtest(
                symbol=symbol,
                candles=candles,
                news_sentiment=news,
                social_sentiment=social,
                manipulation_score=manipulation_map.get(symbol),
                anchor_offset=anchor_offset,
                horizons=horizons,
            )
        )

    summary = _aggregate(results, horizons)
    summary["symbols"] = [r.to_dict() for r in results]
    summary["horizons"] = list(horizons)
    summary["look_ahead"] = True
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()

    SENTIMENT_DIR.mkdir(parents=True, exist_ok=True)
    report_id = f"sentiment_backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    report_path = SENTIMENT_DIR / f"{report_id}.json"
    with report_path.open("w") as f:
        json.dump(summary, f, indent=2)
    summary["report_path"] = str(report_path)
    return summary


def main(
    universe: Optional[List[str]] = None,
    use_live: bool = False,
    horizons: List[int] = DEFAULT_HORIZONS,
) -> Dict[str, Any]:
    """CLI entry point: backtest sentiment over the NIFTY 50 universe."""
    return run_backtest(
        universe=universe or DEFAULT_UNIVERSE,
        use_live=use_live,
        horizons=horizons,
    )


if __name__ == "__main__":
    import pprint

    pprint.pp(main(use_live=False))
