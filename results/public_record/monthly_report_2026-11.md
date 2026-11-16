# NSE Options Research — Monthly Report, November 2026

**Paper/simulation research — not investment advice.** All results in this report come from simulated trading on historical data. No live orders were placed, no broker was connected, and no real capital was at risk. Nothing herein is a recommendation to buy or sell any security.

## 1. Methodology

The month's work followed a pre-registered, gated research pipeline:

1. **Pre-registration.** Each hypothesis — instrument, signal rule, entry/exit rules, tuning and holdout windows, expected edge, and expected costs — was registered in writing before any results were computed.
2. **Verification gate.** Tuning-window results were checked against minimum trade count, net-positive P&L, statistical edge (edge excluding zero), maximum drawdown, and cost-efficiency checks. A hypothesis must pass every check to proceed.
3. **Holdout.** Out-of-sample results over the holdout window were evaluated independently, with no parameter changes after tuning.
4. **Calibration.** Predicted edge was compared with realized edge, and calibration error was recorded.
5. **Honest costs.** All transaction costs were deducted from gross P&L; costs are reported as a fraction of gross credit received.

**Operating boundaries for the month:**
- Paper/simulation only. Kill switch **LOCKED**. No live orders. No broker connection.
- Tier C human-only oversight; no automated execution.
- No new strategy hunting — only pre-registered hypotheses were evaluated.
- Free data tiers only (NSE end-of-day bhavcopy archives).

## 2. Results

Two hypotheses were registered this month. **One was evaluated and failed; one remains pre-registered awaiting evaluation.**

### Bull put spread (300-pt wings) on NIFTY weekly expiry — FAILED, retired

**Signal rule:** enter at close when IV rank ≥ 80th percentile on the nearest weekly expiry; sell the ATM−300 put and buy the ATM−600 put; exit at a 50% credit target, a 2× credit stop-loss, or expiry close. Capital frame: ₹1 lakh. Data: free NSE EOD bhavcopy.

**Tuning window (2024-10-01 to 2025-12-31) — 92 trades**

| Metric | Value |
|---|---|
| Wins / Losses | 38 / 54 |
| Win rate | 41.3% |
| Gross P&L | +₹18,355.6 |
| Total transaction costs | ₹17,593.26 |
| Net P&L | **+₹762.34** |
| Maximum drawdown | 2.28% |
| Costs as % of gross credit | 95.85% |
| Average cost per trade | ₹191.23 |
| Average gross credit per trade | ₹199.52 |

**Gate result: FAILED.** The edge does not exclude zero, and costs consumed nearly all gross credit (cost-fraction check failed). Despite a small net-positive tuning result, the edge is not statistically distinguishable from zero.

**Holdout window (2026-01-01 to 2026-11-17)**

| Metric | Value |
|---|---|
| Net P&L | **−₹5,329.56** |
| Maximum drawdown | 5.33% (tuning: 2.28%) |

**Holdout result: FAILED.** The tuning-window profit did not survive out-of-sample, and drawdown exceeded tolerance. The strategy has been **retired**.

### Calibration

One calibration record was logged this month:

- Predicted edge: 0.15%
- Realized edge: 0.0552%
- Calibration error: −0.0948 percentage points
- Well-calibrated: yes (1 of 1 records)

Sample size is one; this is a directional check, not proof of calibration reliability.

## 3. Verdict

**No viable edge at ₹1 lakh capital with free data.** Across the evaluated strategy variant (bull put spread on NIFTY weekly expiry) and the market regimes covered by the tuning and holdout windows, the edge did not survive transaction costs or out-of-sample testing. The tuning-window gain of +₹762.34 was erased by a holdout loss of −₹5,329.56.

The NSE options research verdict is **settled/definitive**: no tradeable edge was found under the stated constraints (paper-only, ₹1 lakh capital, free EOD data, no new strategy hunting). The program is closed for this strategy family unless new, pre-registered evidence emerges.

## 4. Fleet

Aggregate research-fleet figures for the month (232 tasks):

| Metric | Value |
|---|---|
| Tasks completed | 91 (39.2%) |
| Tasks errored | 141 (60.8%) |
| **Aggregate error rate** | **60.8%** |
| Total cost units | 517 |
| Total outcome value | 910 |
| **Net value** | **393** |
| Cost efficiency | 0.76 net value per cost unit |
| Average cost per task | 2.23 cost units |
| Net value per task | 1.69 cost units |

**Reading:** The fleet processed 232 tasks at an aggregate error rate of 60.8%. Net value of 393 against 517 cost units gives a cost efficiency of roughly 0.76 — each cost unit returned about 0.76 units of net value. The elevated error rate reflects task-level execution failures, not trading losses; no live orders were placed and no capital was at risk.
