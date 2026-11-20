"""
Market Data Ingestion for THE CLAUDE COMPANY.

Connects to free public data sources to provide real-time market data
for the research fleet. All data is free-tier, no API keys required.

Data sources:
- Yahoo Finance (yfinance) - stocks, ETFs, indices, crypto
- CoinGecko - cryptocurrency prices
- NSE India - Indian stock market data
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(os.path.expanduser("~/.openclaw/market_data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

MARKET_DATA_DIR = DATA_DIR / "ohlcv"
MARKET_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Free data sources
NSE_INDICES = {
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYIT": "^CNXIT",
}

CRYPTO_SYMBOLS = ["bitcoin", "ethereum", "solana", "cardano", "polkadot"]

US_STOCKS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "SPY", "QQQ"]


def fetch_yahoo_finance(symbol: str, period: str = "1mo", interval: str = "1d") -> list[dict]:
    """Fetch OHLCV data from Yahoo Finance (free, no API key).

    Args:
        symbol: Yahoo Finance symbol (e.g., '^NSEI', 'AAPL', 'BTC-USD')
        period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
        interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)

    Returns:
        List of OHLCV dicts sorted by timestamp ascending.
    """
    import urllib.parse

    encoded_symbol = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
        f"?period1=0&period2={int(time.time())}&interval={interval}"
        f"&events=history&includeAdjustedClose=true"
    )

    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))

        chart = data.get("chart", {})
        result = chart.get("result", [])
        if not result:
            return []

        result = result[0]
        timestamps = result.get("timestamp", [])
        ohlcv = result.get("indicators", {}).get("quote", [{}])[0]

        closes = ohlcv.get("close", [])
        opens = ohlcv.get("open", [])
        highs = ohlcv.get("high", [])
        lows = ohlcv.get("low", [])
        volumes = ohlcv.get("volume", [])

        candles = []
        for i in range(len(timestamps)):
            if closes[i] is None:
                continue
            candles.append({
                "id": f"{symbol}_{timestamps[i]}",
                "timestamp": timestamps[i],
                "timestamp_str": datetime.fromtimestamp(timestamps[i], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "symbol": symbol,
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i] if volumes[i] else 0,
            })

        return candles

    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return []


def fetch_crypto_prices(symbols: list[str] = None) -> list[dict]:
    """Fetch crypto prices from CoinGecko (free, no API key).

    Args:
        symbols: List of CoinGecko coin IDs (e.g., 'bitcoin', 'ethereum')

    Returns:
        List of price dicts.
    """
    if not symbols:
        symbols = CRYPTO_SYMBOLS

    ids = ",".join(symbols)
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true"

    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))

        results = []
        for coin_id, data in data.items():
            results.append({
                "id": f"{coin_id}_{int(time.time())}",
                "timestamp": int(time.time()),
                "timestamp_str": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "symbol": coin_id.upper(),
                "price": data.get("usd", 0),
                "change_24h": data.get("usd_24h_change", 0),
                "volume_24h": data.get("usd_24h_vol", 0),
                "source": "coingecko",
            })
        return results

    except Exception as e:
        print(f"Error fetching crypto prices: {e}")
        return []


def save_ohlcv_to_file(candles: list[dict], symbol: str) -> str:
    """Save OHLCV data to file.

    Args:
        candles: List of OHLCV dicts.
        symbol: Symbol identifier.

    Returns:
        File path.
    """
    MARKET_DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_path = MARKET_DATA_DIR / f"{symbol}.json"

    existing = []
    if MARKET_DATA_DIR.joinpath(f"{symbol}.json").exists():
        try:
            existing = json.loads(MARKET_DATA_DIR.joinpath(f"{symbol}.json").read_text())
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.extend(candles)
    # Deduplicate by timestamp
    seen = set()
    unique = []
    for c in existing:
        key = c.get("timestamp")
        if key not in seen:
            seen.add(key)
            unique.append(c)

    with open(MARKET_DATA_DIR / f"{symbol}.json", "w") as f:
        json.dump(unique, f, indent=2)

    return str(MARKET_DATA_DIR / f"{symbol}.json")


def fetch_and_store(symbol: str, interval: str = "1d") -> dict:
    """Fetch and store OHLCV data for a symbol.

    Args:
        symbol: Symbol to fetch.
        interval: Data interval.

    Returns:
        Dict with fetch stats.
    """
    candles = fetch_yahoo_finance(symbol, period="1mo", interval=interval)
    if not candles:
        return {"symbol": symbol, "count": 0, "error": "No data returned"}

    file_path = save_ohlcv_to_file(candles, symbol)
    return {
        "symbol": symbol,
        "count": len(candles),
        "file_path": file_path,
        "first_timestamp": candles[0].get("timestamp_str") if candles else None,
        "last_timestamp": candles[-1].get("timestamp_str") if candles else None,
    }


def fetch_all_market_data() -> dict:
    """Fetch all market data for configured symbols.

    Returns:
        Dict with fetch results per symbol.
    """
    results = {}

    # Fetch NSE indices
    for symbol in NSE_INDICES.values():
        results[symbol] = fetch_and_store(symbol, "1d")

    # Fetch crypto prices
    crypto_data = fetch_crypto_prices(CRYPTO_SYMBOLS)
    for c in crypto_data:
        results[c["symbol"]] = {
            "symbol": c["symbol"],
            "price": c.get("price"),
            "change_24h": c.get("change_24h"),
            "source": "coingecko",
        }

    return results


if __name__ == "__main__":
    print("Fetching market data...")
    results = fetch_all_market_data()
    for symbol, result in results.items():
        print(f"{symbol}: {result}")