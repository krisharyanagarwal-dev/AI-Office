"""Funding print loading and carry statistics.

Primary source is the archived primary data under
``packages/_archive/all-files/parquet/*_funding.parquet``: one row per native
8h funding print. The archived deep JSON files used by earlier research are
accepted as an equivalent fallback.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

PERIODS_PER_YEAR = 365 * 3

PACKAGES_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PACKAGES_ROOT / "_archive/all-files/parquet"


@dataclass(frozen=True)
class FundingPrint:
    ts_ms: int
    rate: float


def _prints_from_frame(frame: pd.DataFrame) -> list[FundingPrint]:
    timestamps = frame["fundingTime"]
    if pd.api.types.is_datetime64_any_dtype(timestamps):
        timestamps = pd.to_datetime(timestamps, utc=True).astype("int64") // 1_000_000
    records = [
        FundingPrint(ts_ms=int(ts), rate=float(rate))
        for ts, rate in zip(timestamps, frame["fundingRate"])
    ]
    return sorted(records, key=lambda print: print.ts_ms)


def _prints_from_payload(payload) -> list[FundingPrint]:
    rows = payload["funding"] if isinstance(payload, dict) else payload
    records = [FundingPrint(ts_ms=int(row["t"]), rate=float(row["rate"])) for row in rows]
    return sorted(records, key=lambda print: print.ts_ms)


def load_funding_prints(path) -> list[FundingPrint]:
    """Load funding prints from a parquet or deep-JSON file, oldest first."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return _prints_from_frame(pd.read_parquet(path))
    if suffix == ".json":
        return _prints_from_payload(json.loads(path.read_text()))
    raise ValueError(f"unsupported funding file type: {path.suffix}")


def load_symbol_prints(symbol: str, data_dir=None) -> list[FundingPrint]:
    """Load the funding history for a symbol such as ``BTCUSDT``."""
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    candidates = [
        root / f"{symbol}_funding.parquet",
        root / f"funding_{symbol}_deep.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return load_funding_prints(candidate)
    raise FileNotFoundError(
        f"no funding history for {symbol} under {root} (looked for "
        + ", ".join(candidate.name for candidate in candidates)
        + ")"
    )


def annualized_funding(
    prints: Sequence[FundingPrint], periods_per_year: int = PERIODS_PER_YEAR
) -> float:
    """Annualized carry in return-on-notional units (1.0 = 100% per year)."""
    if not prints:
        return 0.0
    mean_rate = sum(print.rate for print in prints) / len(prints)
    return mean_rate * periods_per_year


def positive_print_fraction(prints: Iterable[FundingPrint]) -> float:
    """Share of prints with positive funding (the carry drift's raw support)."""
    prints = list(prints)
    if not prints:
        return 0.0
    return sum(1 for print in prints if print.rate > 0) / len(prints)
