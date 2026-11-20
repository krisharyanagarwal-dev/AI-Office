# Trading Department — Paper Trading Engine

Function: Paper backtesting, forward simulation, cost modeling, strategy testing on NSE equities and options.

## Core Modules

| Module | File | Function |
|---|---|---|
| Config | `config.py` | Universe (~130 liquid NSE), cost model, params |
| Costs | `costs.py` | Groww fee model (brokerage, STT, stamp, GST, SEBI/exchange, slippage) |
| Data | `data.py` | yfinance daily + 15m, local CSV cache |
| Indicators | `indicators.py` | EMA, RSI |
| Backtests | `backtest_*.py` | 19 strategy variants tested |
| Options Data | `options_data.py` | NSE bhavcopy downloader/parser (free) |
| Options Backtest | `backtest_options_selling.py` | Straddle/strangle/CSP |
| Defined Risk | `backtest_defined_risk.py` | Iron condor, bull put, bear call |
| Chain Metrics | `chain_metrics.py` | IV rank, PCR, max pain, OI walls |
| Paper Trader | `paper_trader.py` | Forward engine, pending_signals.json, day-lag timing |

## Cost Model (Groww, Honest)

- Brokerage: ₹20/order min or 0.05%
- STT: 0.025% intraday / 0.0625% options sell
- Stamp: 0.003% buy side
- SEBI/Exchange: 0.0035% both sides
- GST: 18% on brokerage
- Slippage: 0.05% equity / 0.1% options per side

## Round-Trip Cost on ₹50k Equity Position

~₹126 = 0.25%. Required edge per trade: >0.25%.

## Current Status

- 19+ strategy variants tested — all fail after costs at ₹1L
- Paper engine ready: `paper_trader.py` with `state/` (ledger.json, positions.json, pending_signals.json, equity_curve.csv)
- Honest day-lag timing: signal at close T → execute at open T+1
- No strategy passed the profitability gate

---

*Department of Trading — Paper only, kill switch LOCKED.*