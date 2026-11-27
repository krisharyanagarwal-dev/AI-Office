# Screener EV / New-Age Integration — Design Spec

**Date:** 2026-11-28
**Status:** Draft (pending user review)
**Scope:** Project 1 of the three remaining dost goals (EV/new-age/high-growth criteria integrated into screener-manip-watch).

## 1. Goal

Expand `screener-manip-watch` (`dost/ops/screener_manip_watch.py`, committed as `73db1049`) beyond its current OLAELEC/technicals manipulation signals by incorporating High Growth EV and New-Age Sector criteria, which are not available in screener.in's free pages.

All actions remain paper/testnet-only: task re-dispatch, pool failover, service restarts never place live orders or touch credentials.

## 2. Requirements

- **R1 (Data source):** Read-only keyless screener APIs only — TradingView scanner API (primary, already validated for NSE) + yfinance (secondary, keyless, unofficial/fragile). No credentials may be read or stored.
- **R2 (Both sources required):** A symbol is emitted only if both TradingView and yfinance succeed for that symbol. Missing/invalid fields count as a source failure; the symbol is skipped entirely. No partial rows, no fallbacks to single-source.
- **R3 (Artifact):** Ingestion writes `screener_ev_<timestamp>.csv` to repo root, matching the existing screener artifact glob pattern (`all_stocks_summary_*.csv`) so `screener-manip-watch` can discover it via `_artifact_paths`.
- **R4 (Empty universe):** If zero symbols pass, an empty artifact with headers only is still written (pipeline-health can detect empty universe).
- **R5 (Internal skill interface):** `dost/skills/screener_ev_integration.py` exposes `get_ev_criteria(symbol)`, `get_all_ev_criteria()`, `is_ev_new_age(symbol)`, `latest_artifact_path()` — decoupling screener-manip-watch from vendor format.
- **R6 (Consumption):** `screener-manip-watch.run_once()` enriches rows via the skill interface and adds an EV/new-age component (+10-15 points when `is_ev_new_age`) to `_manipulation_score`, still capped at 100.
- **R7 (Graceful degradation):** No EV artifact → rows skip EV scoring (not failed). yfinance outage → empty artifact → pipeline stuck → stuck-task check. No crashes on missing data.
- **R8 (Testing):** Unit tests for ingestor, skill interface, and extended manip-watch scoring; no network, no credentials; run from `dost/` via `python3 -m pytest`.

## 3. Components

### `dost/ops/screener_ingest.py` — ingestion pipeline

- `fetch_tradingview(symbols) -> dict[str, dict]` — per-symbol TradingView scanner query; technicals + basic multiples (P/E, momentum, leverage flags, pct_from_52w_high).
- `fetch_yfinance(symbol) -> dict | None` — keyless yfinance query for EV/new-age fundamentals: market cap, sector, revenue growth, EV/EBITDA, debt/equity, current ratio. Returns None on failure.
- `normalize(symbol, tv_data, yf_data) -> dict | None` — merges both into internal schema; returns None if either source lacks required fields.
- `write_artifact(rows) -> Path` — writes `screener_ev_<timestamp>.csv` with headers: `symbol, sector, market_cap, revenue_growth, ev_ebitda, pe_ttm, debt_to_equity, current_ratio, momentum_flag, leverage_flag, pct_from_52w_high, ev_new_age_score`.
- `ingest(symbols) -> Path` — orchestration: fetch both → normalize (skip failures) → write artifact.

### `dost/skills/screener_ev_integration.py` — internal skill interface

- `get_ev_criteria(symbol: str) -> dict | None` — criteria for one symbol from latest artifact.
- `get_all_ev_criteria() -> list[dict]` — all symbols' criteria.
- `is_ev_new_age(symbol: str) -> bool` — `ev_new_age_score >= 70`.
- `latest_artifact_path() -> Path | None` — most recent `screener_ev_*.csv`.
- Lazy loads + caches per cycle; degrades to None/empty when no artifact exists.
- Follows dost skill registry pattern.

### `dost/ops/screener_manip_watch.py` — consumption (modified)

- `run_once()` enriches each row via `get_ev_criteria(symbol)` before scoring.
- `_manipulation_score()` gains EV/new-age component: +10-15 points when `is_ev_new_age(symbol)`, within existing 0-100 cap.
- Signals carry EV/new-age fields; rows without criteria skip EV scoring.

## 4. Data flow

```
symbols list
   │
   ▼
ingest(symbols)
   ├─ fetch_tradingview(symbol)  [fail → skip symbol]
   ├─ fetch_yfinance(symbol)     [fail → skip symbol]
   ├─ normalize → internal schema
   └─ write screener_ev_<ts>.csv
   │
   ▼ (separate cycle)
screener-manip-watch.run_once()
   ├─ load artifacts incl. screener_ev_*.csv
   ├─ for each row: get_ev_criteria(symbol) → enrich
   ├─ _manipulation_score(row) with EV/new-age +10-15 if is_ev_new_age
   └─ severity mapping → FleetSelfHealing (unchanged)
```

## 5. Error handling

| Failure | Behavior |
|---|---|
| TradingView fetch fails for symbol | Symbol skipped |
| yfinance fetch fails for symbol | Symbol skipped |
| Both succeed, fields missing/invalid | Symbol skipped (counts as source failure) |
| Zero symbols pass | Empty artifact with headers written |
| No EV artifact exists in run_once | Rows skip EV scoring; manipulation_score omits EV component |
| Network error mid-batch | Per-symbol isolation; batch continues for remaining symbols |

No retries, no credential access, no live-order paths.

## 6. Testing

- `dost/tests/test_screener_ingest.py` — both-sources-required invariant, per-symbol isolation, empty-artifact-with-headers, normalization schema.
- `dost/tests/test_screener_ev_integration.py` — skill interface vs fake artifact; `is_ev_new_age` threshold (70); graceful degradation with no artifact.
- `dost/tests/test_screener_manip_watch.py` extended — EV/new-age +10-15 points, cap at 100, rows without criteria skip EV scoring.
- All run from `dost/` via `python3 -m pytest`; no network, no credentials.

## 7. Out of scope

- Dedicated launchd job for the ingestor (ingestion is invoked by screener-manip-watch's run_once cycle; decoupling can be revisited later).
- Paid/fundamental-data APIs requiring credentials.
- Modifying existing `all_stocks_summary_*.csv` generation.
