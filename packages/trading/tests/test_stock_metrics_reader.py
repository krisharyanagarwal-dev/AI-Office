"""Tests for the shared fundamentals reader (alpha/data/stock_metrics.py)."""
import json
import sys
from pathlib import Path

import pytest

TRADING_ROOT = Path(__file__).resolve().parents[1]
if str(TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(TRADING_ROOT))

from alpha.data import stock_metrics  # noqa: E402


@pytest.fixture
def metrics_file(tmp_path, monkeypatch):
    path = tmp_path / "stocks_metrics.json"
    monkeypatch.setattr(stock_metrics, "STOCKS_METRICS_FILE", path)
    return path


def test_load_returns_empty_when_file_missing(metrics_file):
    assert stock_metrics.load_stock_metrics() == {}


def test_load_returns_empty_on_invalid_json(metrics_file):
    metrics_file.write_text("{not json", encoding="utf-8")
    assert stock_metrics.load_stock_metrics() == {}


def test_lookup_uses_the_producer_alias_map(metrics_file):
    metrics_file.write_text(json.dumps({
        "fundamentals_by_symbol": {
            "BTCUSDT": {"symbol": "BTC-USD", "valuation_flag": "N/A"},
            "RELIANCE": {"symbol": "RELIANCE.NS", "valuation_flag": "Fair"},
        },
    }), encoding="utf-8")

    metrics = stock_metrics.load_stock_metrics()
    assert stock_metrics.symbol_fundamentals(metrics, "BTCUSDT")["symbol"] == "BTC-USD"
    assert stock_metrics.symbol_fundamentals(metrics, "RELIANCE")["symbol"] == "RELIANCE.NS"


def test_lookup_returns_none_for_unknown_symbol(metrics_file):
    metrics_file.write_text(json.dumps({
        "fundamentals_by_symbol": {"AAPL": {"symbol": "AAPL"}},
    }), encoding="utf-8")

    metrics = stock_metrics.load_stock_metrics()
    assert stock_metrics.symbol_fundamentals(metrics, "TSLA") is None


def test_lookup_falls_back_to_legacy_top_by_market_cap(metrics_file):
    metrics_file.write_text(json.dumps({
        "top_by_market_cap": [{"symbol": "AAPL", "valuation_flag": "Fair"}],
    }), encoding="utf-8")

    metrics = stock_metrics.load_stock_metrics()
    assert stock_metrics.symbol_fundamentals(metrics, "AAPL")["valuation_flag"] == "Fair"


def test_lookup_is_case_insensitive_for_the_alias_map(metrics_file):
    metrics_file.write_text(json.dumps({
        "fundamentals_by_symbol": {"BTCUSDT": {"symbol": "BTC-USD"}},
    }), encoding="utf-8")

    metrics = stock_metrics.load_stock_metrics()
    assert stock_metrics.symbol_fundamentals(metrics, "btcusdt")["symbol"] == "BTC-USD"
