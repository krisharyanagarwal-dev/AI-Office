# Two-Pass Proportional Allocation Design Spec

**Date**: 2026-11-28
**Status**: Draft
**Related**: services/portfolio_optimizer.py, trading-bot/core.py, trading-bot/main.py, trading-bot/config.yaml, trading-bot/run_bot.py

---

## 1. Objective

Extend the single-symbol trading bot to allocate capital proportionally across multiple symbols in two passes:

- Pass 1 (allocation): an allocator over a returns matrix produces a target weight per symbol (long-only, weights >= 0, sum <= 1), e.g. inverse-volatility, risk parity, min variance, Markowitz tangency, fractional Kelly.
- Pass 2 (sizing): each signaled symbol's target weight is converted into an executable position size: `size = (equity * weight) / price`, capped by per-symbol max notional and gated by existing risk limits (daily loss limit, consecutive losses, max trades/day, max open positions).

The bot remains paper/testnet only. `live_orders_allowed` stays false; no live order path is added. Default behavior (single symbol, fixed position-size-percent sizing) is unchanged when allocation is disabled.

---

## 2. Architecture

### 2.1 High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                   config.yaml / CLI flags                        │
│  allocation.enabled  method  lookback_bars  max_position_notional│
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│              build_allocation_engine(config, equity)             │
│  Pass 1: Allocator(returns) -> {symbol: weight}  (sum <= 1)     │
└─────────────────────────────────────────────────────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
        ┌───────────────┐               ┌───────────────┐
        │  PASS 1       │               │   PASS 2      │
        │ allocate()    │               │ size_order()  │
        │ weights per   │               │ size = eq*w/px│
        │ symbol        │               │ capped + gated│
        └──────┬────────┘               └──────┬────────┘
               │                               │
               └───────────────┬───────────────┘
                               ▼
                    ┌─────────────────────┐
                    │ run_allocation_cycle│  per symbol: signal -> size -> order
                    │ (risk gate each)    │  single-symbol fallback unchanged
                    └─────────────────────┘
```

### 2.2 Components changed

| File | Component | Change |
|------|-----------|--------|
| `services/portfolio_optimizer.py` | `allocate()` | Add `target_weights()` wrapper returning sorted, clipped weights; existing allocators unchanged |
| `trading-bot/core.py` | `TradingBot` | Add `AllocationConfig`, `TargetWeight`, `SizedOrder` dataclasses; `set_allocation()`, `size_for_symbol()`; keep `calculate_position_size()` as single-symbol fallback |
| `trading-bot/main.py` | `TradingBotApp` | Per-symbol price buffers; Pass 1 each cycle over returns matrix; Pass 2 per signaled symbol; dispatch sized orders |
| `trading-bot/config.yaml` | `allocation` section | New config block: enabled, method, lookback_bars, max_position_notional, max_open_positions, min_weight |
| `trading-bot/run_bot.py` | launcher | Unchanged (thin shell for main.py) |

No new modules, no new external dependencies (numpy/pandas already present), no changes to the risk governor, no live order path.

---

## 3. Data Models

### 3.1 AllocationConfig

```python
@dataclass(frozen=True)
class AllocationConfig:
    enabled: bool = False           # two-pass allocation on/off
    method: str = "risk_parity"     # inverse_vol | risk_parity | min_variance | markowitz | kelly
    lookback_bars: int = 252        # bars used to build the returns matrix
    max_position_notional: Optional[float] = None  # per-symbol notional cap; None = risk.max_position_size * equity
    max_open_positions: int = 1     # max concurrent open positions
    min_weight: float = 0.0         # drop weights below this from the book
```

Defaults keep current behavior exactly (allocation disabled, single-symbol fixed sizing).

### 3.2 TargetWeight

```python
@dataclass(frozen=True)
class TargetWeight:
    symbol: str
    weight: float          # 0 <= w <= 1
    target_notional: float # equity * weight
```

### 3.3 SizedOrder

```python
@dataclass(frozen=True)
class SizedOrder:
    symbol: str
    side: Signal
    size: float            # base asset quantity
    notional: float        # size * price
    price: float
    reason: str            # "allocated" | "risk_gated" | "skipped"
```

---

## 4. Data Flow

1. Each cycle, `TradingBotApp` updates per-symbol close-price buffers for all symbols in `trading.symbols` (fallback to `trading.symbol` single entry).
2. When enough bars exist (>= lookback_bars), Pass 1 builds a returns matrix from the buffers and calls `portfolio_optimizer.allocate(returns, method=config.method)` → {symbol: weight}.
3. Pass 1 output: `TargetWeight` per symbol with weight >= min_weight, sorted desc by weight. Allocators already guarantee weights >= 0 and sum <= 1 via `_finish()`.
4. Pass 2: for each symbol in weight order where the strategy emits BUY/SELL and no position exists:
   - `target_notional = equity * weight`
   - `size = target_notional / price`
   - cap `size` by `max_position_notional / price`
   - run `_entry_risk_gate()` (daily trades, loss limit, streak, open positions)
   - if passed → `SizedOrder(symbol, side, size, notional, price, "allocated")` → order; else `SizedOrder(..., reason="risk_gated")` → skip
5. Single-symbol fallback: when `allocation.enabled` is false, `calculate_position_size(price)` (balance * position_size_percent / price) is used exactly as today.
6. State snapshot/restore records allocation config and current weights so restarts are deterministic.

---

## 5. Error Handling

| Failure | Behavior |
|---------|----------|
| Insufficient bars (< lookback) | Skip allocation; use single-symbol fallback for the configured symbol |
| Empty returns matrix / allocator error | Fall back to equal weights across signaled symbols, or single-symbol fallback |
| Weight = 0 for a symbol | Symbol excluded from Pass 2 |
| Risk gate blocks | `SizedOrder` with reason="risk_gated"; no order placed; book unchanged |
| Order rejected by venue | Position not opened; `daily_trades` not incremented; book unchanged |
| Non-paper broker | Guarded as today — testnet/paper only; live fails closed |

The rollback invariant from execution realism applies: a rejected target leaves no open exposure behind.

---

## 6. Implementation Phases

### Phase 1: Spec & tests (TDD red)

Write `tests/test_two_pass_allocation.py` with failing tests:
- weight book invariant: weights >= 0, sum <= 1
- sizing formula: size = equity * weight / price
- notional cap respected
- risk gate skip produces no order
- single-symbol fallback unchanged (allocation off)

### Phase 2: Core sizing (TDD green)

- Add `AllocationConfig`, `TargetWeight`, `SizedOrder` dataclasses to `core.py`.
- Add `TradingBot.set_allocation()` / `size_for_symbol()` to `core.py`.
- Wire Pass 1/Pass 2 into `TradingBotApp` run loop in `main.py`.
- Add `allocation` block to `config.yaml`.

### Phase 3: Integration test

Add `tests/test_two_pass_allocation_integration.py` exercising full cycle: returns → weights → sized orders → risk gate → dashboard snapshot includes allocation weights.

### Phase 4: Verification

- Run full `pytest` suite for trading-bot (no regressions; single-symbol default tests pass unchanged).
- Run quality gate (`scripts/run_quality_gate.py`).
- Confirm determinism: same config + same inputs → identical weights across runs.

---

## 7. Configuration

### 7.1 allocation block (config.yaml)

```yaml
allocation:
  enabled: false
  method: risk_parity
  lookback_bars: 252
  max_position_notional: null
  max_open_positions: 1
  min_weight: 0.0
```

### 7.2 CLI flags (run_bot.py / main.py parser)

```
--allocation        store_true, default off
--allocation-method choice, default risk_parity
--allocation-lookback int, default 252
```

---

## 8. Success Criteria

| Metric | Target |
|--------|--------|
| Weight book | weights >= 0, sum <= 1, deterministic per inputs |
| Sizing formula | size = equity * weight / price, capped by max notional |
| Single-symbol default | allocation disabled → identical behavior to today (fixed position_size_percent) |
| Risk gate | gated symbols produce no order; book unchanged |
| Determinism | same config + same inputs → identical fills across runs |
| Paper-only | live_orders_allowed stays false; no live order path added |
| Regression | all existing trading-bot tests pass with default (allocation off) |

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Allocator produces NaN/inf weights | Medium | High | clip negatives; nan-to-num; fallback to equal weights |
| Multi-symbol run loop slows ticks | Low | Medium | Pass 1 runs once per cycle, not per tick; lookback bounded |
| Weight churn causes overtrading | Medium | Medium | min_weight threshold; max_open_positions cap; existing daily trade limit |
| Config drift between passes | Low | Low | single AllocationConfig object shared by Pass 1 and Pass 2 |

---

## 10. Open Questions

1. Should Pass 1 run on every closed kline or on a separate time-based schedule? (Current: every closed kline cycle for simplicity.)
2. Should short signals be allowed in allocation mode, or long-only? (Current: long-only weights; side comes from the strategy signal.)
3. Should the returns matrix use log returns or simple returns? (Current: simple pct_change, consistent with portfolio_optimizer.)

---

## 11. Approval

- [ ] Design reviewed by user
- [ ] Spec committed to git
- [ ] Implementation plan created via writing-plans skill
