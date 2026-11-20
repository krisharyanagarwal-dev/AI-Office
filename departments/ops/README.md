# Ops Department — Company Operations

Function: Company P&L, autonomy tier enforcement, provider health, dashboards, self-upgrade coordination.

## Responsibilities

- Track office P&L (cost vs outcome value by tier and agent)
- Enforce autonomy tier boundaries (A/B/C)
- Monitor provider health (NVIDIA keys, OpenRouter, Google)
- Maintain dashboards (`/metrics` per-cycle reporting)
- Coordinate self-upgrade cycles
- Manage compliance and kill switch status

## Key Metrics

| Metric | Source |
|---|---|
| Tasks per cycle | JEV dispatcher hive |
| Completion rate | Hive task status |
| Error rate | Hive error tasks |
| Provider health | Router status |
| Net value per tier | Task ledger (`office_pnl.json`) |
| Kill switch | `trader_killswitch_status.json` |

---

*Ops Department — Tier B, gated.*