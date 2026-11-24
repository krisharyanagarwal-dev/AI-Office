"""Tests for the fundamentals producer/reader pipeline.

The producer (scripts/all_stocks_bot.py) publishes a per-symbol facts payload
and an alias-expanded lookup map. The reader (alpha/data/stock_metrics.py)
resolves a bot's own symbol spelling against that map.

Facts only — no directional calls.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_producer():
    path = REPO_ROOT / "scripts" / "all_stocks_bot.py"
    spec = importlib.util.spec_from_file_location("all_stocks_bot_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


producer = _load_producer()


class FakeTicker:
    def __init__(self, fast_info=None, info=None, closes=None):
        self._fast_info = fast_info or {}
        self._info = info or {}
        self._closes = closes or []

    @property
    def fast_info(self):
        return self._fast_info

    @property
    def info(self):
        return self._info

    def history(self, period=None, **kwargs):
        return pd.DataFrame({"Close": self._closes})


def _crypto_ticker():
    return FakeTicker(
        fast_info={"lastPrice": 58994.1, "lastVolume": 60832735232},
        info={
            "quoteType": "CRYPTOCURRENCY",
            "longName": "Bitcoin USD",
            "regularMarketPrice": 58994.1,
            "marketCap": 1188195860480,
            "volume": 60832735232,
            "fiftyTwoWeekHigh": 97860.6,
            "fiftyTwoWeekLow": 57747.766,
        },
        closes=[58000.0, 57000.0, 60000.0, 59000.0, 58994.1],
    )


def _equity_ticker():
    return FakeTicker(
        fast_info={"lastPrice": 100.0},
        info={
            "quoteType": "EQUITY",
            "longName": "Example Corp",
            "regularMarketPrice": 100.0,
            "marketCap": 5_000_000_000,
            "trailingPE": 12.0,
            "priceToBook": 2.0,
            "returnOnEquity": 0.25,
            "profitMargins": 0.20,
            "debtToEquity": 20.0,
            "currentRatio": 2.5,
            "totalVolume": 10_000_000,
            "fiftyTwoWeekHigh": 120.0,
            "fiftyTwoWeekLow": 80.0,
        },
    )


def test_crypto_universe_is_published():
    universe = producer.DEFAULT_CRYPTO_UNIVERSE
    assert "BTC-USD" in universe
    assert "ETH-USD" in universe


def test_load_universe_supports_crypto_market():
    symbols = producer.load_universe(None, None, "crypto")
    assert symbols == producer.DEFAULT_CRYPTO_UNIVERSE


def test_equity_runs_also_publish_crypto_majors(monkeypatch):
    """Crypto bots need facts whichever equity market the run covered."""
    monkeypatch.setattr(producer, "discover_nse_symbols", lambda: ["RELIANCE.NS"])
    universe = producer.load_universe(None, None, "nse")
    assert "BTC-USD" not in universe

    combined = producer.universe_with_crypto(universe)
    assert "RELIANCE.NS" in combined
    assert "BTC-USD" in combined
    assert "ETH-USD" in combined


def test_universe_with_crypto_does_not_duplicate():
    combined = producer.universe_with_crypto(["BTC-USD", "AAPL"])
    assert combined.count("BTC-USD") == 1
    assert "AAPL" in combined


def test_crypto_equity_only_flags_are_not_applicable(monkeypatch):
    monkeypatch.setattr(producer.yf, "Ticker", lambda symbol: _crypto_ticker())
    result = producer.analyze_symbol("BTC-USD")

    assert result["asset_class"] == "crypto"
    assert result["valuation_flag"] == "N/A"
    assert result["leverage_flag"] == "N/A"
    assert result["profitability_flag"] == "N/A"
    assert result["roe_flag"] == "N/A"
    assert result["volatility_30d_pct"] is not None
    assert result["turnover_ratio"] == pytest.approx(
        60832735232 / 1188195860480, rel=1e-6
    )


def test_crypto_liquidity_flag_comes_from_turnover(monkeypatch):
    monkeypatch.setattr(producer.yf, "Ticker", lambda symbol: _crypto_ticker())
    result = producer.analyze_symbol("BTC-USD")
    assert result["liquidity_flag"] in ("Tight", "Adequate", "Comfortable")


def test_crypto_momentum_flag_uses_52_week_range(monkeypatch):
    monkeypatch.setattr(producer.yf, "Ticker", lambda symbol: _crypto_ticker())
    result = producer.analyze_symbol("BTC-USD")
    assert result["momentum_flag"] == "Deep below 52W high"


def test_equity_analysis_keeps_its_existing_flags(monkeypatch):
    monkeypatch.setattr(producer.yf, "Ticker", lambda symbol: _equity_ticker())
    result = producer.analyze_symbol("EXAMPLE")

    assert result["asset_class"] == "equity"
    assert result["valuation_flag"] == "Cheap"
    assert result["roe_flag"] == "High"
    assert result["volatility_30d_pct"] is None
    # Provider debtToEquity is a percentage (20.0 = 20%), normalized to a ratio.
    assert result["debt_to_equity"] == 0.2
    assert result["debt_to_equity_unit"] == "ratio"
    assert result["leverage_flag"] == "Low"


def _ratio_fallback_ticker():
    """Yahoo omits debtToEquity; balance-sheet totals must be used instead."""
    return FakeTicker(
        fast_info={"lastPrice": 100.0},
        info={
            "quoteType": "EQUITY",
            "longName": "Example Corp",
            "regularMarketPrice": 100.0,
            "marketCap": 5_000_000_000,
            "totalDebt": 800_000_000,
            "totalStockholderEquity": 1_000_000_000,
        },
        closes=[100.0, 99.0, 101.0],
    )


def test_equity_debt_to_equity_falls_back_to_balance_sheet_ratio(monkeypatch):
    """Computed totalDebt/totalEquity is already a ratio and is kept as-is."""
    monkeypatch.setattr(producer.yf, "Ticker", lambda symbol: _ratio_fallback_ticker())
    result = producer.analyze_symbol("EXAMPLE")

    assert result["debt_to_equity"] == pytest.approx(0.8)
    assert result["debt_to_equity_unit"] == "ratio"
    assert result["leverage_flag"] == "Moderate"


def test_equity_debt_to_equity_provider_percent_normalizes_to_ratio(monkeypatch):
    """Provider percentage (e.g. 150 = 150%) divides by 100 into a ratio."""
    ticker = _ratio_fallback_ticker()
    ticker._info["debtToEquity"] = 150.0
    monkeypatch.setattr(producer.yf, "Ticker", lambda symbol: ticker)
    result = producer.analyze_symbol("EXAMPLE")

    assert result["debt_to_equity"] == 1.5
    assert result["debt_to_equity_unit"] == "ratio"
    assert result["leverage_flag"] == "High"


def test_alias_map_covers_every_symbol_spelling_used_by_bots():
    entries = [
        {
            "symbol": "BTC-USD",
            "name": "Bitcoin USD",
            "asset_class": "crypto",
            "market_cap": 100,
            "price": 10.0,
            "valuation_flag": "N/A",
            "leverage_flag": "N/A",
            "liquidity_flag": "Adequate",
            "profitability_flag": "N/A",
            "roe_flag": "N/A",
            "momentum_flag": "Mid range",
            "volatility_30d_pct": 3.0,
            "turnover_ratio": 0.05,
        },
        {
            "symbol": "RELIANCE.NS",
            "name": "Reliance",
            "asset_class": "equity",
            "market_cap": 200,
            "price": 20.0,
            "valuation_flag": "Fair",
            "leverage_flag": "Moderate",
            "liquidity_flag": "Adequate",
            "profitability_flag": "Strong",
            "roe_flag": "High",
            "momentum_flag": "Mid range",
            "volatility_30d_pct": None,
            "turnover_ratio": None,
        },
        {
            "symbol": "BRK-B",
            "name": "Berkshire",
            "asset_class": "equity",
            "market_cap": 300,
            "price": 30.0,
            "valuation_flag": "Fair",
            "leverage_flag": "Low",
            "liquidity_flag": "Comfortable",
            "profitability_flag": "Strong",
            "roe_flag": "High",
            "momentum_flag": "Mid range",
            "volatility_30d_pct": None,
            "turnover_ratio": None,
        },
    ]
    aliases = producer.build_alias_map(entries)

    for spelling in ("BTC-USD", "BTC/USD", "BTCUSDT", "BTC", "RELIANCE.NS",
                     "RELIANCE", "BRK-B", "BRK.B"):
        assert spelling in aliases, spelling

    assert aliases["BTCUSDT"]["symbol"] == "BTC-USD"
    assert aliases["RELIANCE"]["symbol"] == "RELIANCE.NS"
    assert aliases["BRK.B"]["symbol"] == "BRK-B"


def test_push_metrics_publishes_lookup_map_and_separate_slices(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        return FakeResponse()

    monkeypatch.setattr(producer.requests, "post", fake_post)

    results = [
        {
            "symbol": "BTC-USD",
            "name": "Bitcoin USD",
            "asset_class": "crypto",
            "market_cap": 1_188_195_860_480,
            "price": 58994.1,
            "valuation_flag": "N/A",
            "leverage_flag": "N/A",
            "liquidity_flag": "Adequate",
            "profitability_flag": "N/A",
            "roe_flag": "N/A",
            "momentum_flag": "Mid range",
            "volatility_30d_pct": 3.0,
            "turnover_ratio": 0.05,
        },
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "asset_class": "equity",
            "market_cap": 3_000_000_000_000,
            "price": 200.0,
            "valuation_flag": "Fair",
            "leverage_flag": "Moderate",
            "liquidity_flag": "Comfortable",
            "profitability_flag": "Strong",
            "roe_flag": "High",
            "momentum_flag": "Mid range",
            "volatility_30d_pct": None,
            "turnover_ratio": None,
        },
    ]
    producer.push_metrics(results, "both")

    assert "fundamentals_by_symbol" in captured
    assert captured["fundamentals_by_symbol"]["BTCUSDT"]["symbol"] == "BTC-USD"
    assert captured["fundamentals_by_symbol"]["AAPL"]["symbol"] == "AAPL"
    assert [e["symbol"] for e in captured["top_by_market_cap"]] == ["AAPL"]
    assert [e["symbol"] for e in captured["top_crypto_by_market_cap"]] == ["BTC-USD"]
