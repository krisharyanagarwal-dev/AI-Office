"""
Data - NSE bhavcopy (end-of-day) reader for 2020-2024 backtests.

Reads free NSE end-of-day bhavcopy archives (nsearchives_bhavcopy_EOD).
Read-only: no network, no writes, no secrets. Returns parsed OHLCV records
or an empty list when files are missing/stale — never raises.

Used for longer backtests (2020-2024) beyond the 2024-10 to 2026-11 window
already covered by hypothesis_queue data.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# Default location for NSE bhavcopy archives (free tier, end-of-day).
# Users populate this directory with downloaded bhavcopy files.
BHAVCOPY_ROOT = Path.home() / "Documents" / "indian-paper-trading" / "data" / "bhavcopy"


def _parse_date(s: str) -> Optional[date]:
    """Parse YYYY-MM-DD or DD-MMM-YYYY (NSE bhavcopy format)."""
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(v: str) -> Optional[float]:
    try:
        return float(v.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _to_int(v: str) -> Optional[int]:
    f = _to_float(v)
    return int(f) if f is not None else None


def discover_files(symbol: str, start: date, end: date) -> list[Path]:
    """List bhavcopy files whose date falls in [start, end] for the symbol.

    File naming (NSE convention): cm<DD><MMM><YYYY>bhav.csv.zip or
    cm<DD><MMM><YYYY>bhav.csv, e.g. cm01JAN2024bhav.csv.
    Symbol-specific folders are also supported: <symbol>/cm<date>bhav.csv.
    """
    if not BHAVCOPY_ROOT.exists():
        return []

    files: list[Path] = []
    pat = re.compile(r"cm(\d{2})([A-Za-z]{3})(\d{4})bhav", re.I)

    for p in BHAVCOPY_ROOT.rglob("*"):
        if not p.is_file():
            continue
        m = pat.search(p.name)
        if not m:
            continue
        d = _parse_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
        if d is None or d < start or d > end:
            continue
        # If symbol folder present, match it; otherwise accept any
        if symbol:
            parts = p.parts
            if symbol.upper() not in [s.upper() for s in parts]:
                # still accept if at root (symbol not in path)
                if len(p.relative_to(BHAVCOPY_ROOT).parts) > 1:
                    continue
        files.append(p)

    return sorted(files, key=lambda p: p.name)


def load_bhavcopy(symbol: str, start: date, end: date) -> list[dict]:
    """
    Load NSE EOD bhavcopy records for a symbol over [start, end].

    Each record: {date, symbol, open, high, low, close, last, close_price,
    vwap, volume, turnover, trades, deliverable_qty, deliverable_pct, series}

    Returns empty list if no files found or unreadable. Never raises.
    """
    records: list[dict] = []
    for path in discover_files(symbol, start, end):
        try:
            if path.suffix.lower() == ".zip":
                import zipfile
                with zipfile.ZipFile(path) as z:
                    for name in z.namelist():
                        if not name.lower().endswith(".csv"):
                            continue
                        with z.open(name) as f:
                            text = f.read().decode("utf-8", errors="replace")
                            records.extend(_parse_csv(text, symbol))
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
                records.extend(_parse_csv(text, symbol))
        except (OSError, zipfile.BadZipFile, UnicodeDecodeError):
            continue  # skip unreadable files

    # Dedupe by date, sort ascending
    seen: dict[str, dict] = {}
    for r in records:
        seen[r["date"]] = r
    return [seen[d] for d in sorted(seen)]


def _parse_csv(text: str, symbol: str) -> list[dict]:
    """Parse a bhavcopy CSV into normalized records."""
    out: list[dict] = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return out

    # Detect header
    reader = csv.DictReader(lines)
    if not reader.fieldnames:
        return out

    # Normalize header names (NSE uses mixed case, spaces)
    field_map = {f.strip().lower(): f for f in reader.fieldnames}

    def get(row: dict, *names: str) -> str:
        for n in names:
            key = field_map.get(n.strip().lower())
            if key:
                return row.get(key, "")
        return ""

    for row in reader:
        sym = get(row, "symbol", "SYMBOL", "TckrSymb").strip()
        if symbol and sym.upper() != symbol.upper():
            continue
        d = _parse_date(get(row, "date", "DATE", "TradDt"))
        if d is None:
            continue
        series = get(row, "series", "SERIES", "Sgmt").strip()
        out.append({
            "date": d.isoformat(),
            "symbol": sym,
            "series": series,
            "open": _to_float(get(row, "open", "OPEN", "OpnPric")),
            "high": _to_float(get(row, "high", "HIGH", "HighPric")),
            "low": _to_float(get(row, "low", "LOW", "LowPric")),
            "close": _to_float(get(row, "close", "CLOSE", "ClsgPric")),
            "last": _to_float(get(row, "last", "LAST", "LastPric")),
            "close_price": _to_float(get(row, "close_price", "Close Price")),
            "vwap": _to_float(get(row, "vwap", "VWAP", "WghtAvrgPric")),
            "volume": _to_int(get(row, "volume", "VOLUME", "QtyTraded")),
            "turnover": _to_float(get(row, "turnover", "TURNOVER", "TotTradVal")),
            "trades": _to_int(get(row, "trades", "TRADES", "NoOfTrades")),
            "deliverable_qty": _to_int(get(row, "deliverable_qty", "DELIV QTY", "DlvQty")),
            "deliverable_pct": _to_float(get(row, "deliverable_pct", "DELIV %", "DlvPct")),
        })
    return out


def get_close_price(symbol: str, on: date) -> Optional[float]:
    """Single closing price for a symbol on a date. None if unavailable."""
    recs = load_bhavcopy(symbol, on, on)
    return recs[0]["close"] if recs else None


def date_range(d0: date, d1: date) -> list[date]:
    """All calendar dates from d0 to d1 inclusive."""
    days = []
    cur = d0
    while cur <= d1:
        days.append(cur)
        cur += timedelta(days=1)
    return days


if __name__ == "__main__":
    # Self-check: no files expected -> empty, no crash
    recs = load_bhavcopy("NIFTY", date(2020, 1, 1), date(2024, 12, 31))
    print(f"data.py: {len(recs)} bhavcopy records (0 expected if no files present)")
    assert recs == []
    print("data.py: OK")
