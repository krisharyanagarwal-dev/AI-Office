# Fleet Department — JEV 32-Agent Dispatch

Function: Autonomous agent fleet with verification, tripartite consensus, autonomy tiers, cost-per-outcome accounting.

## Structure

- 32 agents across 2 tiers (pro/lite)
- 10 worker processes × 20 threads
- Cloud-only (NVIDIA/OpenRouter/Gemini), no local Qwen for fleet tasks
- Kill switch: LOCKED (permanent)

## Autonomy Tiers

| Tier | Role | Agents | Count |
|---|---|---|---|
| A | Autonomous (research, data, content) | 13 agents | data, regime, correlation, volatility, order-book, liquidity, exposure, signal, event, archivists |
| B | Gated (writes to stores, analysis artifacts) | 12 agents | quant, backtest, quant-model-validator, position-sizing, cost, strategy-advisor, portfolio-allocation, performance, drawdown, liquidation, perp-funding |
| C | Human only (risk, execution, kill switch, broker) | 7 agents | risk-manager, risk-control-verifier, compliance-checker, execution-strategist, execution-analyst, market-maker, portfolio-manager |

## Verification Layer (O1)

- Producer ≠ verifier (independent checker for every finding)
- Tripartite consensus + devil-advisor for major verdicts (strategy, risk, backtest domains)
- Synthesis respects verification status (confirmed/pending/contested)

## Cost-Per-Outcome (O2)

- Pro pool = 3 units/call, general = 2, lite = 1
- Outcome value: confirmed = +10, pending = +2, contested = -5
- Ledger: `/Users/aryanagarwal/.openclaw/office_pnl.json`
- CLI: `python jev-dispatcher.py --pnl`

## Boundaries

- Kill switch: LOCKED
- `live_orders_allowed`: false
- No order path ever added
- No broker connection

---

*Fleet Department — Paper only, verified, tiered.*