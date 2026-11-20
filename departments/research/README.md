# Research Department — NSE Research Machine

Function: Hypothesis-driven research with pre-registration, verdict gates, holdout confirmation, calibration tracking, and public reports.

## Core Modules

| Module | File | Function |
|---|---|---|
| Hypothesis Queue | `hypothesis_queue.py` | Pre-register hypotheses before backtest |
| Verdict Gate | `verdict_gate.py` | Cost-honest profitability gate (≥50 trades, edge excludes zero, DD limit) |
| Holdout | `verdict_gate.py` | Out-of-sample confirmation |
| Calibration | `calibration_ledger.py` | Predicted vs realized edge tracking |
| Public Record | `research_report.py` | Monthly honest reports (wins AND losses) |
| O3 Runner | `o3_runner.py` | End-to-end pipeline: register → gate → holdout → calibrate → report |

## Gate Rules (Non-Negotiable)

- ≥50 trades
- Net P&L > 0
- Edge after costs excludes zero (CI lower bound > 0)
- Max drawdown ≤ 15%
- Per-trade cost < 10% of gross credit
- Holdout: not destroyed, DD tolerable

## Data Sources (Free, Keyless)

- yfinance: Daily + 15m intraday (60 days)
- nsearchives.nseindia.com: F&O bhavcopy (EOD options, 20+ years), F&O participant OI
- nsepython: FII/DII (today only)

## Current Status

- Naked options selling: +₹3.95L on ₹5L (2025), but blocked at ₹1L (margin ~₹94k/lot)
- Defined-risk spreads (bull put IV rank ≥80%): +₹762 in 2025, **-₹5,330 in 2026 holdout** — FAIL
- **Verdict: No viable edge at ₹1L + free data** (proven, in-sample + out-of-sample)

---

*Department of Research — Auto-upgraded every cycle.*