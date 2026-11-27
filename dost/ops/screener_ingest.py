"""EV / new-age screener ingestion pipeline.

Read-only and keyless: queries the TradingView scanner API for technicals and
yfinance for EV/new-age fundamentals. A symbol is emitted only when BOTH
sources succeed with all required fields — no partial rows, no single-source
fallbacks, no credentials read or stored.

Writes `screener_ev_<timestamp>.csv` to the repo root so screener-manip-watch
can discover it via its artifact globbing.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[2]  # AI-Office/

TRADINGVIEW_SCAN_URL = "https://scanner.tradingview.com/canonical/scan"

# Columns requested from the TradingView scanner (keyless, no auth).
TV_COLUMNS = ["name", "close", "change", "pe_ttm_fwd", "high_52w", "low_52w"]

# Sectors treated as EV / new-age adjacent for the internal scoring below.
EV_NEW_AGE_SECTORS = {"Technology", "Consumer Cyclical", "Automotive", "Industrials", "Energy"}

EV_NEW_AGE_THRESHOLD = 70

CSV_FIELDNAMES = [
    "symbol",
    "sector",
    "market_cap",
    "revenue_growth",
    "ev_ebitda",
    "pe_ttm",
    "debt_to_equity",
    "current_ratio",
    "momentum_flag",
    "leverage_flag",
    "pct_from_52w_high",
    "ev_new_age_score",
]

# Fields that must be present and valid for each source, else the symbol is
# skipped entirely (both-sources-required invariant).
TV_REQUIRED = ("symbol", "close", "change", "pe_ttm", "pct_from_52w_high", "momentum_flag")
YF_REQUIRED = (
    "sector",
    "market_cap",
    "revenue_growth",
    "ev_ebitda",
    "debt_to_equity",
    "current_ratio",
)


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _tv_payload(symbol: str) -> dict[str, Any]:
    return _tv_payload_batch([symbol])


def _tv_payload_batch(symbols: list[str]) -> dict[str, Any]:
    return {
        "columns": list(TV_COLUMNS),
        "filter": [{"left": "name", "right": symbols, "operation": "in"}],
        "options": {"lang": "en"},
        "range": [0, len(symbols)],
    }


def _fetch_json(url: str, data: bytes | None = None, timeout: float = 10.0) -> Any:
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, headers=headers)
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _tv_numbers(row: dict[str, Any]) -> dict[str, Any]:
    close = _to_float(row.get("close"))
    change = _to_float(row.get("change"))
    pe_ttm = _to_float(row.get("pe_ttm_fwd"))
    high_52w = _to_float(row.get("high_52w"))

    pct_from_52w_high: float | None = None
    if close is not None and high_52w not in (None, 0):
        pct_from_52w_high = (close - high_52w) / high_52w * 100.0

    if change is None:
        momentum_flag = "Normal"
    elif change >= 5:
        momentum_flag = "Parabolic"
    elif change >= 2:
        momentum_flag = "Elevated"
    else:
        momentum_flag = "Normal"

    return {
        "close": close,
        "change": change,
        "pe_ttm": pe_ttm,
        "pct_from_52w_high": pct_from_52w_high,
        "momentum_flag": momentum_flag,
    }


def _parse_tv_response_all(body: Any) -> list[dict[str, Any]] | None:
    """Parse all rows from a TradingView scanner response (single or batch)."""
    if not isinstance(body, dict):
        return None
    columns = list(body.get("columns") or TV_COLUMNS)
    rows: list[dict[str, Any]] = []
    for item in body.get("data") or []:
        if isinstance(item, dict) and isinstance(item.get("d"), (list, tuple)):
            row = dict(zip(columns, item["d"]))
        elif isinstance(item, dict):
            row = item
        else:
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        numbers = _tv_numbers(row)
        rows.append({"symbol": name, **numbers})
    return rows or None


def _parse_tv_response(body: Any) -> dict[str, Any] | None:
    """Parse the first row from a TradingView scanner response (backward compat)."""
    rows = _parse_tv_response_all(body)
    return rows[0] if rows else None


def fetch_tradingview(symbols: list[str], timeout: float = 10.0) -> dict[str, dict[str, Any]]:
    """Per-symbol TradingView scanner queries.

    Returns a dict of symbol -> technicals. Symbols that fail (network,
    empty response, missing fields) are simply omitted — callers skip them.
    """
    results: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        try:
            payload = json.dumps(_tv_payload(symbol)).encode("utf-8")
            body = _fetch_json(TRADINGVIEW_SCAN_URL, data=payload, timeout=timeout)
        except (urlerror.URLError, urlerror.HTTPError, OSError, ValueError):
            continue
        row = _parse_tv_response(body)
        if row:
            results[symbol] = row
    return results


def fetch_tradingview_batch(symbols: list[str], timeout: float = 10.0) -> dict[str, dict[str, Any]]:
    """Batch TradingView scanner query for multiple symbols in one HTTP request.

    Uses the scanner's ``in`` operator so N symbols cost one request instead of N.
    Returns a dict of symbol -> technicals. Symbols that fail or are absent
    from the response are simply omitted — callers skip them.
    """
    if not symbols:
        return {}
    try:
        payload = json.dumps(_tv_payload_batch(symbols)).encode("utf-8")
        body = _fetch_json(TRADINGVIEW_SCAN_URL, data=payload, timeout=timeout)
    except (urlerror.URLError, urlerror.HTTPError, OSError, ValueError):
        return {}
    rows = _parse_tv_response_all(body) or []
    results: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = row.get("symbol")
        if symbol:
            results[symbol] = row
    return results


def fetch_yfinance(symbol: str) -> dict[str, Any] | None:
    """Keyless yfinance fundamentals for one symbol.

    Returns None on any failure (network, missing fields, invalid data).
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        fast = ticker.fast_info or {}
    except Exception:
        return None

    sector = str(info.get("sector") or "").strip() or None
    values: dict[str, Any] = {
        "sector": sector,
        "market_cap": _to_float(info.get("marketCap") or fast.get("market_cap")),
        "revenue_growth": _to_float(info.get("revenueGrowth")),
        "ev_ebitda": _to_float(info.get("enterpriseToEbitda")),
        "debt_to_equity": _to_float(info.get("debtToEquity")),
        "current_ratio": _to_float(info.get("currentRatio")),
    }
    if any(value is None for value in values.values()):
        return None
    return values


def _ev_new_age_score(yf_data: dict[str, Any]) -> float:
    """Internal EV/new-age score (0-100) from yfinance fundamentals."""
    score = 0.0
    growth = yf_data["revenue_growth"]
    if growth >= 0.25:
        score += 35
    elif growth >= 0.15:
        score += 25
    elif growth >= 0.10:
        score += 15
    elif growth >= 0.05:
        score += 8

    if yf_data["ev_ebitda"] is not None and yf_data["ev_ebitda"] > 0:
        score += 20

    if yf_data["sector"] in EV_NEW_AGE_SECTORS:
        score += 25

    if yf_data["market_cap"] > 0:
        score += 10

    if yf_data["debt_to_equity"] < 100:
        score += 10

    return min(score, 100.0)


def normalize(
    symbol: str,
    tv_data: dict[str, Any] | None,
    yf_data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge TradingView technicals and yfinance fundamentals into one row.

    Returns None if either source is missing or lacks required fields — both
    sources are required, no partial rows.
    """
    if not tv_data or not yf_data:
        return None

    for field in TV_REQUIRED:
        if tv_data.get(field) is None:
            return None
    if _to_float(tv_data["pe_ttm"]) is None or _to_float(tv_data["pct_from_52w_high"]) is None:
        return None

    for field in YF_REQUIRED:
        if yf_data.get(field) is None:
            return None

    debt_to_equity = float(yf_data["debt_to_equity"])
    if debt_to_equity > 100:
        leverage_flag = "Extreme"
    elif debt_to_equity > 50:
        leverage_flag = "High"
    else:
        leverage_flag = "Low"

    return {
        "symbol": str(tv_data["symbol"]).strip().upper(),
        "sector": yf_data["sector"],
        "market_cap": yf_data["market_cap"],
        "revenue_growth": yf_data["revenue_growth"],
        "ev_ebitda": yf_data["ev_ebitda"],
        "pe_ttm": tv_data["pe_ttm"],
        "debt_to_equity": yf_data["debt_to_equity"],
        "current_ratio": yf_data["current_ratio"],
        "momentum_flag": tv_data["momentum_flag"],
        "leverage_flag": leverage_flag,
        "pct_from_52w_high": tv_data["pct_from_52w_high"],
        "ev_new_age_score": _ev_new_age_score(yf_data),
    }


def write_artifact(
    rows: list[dict[str, Any]],
    artifact_dir: Path | None = None,
) -> Path:
    """Write rows to `screener_ev_<timestamp>.csv` with the full header."""
    directory = artifact_dir or REPO_ROOT
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = directory / f"screener_ev_{timestamp}.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDNAMES})
    return path


def ingest(symbols: list[str], artifact_dir: Path | None = None) -> Path:
    """Fetch both sources per symbol, normalize, and write the EV artifact.

    Symbols failing either source are skipped. If zero symbols pass, an empty
    artifact with headers only is still written (pipeline health can detect
    the empty universe).
    """
    tv = fetch_tradingview_batch(list(symbols))
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        row = normalize(symbol, tv.get(symbol), fetch_yfinance(symbol))
        if row is not None:
            rows.append(row)
    return write_artifact(rows, artifact_dir=artifact_dir)
