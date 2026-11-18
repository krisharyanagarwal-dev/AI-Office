"""
Data Access Layer for THE CLAUDE COMPANY strategy pipeline.

Reads OHLCV (Open, High, Low, Close, Volume) data from the autonomous-qwen
results directory and other market data sources. Provides a unified interface
for loading historical price data used by strategies, backtests, and validation.

All data access is read-only. No write operations to market data files.
"""

from __future__ import annotations

import json
import csv
import glob
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Directory where hypothesis queue results (including any OHLCV data) live
RESULT_DIR = Path(os.path.expanduser("~/.openclaw/autonomous-qwen/results"))
HYPOTHESIS_QUEUE_DIR = RESULT_DIR / "hypothesis_queue"
CALIBRATION_LEDGER = RESULT_DIR / "calibration_ledger.json"
PUBLIC_RECORD_DIR = RESULT_DIR / "public_record"


def _parse_timestamp(ts_str: str) -> float:
    """Parse an ISO-8601 timestamp string to a Unix timestamp."""
    try:
        return time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        try:
            return time.mktime(time.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            return time.time()


def _parse_ohlcv_row(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Parse a single OHLCV row from a CSV row dict.

    Expected columns (case-insensitive):
        timestamp, open, high, low, close, volume
    or:
        timestamp, open, high, low, close, volume, symbol
    """
    try:
        # Normalize keys to lowercase
        row_lower = {k.lower().strip(): v for k, v in row.items()}

        ts_str = row_lower.get("timestamp", row_lower.get("date", row_lower.get("time")))
        if ts_str is None:
            return None

        ts = time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ"))

        return {
            "timestamp": ts,
            "timestamp_str": ts_str,
            "open": float(row_lower["open"]),
            "high": float(row_lower["high"]),
            "low": float(row_lower["low"]),
            "close": float(row_lower["close"]),
            "volume": float(row_lower.get("volume", row_lower.get("vol", 0))),
            "symbol": row_lower.get("symbol", "UNKNOWN"),
        }
    except (ValueError, KeyError, TypeError):
        return None


def load_ohlcv_from_csv(file_path: str) -> List[Dict[str, Any]]:
    """Load OHLCV data from a single CSV file.

    Args:
        file_path: Path to the CSV file containing OHLCV data.

    Returns:
        List of OHLCV dicts sorted by timestamp ascending.
    """
    candles: List[Dict[str, Any]] = []

    with open(file_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = _parse_ohlcv_row(row)
            if parsed is not None:
                candles.append(parsed)

    candles.sort(key=lambda c: c["timestamp"])
    return candles


def load_ohlcv_from_directory(dir_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Load all OHLCV CSV files from a directory.

    Args:
        dir_path: Directory containing CSV files with OHLCV data.

    Returns:
        Dict mapping symbol -> list of OHLCV dicts sorted by timestamp.
    """
    result: Dict[str, List[Dict[str, Any]]] = {}

    for csv_file in sorted(Path(dir_path).glob("*.csv")):
        candles = load_ohlcv_from_csv(str(csv_file))
        if not candles:
            continue

        symbol = candles[0].get("symbol", Path(csv_file).stem.upper())
        result[symbol] = candles

    return result


def load_hypothesis_queue() -> List[Dict[str, Any]]:
    """Load all hypothesis queue entries.

    Returns:
        List of hypothesis dicts sorted by pre_registered_at.
    """
    hypotheses: List[Dict[str, Any]] = []

    if not HYPOTHESIS_QUEUE_DIR.exists():
        return hypotheses

    for h_file in sorted(HYPOTHESIS_QUEUE_DIR.glob("*.json")):
        try:
            hyp = json.loads(h_file.read_text())
            hypotheses.append(hyp)
        except (json.JSONDecodeError, OSError):
            continue

    hypotheses.sort(key=lambda h: h.get("pre_registered_at", ""))
    return hypotheses


def load_calibration_ledger() -> List[Dict[str, Any]]:
    """Load the calibration ledger.

    Returns:
        List of calibration record dicts.
    """
    if not CALIBRATION_LEDGER.exists():
        return []

    try:
        return json.loads(CALIBRATION_LEDGER.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def load_monthly_public_record() -> List[Dict[str, Any]]:
    """Load monthly public record files.

    Returns:
        List of monthly public record dicts sorted by month.
    """
    records: List[Dict[str, Any]] = []

    if not PUBLIC_RECORD_DIR.exists():
        return records

    for p in sorted(PUBLIC_RECORD_DIR.glob("*.json")):
        try:
            rec = json.loads(p.read_text())
            records.append(rec)
        except (json.JSONDecodeError, OSError):
            continue

    records.sort(key=lambda r: r.get("month", ""))
    return records


def generate_synthetic_ohlcv(
    symbol: str = "SYM",
    start_date: str = "2024-01-01",
    days: int = 252,
    start_price: float = 100.0,
    volatility: float = 0.02,
    drift: float = 0.0005,
    volume_base: int = 1000000,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Generate synthetic OHLCV data for testing and development.

    Generates realistic-looking OHLCV data using a geometric Brownian motion
    model with daily volatility and drift.

    Args:
        symbol: Symbol/ticker symbol for the generated data.
        start_date: Start date in YYYY-MM-DD format.
        days: Number of trading days to generate.
        start_price: Starting price.
        volatility: Daily volatility (as decimal, e.g. 0.02 = 2%).
        drift: Daily drift (as decimal, e.g. 0.0005 = 0.05% per day).
        volume_base: Base daily volume.
        seed: Random seed for reproducibility.

    Returns:
        List of OHLCV dicts sorted by timestamp ascending.
    """
    import random

    if seed is not None:
        random.seed(seed)

    candles: List[Dict[str, Any]] = []
    current_price = start_price
    current_date = datetime.strptime(start_date, "%Y-%m-%d")

    for i in range(days):
        # Skip weekends (simple approximation - no holiday calendar)
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue

        # Geometric Brownian Motion step
        shock = random.gauss(0, volatility)
        daily_return = drift + shock
        close_price = current_price * (1 + daily_return)

        # High and low based on intra-day volatility
        intra_vol = volatility * 0.5
        high_price = max(current_price, close_price) * (1 + abs(random.gauss(0, intra_vol)))
        low_price = min(current_price, close_price) * (1 - abs(random.gauss(0, intra_vol)))
        open_price = current_price

        volume = int(volume_base * (1 + random.gauss(0, 0.3)))
        volume = max(volume, 1000)

        candle = {
            "id": f"{symbol}_{current_date.strftime('%Y%m%d')}",
            "timestamp": time.mktime(current_date.timetuple()),
            "timestamp_str": current_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbol": symbol,
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": volume,
            "source": "synthetic",
        }

        candles.append(candle)
        current_price = close_price
        current_date += timedelta(days=1)

    return candles


def save_ohlcv_to_file(candles: List[Dict[str, Any]], file_path: str) -> None:
    """Save OHLCV candles to a CSV file.

    Args:
        candles: List of OHLCV dicts.
        file_path: Path to write the CSV file.
    """
    if not candles:
        return

    with open(file_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "symbol"])
        for c in candles:
            writer.writerow([
                c.get("timestamp_str", ""),
                c.get("open", ""),
                c.get("high", ""),
                c.get("low", ""),
                c.get("close", ""),
                c.get("volume", ""),
                c.get("symbol", ""),
            ])


def get_latest_price(candles: List[Dict[str, Any]]) -> Optional[float]:
    """Get the most recent close price from a list of candles.

    Args:
        candles: List of OHLCV dicts sorted by timestamp.

    Returns:
        Most recent close price, or None if no candles.
    """
    if not candles:
        return None
    return candles[-1].get("close")


def compute_returns(candles: List[Dict[str, Any]]) -> List[float]:
    """Compute simple returns from a list of candles.

    Args:
        candles: List of OHLCV dicts sorted by timestamp.

    Returns:
        List of simple returns (close_to_close / prev_close - 1).
        First element is 0.0 (no previous close).
    """
    if len(candles) < 2:
        return [0.0]

    returns = [0.0]
    for i in range(1, len(candles)):
        prev_close = candles[i - 1].get("close", 0)
        curr_close = candles[i].get("close", 0)
        if prev_close > 0:
            returns.append(curr_close / prev_close - 1)
        else:
            returns.append(0.0)

    return returns


def compute_log_returns(candles: List[Dict[str, Any]]) -> List[float]:
    """Compute log returns from a list of candles.

    Args:
        candles: List of OHLCV dicts sorted by timestamp.

    Returns:
        List of log returns (ln(close_to_close / prev_close)).
        First element is 0.0.
    """
    import math

    if len(candles) < 2:
        return [0.0]

    returns = [0.0]
    for i in range(1, len(candles)):
        prev_close = candles[i - 1].get("close", 0)
        curr_close = candles[i].get("close", 0)
        if prev_close > 0 and curr_close > 0:
            returns.append(__import__("math").log(curr_close / prev_close))
        else:
            returns.append(0.0)

    return returns