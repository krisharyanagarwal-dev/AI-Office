"""
Shared reader for stock fundamental metrics produced by all_stocks_bot.

all_stocks_bot.py POSTs a compact summary to the Office OS dashboard
(http://127.0.0.1:8083/api/stocks), which persists it to
~/.openclaw/stocks_metrics.json. This module reads that file so any trading
bot can surface fundamental context (valuation, leverage, liquidity,
profitability, ROE, momentum flags) for the symbols it trades.

Read-only, fails silently: never blocks the trading loop, never issues
directional calls — the flags are factual context only, not buy/sell signals.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

STOCKS_METRICS_FILE = Path(
    os.environ.get("STOCKS_METRICS_FILE", "/Users/aryanagarwal/.openclaw/stocks_metrics.json")
)


def load_stock_metrics() -> dict:
    """Return the last stock run metrics dict, or {} if unavailable."""
    try:
        if not STOCKS_METRICS_FILE.exists():
            return {}
        return json.loads(STOCKS_METRICS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def symbol_fundamentals(metrics: dict, symbol: str) -> Optional[dict]:
    """Return the fundamental facts for a symbol, or None.

    The producer publishes an alias-expanded map (fundamentals_by_symbol) so
    a bot's own spelling — BTCUSDT, RELIANCE, BRK.B — resolves with one
    lookup. Older payloads without that map fall back to the legacy
    top_by_market_cap list.
    """
    if not metrics or not symbol:
        return None

    alias_map = metrics.get("fundamentals_by_symbol") or {}
    if alias_map:
        entry = alias_map.get(symbol)
        if entry is None:
            entry = alias_map.get(symbol.strip().upper())
        if entry is not None:
            return entry

    top = metrics.get("top_by_market_cap") or []
    for entry in top:
        if entry.get("symbol") == symbol:
            return entry
    return None


def fundamentals_for(symbol: str, metrics: Optional[dict] = None) -> Optional[dict]:
    """Convenience wrapper: load the metrics file and look up one symbol."""
    if metrics is None:
        metrics = load_stock_metrics()
    return symbol_fundamentals(metrics, symbol)
