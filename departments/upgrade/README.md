# Upgrade Department — Self-Improvement System

Function: The company upgrades itself — code, prompts, configs, processes, continuously.

## Upgrade Targets

| Target | Method | Frequency |
|---|---|---|
| Code (dispatcher, strategies, engine) | Refactor, test, deploy | Every cycle |
| Prompts (agent directives) | A/B test, tripartite verify | Weekly |
| Configs (universe, costs, params) | Drift detection, re-validate | Monthly |
| Processes (gate rules, tiers) | Review, consensus change | Quarterly |

## Upgrade Rules

- No upgrade without test pass (35/35 dispatcher tests must pass)
- No upgrade without verification (O1 tripartite for major changes)
- No upgrade that touches Tier C (kill switch, execution) without human gate
- All upgrades logged with before/after metrics

## Current Upgrade Candidates

1. **Dispatcher**: Add general assistant routing (non-trading tasks)
2. **Cost model**: Real SPAN margin approximation (replacing 15% estimate)
3. **Data**: 2020-2024 bhavcopy for longer backtests
4. **Strategies**: Calendar spreads, ratio spreads (after holdout validation)
5. **Dashboard**: Per-cycle + per-agent breakdown

---

*Upgrade Department — Tier B, gated, continuous.*