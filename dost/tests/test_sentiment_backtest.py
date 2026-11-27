"""Tests for the sentiment backtest module.

Fully offline: OHLCV candles are injected, sentiment is injected through
`sentiment_map` (so the live news/social skills are never called), and the
report directory is redirected to a temp path. No network, no live orders.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from trading.sentiment_backtest import (
    DEFAULT_HORIZONS,
    DEFAULT_UNIVERSE,
    SymbolResult,
    _aggregate,
    _bucket_tertiles,
    _forward_returns,
    _load_ohlcv,
    _to_float,
    run_backtest,
    run_symbol_backtest,
)


def _candles(n: int = 30, start_close: float = 100.0) -> List[Dict[str, Any]]:
    return [
        {
            "timestamp_str": f"2024-01-{1 + i:02d}T09:15:00Z",
            "close": round(start_close + i, 2),
        }
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _redirect_report_dir(tmp_path, monkeypatch):
    """Keep JSON report writes out of ~/.openclaw during tests."""
    monkeypatch.setattr(
        "trading.sentiment_backtest.SENTIMENT_DIR",
        tmp_path / "backtests" / "sentiment",
    )


@pytest.fixture
def offline(monkeypatch):
    """Inject candles and block live OHLCV loads / live skill fetches."""
    monkeypatch.setattr(
        "trading.sentiment_backtest._load_ohlcv", lambda symbol, **kwargs: _candles()
    )
    calls = SimpleNamespace(news=0, social=0)

    def boom_news(*args, **kwargs):
        calls.news += 1
        raise RuntimeError("live news fetch must not happen in tests")

    def boom_social(*args, **kwargs):
        calls.social += 1
        raise RuntimeError("live social fetch must not happen in tests")

    monkeypatch.setattr("trading.sentiment_backtest.get_news_sentiment", boom_news)
    monkeypatch.setattr("trading.sentiment_backtest.get_social_sentiment", boom_social)
    return calls


def _sentiment_map(universe: List[str], signal: str) -> Dict[str, Dict[str, Any]]:
    return {
        symbol: {"news": {"signal": signal}, "social": {"signal": signal}}
        for symbol in universe
    }


# ----------------------- helpers -----------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        (1.5, 1.5),
        ("2.25", 2.25),
        (0, 0.0),
        (None, None),
        ("", None),
        ("abc", None),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
    ],
)
def test_to_float(value, expected):
    result = _to_float(value)
    if expected is None:
        assert result is None
    else:
        assert result == expected


# ----------------------- forward returns -----------------------

def test_forward_returns_known_values():
    candles = _candles(10, 100.0)  # closes 100 .. 109
    out = _forward_returns(candles, anchor_idx=0, horizons=[1, 2, 3])
    assert out["1d"] == pytest.approx(101.0 / 100.0 - 1)
    assert out["2d"] == pytest.approx(102.0 / 100.0 - 1)
    assert out["3d"] == pytest.approx(103.0 / 100.0 - 1)


def test_forward_returns_out_of_range_is_none():
    candles = _candles(10, 100.0)
    out = _forward_returns(candles, anchor_idx=8, horizons=[1, 2, 30])
    assert out["1d"] == pytest.approx(109.0 / 108.0 - 1)
    assert out["2d"] is None
    assert out["30d"] is None


# ----------------------- per-symbol backtest -----------------------

def test_run_symbol_backtest_default_anchor(offline):
    candles = _candles(30)
    res = run_symbol_backtest(
        "AAAA.NS", candles, {"signal": "negative"}, {"signal": "neutral"}
    )
    # 30 candles, default anchor_offset = max horizon = 20 -> anchor idx 9
    assert res.anchor_date == "2024-01-10T09:15:00Z"
    assert res.anchor_price == pytest.approx(109.0)
    assert res.look_ahead is True
    assert res.forward_returns["1d"] == pytest.approx(110.0 / 109.0 - 1)
    assert res.forward_returns["20d"] == pytest.approx(129.0 / 109.0 - 1)
    assert res.forward_prices["20d"] == 129.0


def test_run_symbol_backtest_offset_zero_all_none(offline):
    candles = _candles(30)
    res = run_symbol_backtest(
        "AAAA.NS",
        candles,
        {"signal": "positive"},
        {"signal": "positive"},
        anchor_offset=0,
    )
    assert res.anchor_price == pytest.approx(129.0)
    assert res.look_ahead is False
    assert all(v is None for v in res.forward_returns.values())
    assert all(v is None for v in res.forward_prices.values())


def test_run_symbol_backtest_empty_candles(offline):
    res = run_symbol_backtest(
        "NOPE.NS", [], {"signal": "neutral"}, {"signal": "neutral"}
    )
    assert res.anchor_date == ""
    assert res.anchor_price == 0.0
    assert res.look_ahead is True
    assert res.forward_returns == {}
    assert res.forward_prices == {}


# ----------------------- aggregation -----------------------

def test_aggregation_by_sentiment_buckets(offline):
    universe = ["AAAA.NS", "BBBB.NS", "CCCC.NS", "DDDD.NS", "EEEE.NS"]
    signals = ["negative", "negative", "neutral", "neutral", "positive"]
    sentiment_map = {
        symbol: {"news": {"signal": sig}, "social": {"signal": sig}}
        for symbol, sig in zip(universe, signals)
    }
    summary = run_backtest(universe=universe, sentiment_map=sentiment_map)

    # No live skill calls when sentiment_map covers the universe.
    assert offline.news == 0 and offline.social == 0
    assert summary["symbol_count"] == 5
    assert summary["look_ahead"] is True
    assert summary["horizons"] == list(DEFAULT_HORIZONS)
    assert summary["by_manipulation_tertile"] == {}

    # Each symbol contributes its signal once from news and once from social.
    for h in DEFAULT_HORIZONS:
        key = f"{h}d"
        buckets = summary["by_sentiment"][key]
        assert buckets["negative"]["count"] == 4
        assert buckets["neutral"]["count"] == 4
        assert buckets["positive"]["count"] == 2
        assert buckets["negative"]["win_rate"] == 1.0
        assert buckets["neutral"]["win_rate"] == 1.0
        assert buckets["positive"]["win_rate"] == 1.0
        # Identical candles -> identical returns in every bucket.
        assert buckets["negative"]["mean_forward_return"] == buckets["neutral"]["mean_forward_return"]
        assert buckets["neutral"]["mean_forward_return"] == buckets["positive"]["mean_forward_return"]
        assert buckets["negative"]["mean_forward_return"] > 0


def test_aggregation_manipulation_tertile_buckets(offline):
    universe = [f"SYM{i:02d}.NS" for i in range(9)]
    sentiment_map = _sentiment_map(universe, "neutral")
    manipulation_map = {symbol: float(i) * 0.1 for i, symbol in enumerate(universe)}
    summary = run_backtest(
        universe=universe,
        sentiment_map=sentiment_map,
        manipulation_map=manipulation_map,
    )

    manip = summary["by_manipulation_tertile"]
    assert set(manip) == {f"{h}d" for h in DEFAULT_HORIZONS}
    for h in DEFAULT_HORIZONS:
        key = f"{h}d"
        counts = [manip[key][bucket]["count"] for bucket in ("low", "mid", "high")]
        assert sum(counts) == 9
        assert all(count >= 1 for count in counts)
        means = [manip[key][bucket]["mean_forward_return"] for bucket in ("low", "mid", "high")]
        assert means[0] == means[1] == means[2]


def test_aggregate_empty_results():
    assert _aggregate([], [1, 5])["symbol_count"] == 0
    assert _aggregate([], [1, 5])["by_manipulation_tertile"] == {}
    for h in ("1d", "5d"):
        for bucket in ("negative", "neutral", "positive"):
            assert _aggregate([], [1, 5])["by_sentiment"][h][bucket] == {
                "count": 0,
                "mean_forward_return": None,
                "win_rate": None,
            }


# ----------------------- bucketing -----------------------

def test_bucket_tertiles_splits_into_three_groups():
    scores = [float(i) * 0.1 for i in range(9)]  # 0.0 .. 0.8
    assert _bucket_tertiles(scores).count("low") == 4
    assert _bucket_tertiles(scores).count("mid") == 2
    assert _bucket_tertiles(scores).count("high") == 3


def test_bucket_tertiles_fewer_than_three_all_none():
    assert _bucket_tertiles([0.5]) == [None]
    assert _bucket_tertiles([0.1, 0.9]) == [None, None]


def test_bucket_tertiles_none_stays_none():
    # Only 2 valid scores -> all None.
    assert _bucket_tertiles([0.0, None, 1.0]) == [None, None, None]
    # 3 valid scores -> None slot preserved between buckets (lo_cut = mid value).
    assert _bucket_tertiles([0.0, None, 0.4, 0.6]) == ["low", None, "low", "high"]


# ----------------------- report + entry points -----------------------

def test_run_backtest_writes_report_json(offline):
    universe = ["AAAA.NS", "BBBB.NS"]
    sentiment_map = _sentiment_map(universe, "negative")
    summary = run_backtest(universe=universe, sentiment_map=sentiment_map)

    report_path = summary["report_path"]
    assert report_path and Path(report_path).exists()
    parsed = json.loads(Path(report_path).read_text())
    assert parsed["look_ahead"] is True
    assert parsed["symbol_count"] == 2
    assert parsed["horizons"] == list(DEFAULT_HORIZONS)
    assert "generated_at" in parsed


def test_run_backtest_custom_horizons(offline):
    summary = run_backtest(
        universe=["AAAA.NS"],
        sentiment_map=_sentiment_map(["AAAA.NS"], "neutral"),
        horizons=[1, 2],
    )
    assert summary["horizons"] == [1, 2]
    assert set(summary["by_sentiment"]) == {"1d", "2d"}


def test_symbol_result_to_dict_keys():
    res = SymbolResult(
        symbol="X.NS",
        anchor_date="2024-01-01",
        anchor_price=100.0,
        look_ahead=False,
        news_sentiment={"signal": "neutral"},
        social_sentiment={"signal": "neutral"},
    )
    d = res.to_dict()
    assert set(d) == {
        "symbol",
        "anchor_date",
        "anchor_price",
        "look_ahead",
        "news_sentiment",
        "social_sentiment",
        "manipulation_score",
        "forward_returns",
        "forward_prices",
    }


def test_main_delegates_with_defaults(monkeypatch, offline):
    from trading.sentiment_backtest import main

    captured: Dict[str, Any] = {}

    def fake_run_backtest(universe=None, use_live=False, horizons=None, **kwargs):
        captured["universe"] = universe
        captured["use_live"] = use_live
        captured["horizons"] = horizons
        return {}

    monkeypatch.setattr("trading.sentiment_backtest.run_backtest", fake_run_backtest)
    main()
    assert captured["universe"] == DEFAULT_UNIVERSE
    assert captured["use_live"] is False
    assert captured["horizons"] == DEFAULT_HORIZONS
