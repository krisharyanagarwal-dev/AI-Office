"""Tests for dost ops screener EV/new-age ingestion pipeline.

Covers the both-sources-required invariant, per-symbol isolation,
empty-artifact-with-headers, and the normalization schema. All fetches are
mocked — no network, no credentials.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ops.screener_ingest import (
    CSV_FIELDNAMES,
    EV_NEW_AGE_THRESHOLD,
    TRADINGVIEW_SCAN_URL,
    _tv_numbers,
    ingest,
    normalize,
    write_artifact,
)

TV_COLUMNS = ["name", "close", "change", "pe_ttm_fwd", "high_52w", "low_52w"]

TECHNICALS = {
    "symbol": "EVSTOCK",
    "close": 2500.0,
    "change": 6.5,
    "pe_ttm": 45.0,
    "pct_from_52w_high": -5.0,
    "momentum_flag": "Parabolic",
}

FUNDAMENTALS = {
    "sector": "Technology",
    "market_cap": 50_000_000_000.0,
    "revenue_growth": 0.30,
    "ev_ebitda": 25.0,
    "debt_to_equity": 40.0,
    "current_ratio": 2.0,
}


class _FakeFetchTV:
    """Fake fetch_tradingview: returns selected technicals, no network."""

    def __init__(self, results: dict[str, dict] | None = None, fail: set[str] | None = None):
        self.results = results or {}
        self.fail = fail or set()
        self.called_with: list[list[str]] = []

    def __call__(self, symbols: list[str], timeout: float = 10.0) -> dict[str, dict]:
        self.called_with.append(list(symbols))
        return {s: d for s, d in self.results.items() if s in symbols and s not in self.fail}


class _FakeFetchYF:
    """Fake fetch_yfinance: returns selected fundamentals or None, no network."""

    def __init__(self, results: dict[str, dict] | None = None):
        self.results = results or {}
        self.called_with: list[str] = []

    def __call__(self, symbol: str) -> dict | None:
        self.called_with.append(symbol)
        return self.results.get(symbol)


# ----------------------- normalization schema -----------------------

def test_normalize_merges_both_sources_into_internal_schema():
    row = normalize("EVSTOCK", TECHNICALS, FUNDAMENTALS)

    assert row is not None
    assert set(row) == set(CSV_FIELDNAMES)
    assert row["symbol"] == "EVSTOCK"
    assert row["sector"] == "Technology"
    assert row["market_cap"] == 50_000_000_000.0
    assert row["revenue_growth"] == 0.30
    assert row["ev_ebitda"] == 25.0
    assert row["pe_ttm"] == 45.0  # from TradingView
    assert row["debt_to_equity"] == 40.0
    assert row["current_ratio"] == 2.0
    assert row["momentum_flag"] == "Parabolic"  # from TradingView
    assert row["leverage_flag"] == "Low"  # debt_to_equity 40 <= 50
    assert row["pct_from_52w_high"] == -5.0
    assert row["ev_new_age_score"] == 100.0  # 35 + 20 + 25 + 10 + 10, capped


def test_normalize_upcases_symbol():
    tv = dict(TECHNICALS, symbol="evstock")
    row = normalize("evstock", tv, FUNDAMENTALS)
    assert row["symbol"] == "EVSTOCK"


@pytest.mark.parametrize("debt_to_equity,expected", [
    (0.0, "Low"), (50.0, "Low"), (51.0, "High"), (100.0, "High"), (101.0, "Extreme"),
])
def test_normalize_leverage_flag_boundaries(debt_to_equity, expected):
    yf = dict(FUNDAMENTALS, debt_to_equity=debt_to_equity)
    assert normalize("SYM", TECHNICALS, yf)["leverage_flag"] == expected


def test_normalize_passes_through_tv_momentum_and_pct_from_high():
    tv = dict(TECHNICALS, momentum_flag="Elevated", pct_from_52w_high=-60.0)
    row = normalize("SYM", tv, FUNDAMENTALS)
    assert row["momentum_flag"] == "Elevated"
    assert row["pct_from_52w_high"] == -60.0


@pytest.mark.parametrize("tv,yf", [
    (None, FUNDAMENTALS),
    (TECHNICALS, None),
    (None, None),
    ({**TECHNICALS, "pe_ttm": None}, FUNDAMENTALS),
    ({**TECHNICALS, "pct_from_52w_high": None}, FUNDAMENTALS),
    ({**TECHNICALS, "change": None}, FUNDAMENTALS),
    (TECHNICALS, {**FUNDAMENTALS, "sector": None}),
    (TECHNICALS, {**FUNDAMENTALS, "market_cap": None}),
    (TECHNICALS, {**FUNDAMENTALS, "revenue_growth": None}),
    (TECHNICALS, {**FUNDAMENTALS, "ev_ebitda": None}),
    (TECHNICALS, {**FUNDAMENTALS, "debt_to_equity": None}),
    (TECHNICALS, {**FUNDAMENTALS, "current_ratio": None}),
])
def test_normalize_skips_when_required_fields_missing(tv, yf):
    assert normalize("SYM", tv, yf) is None


# ----------------------- TradingView technicals -----------------------

def test_tv_numbers_computes_pct_from_52w_high_and_momentum():
    out = _tv_numbers({"name": "X", "close": 900.0, "change": 6.0, "pe_ttm_fwd": 30.0, "high_52w": 1000.0})
    assert out["pct_from_52w_high"] == -10.0
    assert out["momentum_flag"] == "Parabolic"
    assert out["pe_ttm"] == 30.0

    out = _tv_numbers({"name": "X", "close": 1000.0, "change": 3.0, "pe_ttm_fwd": 30.0, "high_52w": 1000.0})
    assert out["pct_from_52w_high"] == 0.0
    assert out["momentum_flag"] == "Elevated"

    out = _tv_numbers({"name": "X", "close": None, "change": None, "pe_ttm_fwd": None, "high_52w": None})
    assert out["pct_from_52w_high"] is None
    assert out["momentum_flag"] == "Normal"

    out = _tv_numbers({"name": "X", "close": 500.0, "change": 1.0, "pe_ttm_fwd": 30.0, "high_52w": 0})
    assert out["pct_from_52w_high"] is None


# ----------------------- artifact writing -----------------------

def test_write_artifact_writes_headers_and_rows(tmp_path: Path):
    rows = [normalize("EVSTOCK", TECHNICALS, FUNDAMENTALS)]
    path = write_artifact(rows, artifact_dir=tmp_path)

    assert path.exists()
    assert path.name.startswith("screener_ev_") and path.name.endswith(".csv")
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == list(CSV_FIELDNAMES)
        written = list(reader)
    assert len(written) == 1
    assert written[0]["symbol"] == "EVSTOCK"
    assert written[0]["ev_new_age_score"] == "100.0"


def test_write_artifact_empty_writes_headers_only(tmp_path: Path):
    path = write_artifact([], artifact_dir=tmp_path)
    with path.open(newline="") as fh:
        lines = fh.read().strip().splitlines()
    assert lines == [",".join(CSV_FIELDNAMES)]


# ----------------------- ingest orchestration -----------------------

def test_ingest_skips_symbols_failing_either_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tv_fake = _FakeFetchTV(results={
        "EVSTOCK": TECHNICALS,
        "DEAD": TECHNICALS,
        "GHOST": TECHNICALS,
    })
    yf_fake = _FakeFetchYF(results={
        "EVSTOCK": FUNDAMENTALS,
        # DEAD and GHOST fail yfinance -> skipped
    })
    monkeypatch.setattr("ops.screener_ingest.fetch_tradingview", tv_fake)
    monkeypatch.setattr("ops.screener_ingest.fetch_yfinance", yf_fake)

    path = ingest(["EVSTOCK", "DEAD", "GHOST"], artifact_dir=tmp_path)

    assert path.parent == tmp_path
    assert path.name.startswith("screener_ev_") and path.name.endswith(".csv")
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["symbol"] for r in rows] == ["EVSTOCK"]
    assert tv_fake.called_with == [["EVSTOCK", "DEAD", "GHOST"]]  # one batch query
    assert set(yf_fake.called_with) == {"EVSTOCK", "DEAD", "GHOST"}  # per-symbol, isolated


def test_ingest_empty_universe_still_writes_headers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("ops.screener_ingest.fetch_tradingview", lambda symbols, timeout=10.0: {})
    monkeypatch.setattr("ops.screener_ingest.fetch_yfinance", lambda symbol: None)

    path = ingest(["ANY"], artifact_dir=tmp_path)

    with path.open(newline="") as fh:
        lines = fh.read().strip().splitlines()
    assert lines == [",".join(CSV_FIELDNAMES)]
