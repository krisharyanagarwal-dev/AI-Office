# Execution Realism Design Spec

**Date**: 2026-11-25
**Status**: Draft
**Related**: best_signal/execution.py, best_signal/runner.py, best_signal/position.py, risk.py

---

## 1. Objective

Add execution realism to the paper-only best-signal venue so the paper book prices execution the way a real venue would: slippage against the direction of each fill, partial fills that can break a delta-flat carry, and simulated per-leg latency. The venue must remain paper-only (no live credentials, no exchange access, `live_orders_allowed` stays false), and every change must be deterministic and testable with hand-derived expected values.

---

## 2. Architecture

### 2.1 High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                   BotConfig / CLI flags                          │
│  slippage_bps  latency_ms  partial_fill  partial_fill_fraction   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│             build_paper_venue(equity, realism=ExecutionRealism)  │
│  CarryPaperBroker(slippage_bps, latency_ms, ...)                │
└─────────────────────────────────────────────────────────────────┘
                                 │
                  ┌──────────────┼──────────────┐
                  ▼              ▼              ▼
         ┌─────────────┐ ┌───────────┐ ┌──────────────┐
         │   slippage  │ │  latency  │ │ partial fill │
         │   model     │ │  (sleep)  │ │   handling   │
         └──────┬──────┘ └─────┬─────┘ └──────┬───────┘
                │              │              │
                └──────────────┴──────────────┘
                                 ▼
                    ┌───────────────────────┐
                    │   _execute_market     │  fill price = price ± slippage
                    │   (per leg, serial)   │  commission on filled qty @ fill px
                    └──────────────┬────────┘
                                   ▼
                    ┌───────────────────────┐
                    │   run_paper_execution │  partial fill -> rollback filled legs
                    │   (leg loop + rollback│  full fill -> ExecutionResult.filled
                    │    on reject)         │  partial fill -> ExecutionResult.filled=False
                    └───────────────────────┘
```

### 2.2 Components changed

| File | Component | Change |
|------|-----------|--------|
| `best_signal/execution.py` | `ExecutionRealismConfig` (new dataclass) | slippage_bps, latency_ms, partial_fill_enabled, partial_fill_fraction |
| `best_signal/execution.py` | `CarryPaperBroker.__init__` | accept realism config; store slippage_bps, latency_ms, partial_fill settings |
| `best_signal/execution.py` | `CarryPaperBroker._execute_market` | apply slippage to fill price, simulate latency, support partial fill quantity |
| `best_signal/execution.py` | `run_paper_execution` | propagate realism; handle partial fills (rollback filled legs on partial), return partial-fill result |
| `best_signal/runner.py` | `BotConfig` | add `execution_realism: ExecutionRealismConfig` field |
| `best_signal/runner.py` | `run_bot` | pass realism config into `build_paper_venue` |
| `best_signal/runner.py` | CLI parser | add `--slippage-bps`, `--latency-ms`, `--partial-fill`, `--partial-fill-fraction` flags |

No new modules, no new external dependencies, no changes to the risk governor or position emitter.

---

## 3. Data Models

### 3.1 ExecutionRealismConfig

```python
@dataclass(frozen=True)
class ExecutionRealismConfig:
    slippage_bps: float = 0.0          # basis points of slippage per leg, against trade direction
    latency_ms: float = 0.0            # simulated per-leg venue latency (ms)
    partial_fill_enabled: bool = False # whether legs may partially fill
    partial_fill_fraction: float = 0.5 # fraction of quantity filled when partial (0 < f <= 1)
```

Defaults keep current behavior exactly (zero slippage, zero latency, no partial fills).

### 3.2 Fill price with slippage

For a leg of quantity `q` at order price `p`:
- BUY: `fill_price = p * (1 + slippage_bps / 10_000)` (fills worse, higher)
- SELL: `fill_price = p * (1 - slippage_bps / 10_000)` (fills worse, lower)

Commission = `filled_qty * fill_price * commission_rate` (unchanged 5 bps default).

### 3.3 ExecutionResult additions

| Field | Meaning |
|-------|---------|
| `filled` | True only when every leg filled in full |
| `partial` | True when at least one leg partially filled (book not delta-flat) |
| `reason` | `"filled"`, `"partial:{symbol}"`, `"leg_rejected:{symbol}"`, `"risk_rejected"`, `"stand_down"`, `"held"` |

---

## 4. Data Flow

1. `runner.run_bot` builds `ExecutionRealismConfig` from `config.execution_realism` and calls `build_paper_venue(equity, realism=config)`.
2. `build_paper_venue` constructs `CarryPaperBroker` with the realism settings and returns `(engine, broker)`.
3. For each symbol target, `run_paper_execution` submits legs serially via `_submit_leg` → `engine.submit_order` → `CarryPaperBroker._execute_market`.
4. `_execute_market` sleeps `latency_ms`, computes slippage-adjusted fill price, fills full quantity or a partial fraction (when `partial_fill_enabled`), updates cash/margin/positions/commission.
5. `run_paper_execution` inspects each order status:
   - Full fill on all legs → `ExecutionResult(filled=True, reason="filled")`.
   - Any leg rejected or partial → rollback all filled legs (reverse at order price), return `ExecutionResult(filled=False, reason="leg_rejected:{symbol}" or "partial:{symbol}")`, book restored to flat.
6. Venue snapshot/restore (state persistence) is unchanged; realism config is recorded in state so restarts are deterministic.

---

## 5. Error Handling

| Failure | Behavior |
|---------|----------|
| Non-paper broker | `LiveVenueRefused` before any order is built (unchanged guard) |
| No market price | Order `REJECTED`; triggers rollback of previously filled legs |
| Partial fill | Filled legs rolled back at order price; book flat, `filled=False` |
| Rollback failure | Best-effort reverse orders; result still reports `filled=False`, never leaves a half-carry silently |
| Latency | Simulated via `asyncio.sleep`; never throws, never blocks the runner loop |

The rollback invariant is preserved: a rejected or partially filled target leaves no open exposure behind.

---

## 6. Implementation Phases

### Phase 1: Spec & tests (TDD red)
- Write `tests/test_execution_realism.py` with failing tests for slippage fill price, partial fill + rollback, latency presence, and config defaults.

### Phase 2: Venue implementation (TDD green)
- Add `ExecutionRealismConfig` dataclass to `execution.py`.
- Thread realism config through `CarryPaperBroker.__init__`.
- Implement slippage-adjusted fill price + latency + partial fill in `_execute_market`.
- Implement partial-fill handling + rollback in `run_paper_execution`.
- Add `partial` field to `ExecutionResult`.

### Phase 3: Runner config propagation
- Add `execution_realism` field to `BotConfig` (defaults to zero-realism config).
- Pass it into `build_paper_venue` in `run_bot`.
- Add CLI flags (`--slippage-bps`, `--latency-ms`, `--partial-fill`, `--partial-fill-fraction`).

### Phase 4: Verification
- Run full `pytest` suite for `best_signal` + `risk` (no regressions; existing zero-realism tests must pass unchanged).
- Run `tsc` type check for unified-api (unaffected, but confirm no cross-repo breakage).
- Confirm state snapshot/restore round-trips with realism config recorded.

---

## 7. Configuration

### 7.1 Execution realism config (code)

```python
ExecutionRealismConfig(
    slippage_bps=0.0,
    latency_ms=0.0,
    partial_fill_enabled=False,
    partial_fill_fraction=0.5,
)
```

### 7.2 CLI flags (runner)

```
--slippage-bps      float, default 0.0
--latency-ms        float, default 0.0
--partial-fill      store_true, default off
--partial-fill-fraction float, default 0.5
```

---

## 8. Success Criteria

| Metric | Target |
|--------|--------|
| Slippage fill price | buy fills at `p * (1 + bps/10000)`, sell at `p * (1 - bps/10000)` |
| Partial fill rollback | rejected/partial target leaves broker positions flat, `filled=False` |
| Latency | per-leg `latency_ms` sleep applied; zero when unset |
| Determinism | same config + same inputs → identical fills across runs |
| Paper-only | `LiveVenueRefused` still raised for any non-paper broker; `live=False`, `mode="PAPER"` unchanged |
| Regression | all existing `test_best_signal_execution.py` hand-derived values pass with default (zero) realism |

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Partial fill breaks delta-flat book silently | Medium | High | Rollback filled legs on any partial; never leave half-carry open |
| Slippage changes fee math / break-even | Medium | Medium | Commission computed on filled qty at slippage-adjusted price; defaults zero |
| Latency slows test suite | Low | Low | Tests use `latency_ms=0`; realism latency opt-in via config |
| State restore loses realism config | Low | Low | Record realism config in venue snapshot/state |

---

## 10. Open Questions

1. Should partial fill retry the remaining quantity at the same price instead of rolling back? (Current: rollback, keeps book delta-flat.)
2. Should slippage be symmetric (both sides) or asymmetric (taker only)? (Current: symmetric, against trade direction.)

---

## 11. Approval

- [ ] Design reviewed by user
- [ ] Spec committed to git
- [ ] Implementation plan created via writing-plans skill
