# Trading Research Fleet — Team Charter

**Fleet:** AI-Office Trading Research Fleet  
**Version:** 1.0  
**Status:** Active — PAPER/TESTNET ONLY  
**Live orders:** `live_orders_allowed = false` (hard rule, never changes)

---

## 1. Mission

The fleet conducts paper trading research: edge discovery, backtest validation, cost modeling, risk analysis, and strategy validation. Gross edge is not profit. Every claim must state venue, fee, funding, and horizon. A horizon is viable only when its confidence interval excludes zero AND it clears modelled costs. Never lower a sample floor to get a verdict.

**This fleet does not place live orders. It never will.**

---

## 2. Team Structure — 7 Departments, 32 Agents

| Department | Agents | Role |
|---|---|---|
| **Quant Research** | quant-research-manager, quant-researcher, signal-analyst | Discover and validate trading edges |
| **Backtest Validation** | backtest-auditor, quant-model-validator, event-driven-researcher | Audit for look-ahead bias, leakage, survivorship |
| **Risk Management** | risk-manager, risk-control-verifier, drawdown-analyst | Enforce position sizing, drawdown limits, kill switch |
| **Execution** | execution-strategist, execution-analyst, cost-analyst | Model fees, slippage, funding; cost-sensitivity checks |
| **Portfolio Management** | portfolio-manager, portfolio-allocation-researcher, exposure-analyst | Allocation, correlated exposure, diversification |
| **Market Making** | market-maker, liquidity-researcher, order-book-researcher | Spread capture, liquidity depth, inventory risk (simulation) |
| **Compliance** | compliance-checker, trade-journal-reviewer, research-archivist | Guard PAPER-only boundary, verify kill switch LOCKED |

**Tiers:**
- **Pro (25 agents):** Heavy models (nemotron-3-ultra, mistral-large-4) — complex reasoning, validation, risk decisions
- **Lite (7 agents):** Light models (nemotron-3.5-lightning, nano-omni) — data monitoring, archival, journal review

---

## 3. Ground Rules (Non-Negotiable)

| Rule | Enforcement |
|---|---|
| **PAPER/TESTNET only** | `live_orders_allowed = false` |
| **No order path ever** | `forbidden_path_patterns` blocks `order`/`executor` |
| **Kill switch LOCKED** | Checked every cycle by compliance-checker |
| **Gross edge ≠ profit** | Every claim states venue, fee, funding, horizon |
| **CI excludes zero** | Horizon viable only when CI excludes zero AND clears costs |
| **Never lower sample floor** | ≥10 closed exits (target 20–30) before any verdict |
| **No fabrication** | If data isn't available, state that explicitly |
| **Read-only research** | Output to `research/` only, never to broker/executor |

---

## 4. Decision-Making Framework

### Synthesis Cycle (Fan-In → Fan-Out)

Every planning cycle runs all 32 agents in parallel (10 processes × 20 threads), then synthesizes findings:

1. **Fan-out:** Each agent receives a state bundle (real ground-truth files) and executes its specific audit task
2. **Verdict gate:** Deterministic checks verify form + ground-truth facts (kill switch LOCKED, risk limits referenced, etc.)
3. **Findings store:** Passed findings are persisted with dedup by agent+claim
4. **Synthesis agent:** Reads all findings, produces fleet-level verdict (ALL-CLEAR / CAUTION / PARTIAL / NO-FINDINGS) with confidence

### Verdict Definitions

| Verdict | Meaning | Action |
|---|---|---|
| **ALL-CLEAR** | All findings supported, no risks | Continue monitoring |
| **CAUTION** | Some findings need-review or refuted | Investigate risk agents |
| **PARTIAL** | Some supported, some missing | Fill gaps, re-audit |
| **NO-FINDINGS** | No valid findings produced | Debug agent prompts/sources |

---

## 5. State Bundles (Ground Truth)

Each agent receives a bundle of real files before executing:

| Agent | State Files |
|---|---|
| compliance-checker | kill_switch_status.json, office.json |
| risk-control-verifier | kill_switch_status.json, risk_framework.md, control_results.json |
| drawdown-analyst | audit.log, cross_venue_arb_reality.json |
| quant-model-validator | cross_venue_arb_reality.json, execution_assumptions.json |
| backtest-auditor | cross_venue_arb_reality.json, calibration_report.json |
| cost-analyst | execution_assumptions.json, ACCOUNTING_AUDIT.md |
| performance-attribution | cross_venue_arb_reality.json, ACCOUNTING_AUDIT.md |
| trade-journal-reviewer | audit.log, control_results.json |
| research-archivist | research/ directory listing |
| data-feed-monitor | data_sources.json |
| market-data-analyst | data_sources.json |
| position-sizing-analyst | risk_framework.md |
| exposure-analyst | risk_framework.md |
| portfolio-allocation-researcher | risk_framework.md |
| market-maker | cross_venue_arb_reality.json |
| liquidity-researcher | cross_venue_arb_reality.json |
| order-book-researcher | cross_venue_arb_reality.json |
| market-regime-analyst | cross_venue_arb_reality.json, risk_framework.md |
| correlation-researcher | cross_venue_arb_reality.json |
| signal-analyst | control_results.json, cross_venue_arb_reality.json |
| event-driven-researcher | control_results.json, cross_venue_arb_reality.json |

Agents without mapped state bundles use the plan-then-exec path (generate task → execute).

---

## 6. Cache Gate & Stampede Protection

| Mechanism | Purpose | Threshold |
|---|---|---|
| **Cache gate** | Skip re-auditing when source files unchanged | 5-minute TTL + mtime check |
| **Stampede protection** | Prevent duplicate concurrent analysis per agent | 5-minute lock |
| **Skip window** | Don't re-plan agents done recently | 15 minutes |

---

## 7. Compliance Verification (Every Cycle)

The compliance-checker deterministically verifies:

1. **Kill switch verdict = LOCKED**
2. **`live_orders_allowed = false`** in office config autonomy block
3. **`forbidden_path_patterns` blocks `order`/`executor` paths**

If any check fails, the issue is appended to the agent's output and logged. The fleet does not proceed with live-order-adjacent work under any circumstances.

---

## 8. Track Record (Outcome Tracking)

Every finding is stored with:
- Agent, claim, evidence reference, verdict, date
- Optional outcome (right/wrong/inconclusive) added later
- Hit rate calculated over decided findings

Findings that remain `pending` beyond 30 days are flagged as stale.

---

## 9. Escalation Paths

| Issue | Escalate To | Method |
|---|---|---|
| Kill switch not LOCKED | Compliance department | Immediate, halt all cycles |
| `executor_enabled = true` | Compliance department | Immediate, fix config |
| OpenRouter/Google daily cap | Execution department | Wait for reset (~08:00 UTC), NVIDIA keys carry load |
| Agent produces fabrication | Compliance + backtest | Re-audit, remove finding |
| CI includes zero on claimed edge | Quant research | Reject verdict, no-go |

---

## 10. What This Team Does NOT Do

- ❌ Place live orders
- ❌ Connect to live broker APIs
- ❌ Move real money
- ❌ Unlock the kill switch
- ❌ Set `live_orders_allowed = true`
- ❌ Fabricate data or results

---

## 11. Fleet Health (Current)

| Metric | Value |
|---|---|
| Agents | 32 (25 pro, 7 lite) |
| Departments | 7 |
| Worker processes | 10 (all CPU cores) |
| Threads per process | 20 |
| Findings stored | 168+ |
| Synthesis verdict | ALL-CLEAR |
| Kill switch | LOCKED |
| `live_orders_allowed` | false |

---

**This charter is the team's operating system. Changes require updating this document and re-validating all compliance checks.**
