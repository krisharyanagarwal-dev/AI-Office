# Next 100 Tasks Roadmap

*Generated after fundamentals pipeline completion*

---

## 1. Risk & Portfolio Management (10)

1. **Cross-asset correlation limits** — Add correlation-based position caps across BTC/ETH/SOL
2. **Dynamic Kelly sizing** — Implement full Kelly criterion with drawdown constraints
3. **Drawdown circuit breakers** — Daily/weekly max loss auto-reduce positions
4. **Margin health monitor** — Real-time margin usage across all paper books
5. **Stress test scenarios** — Historical scenario replay (2020 crash, 2022 bear, etc.)
6. **CVaR limits** — Conditional Value-at-Risk per book and aggregate
7. **Concentration limits** — Max single-asset / sector exposure
8. **Tail risk hedging** — Auto-buy puts when portfolio delta exceeds threshold
9. **Factor risk attribution** — Decompose P&L by momentum/value/carry/funding
10. **Risk budget allocation** — Allocate risk budget across strategies by Sharpe

---

## 2. Signal Quality & Alpha Research (15)

11. **Fundamentals regime detector** — Classify market by valuation/leverage/liquidity clusters
12. **Microstructure signals** — Add order flow imbalance, VPIN, Kyle lambda
12. **Funding rate carry signals** — Perpetual basis trading with term structure
13. **Options implied vol signals** — IV rank, term structure, skew
14. **On-chain metrics** — MVRV, SOPR, NUPL, exchange flows
15. **Macro regime filter** — DXY, rates, VIX, yield curve
16. **Cross-asset momentum** — ETH/BTC, SOL/ETH, altcoin rotation
17. **Mean reversion vs trend classifier** — Adaptive strategy selection
18. **Volume profile analysis** — VWAP bands, POC, VAH/VAL
19. **Order book toxicity** — Kyle lambda, VPIN, spread toxicity
20. **Whale tracking** — Large wallet alerts, exchange flows
21. **Sentiment integration** — Fear/greed, funding rate extremes
22. **Seasonality patterns** — Month-of-year, day-of-week, options expiry
23. **Event-driven signals** — Earnings, FOMC, halving, token unlocks
24. **Alternative data** — Google trends, GitHub stars, social volume
25. **Ensemble signal combiner** — Stack/blend multiple alphas

---

## 3. Execution & Trading Infrastructure (12)

26. **Smart order routing** — Venue selection by cost/latency/liquidity
27. **TWAP/VWAP execution algos** — Replace market orders for size
27. **Iceberg/stealth orders** — Hide size from order book
28. **Queue position estimation** — Predict fill probability
29. **Toxicity detection** — Avoid adverse selection
30. **Partial fill handling** — Smart child order management
30. **Latency monitoring** — P50/P99 per venue
31. **Fill quality metrics** — Slippage, market impact, timing
31. **Exchange failover** — Auto-switch on API errors
32. **Order lifecycle audit** — Full trace from signal to fill
32. **Paper → Live migration path** — Config-driven transition
33. **Multi-venue arbitrage** — Cross-exchange price discrepancies

---

## 4. Dashboard & Observability (10)

34. **Real-time P&L dashboard** — Per-strategy, per-symbol, aggregate
35. **Risk heatmap** — Correlation, concentration, VaR visual
36. **Signal attribution** — Which alpha drove each trade
37. **Fundamentals timeline** — Flag change history with P&L overlay
38. **Alert dashboard** — Fundamentals alerts with acknowledgment
39. **Strategy health cards** — Win rate, Sharpe, max DD, turnover
40. **Live order book viz** — Depth, spread, toxicity heatmap
41. **Correlation matrix** — Rolling 30/60/90 day
42. **Performance attribution** — Brinson sector/stock selection
43. **Mobile-friendly HUD** — Responsive for phone monitoring

---

## 4. AlphaInsider & Strategy Ops (10)

44. **Multi-strategy allocator** — Dynamic weight by recent Sharpe
45. **Strategy incubator** — A/B test new alphas with small capital
46. **Walk-forward optimization** — Rolling re-optimization schedule
47. **Parameter sensitivity** — Heatmap of Sharpe vs params
48. **Out-of-sample validation** — Purged K-fold cross-validation
49. **Strategy kill switch** — Auto-disable on drawdown/Sharpe breach
50. **Paper → Live graduation** — Checklist + capital ramp
51. **Strategy versioning** — Git-like branching for alphas
52. **Alpha decay monitor** — Track edge half-life
53. **Crowding detector** — Signal overlap with known factors

---

## 5. Infrastructure & DevOps (10)

54. **Launchd health monitor** — Auto-restart failed jobs
54. **Secrets rotation** — Automated key rotation with audit
55. **Containerization** — Dockerize all services for reproducibility
55. **CI/CD pipeline** — GitHub Actions for test/deploy
56. **Database migration** — Replace JSON files with TimescaleDB
55. **Metrics exporter** — Prometheus + Grafana
56. **Distributed tracing** — OpenTelemetry for latency debugging
56. **Log aggregation** — Loki/Grafana for log search
57. **Chaos engineering** — Failure injection for resilience
57. **Disaster recovery** — RTO/RPO documented + tested

---

## 5. Testing & Validation (8)

58. **Property-based testing** — Hypothesis for strategy invariants
58. **Adversarial testing** — Fuzzing signal generators
58. **Historical replay** — Tick-level backtest engine
58. **Shadow trading** — Run live signals on paper before live
59. **Adversarial market sim** — Adversarial order book scenarios
59. **Regime stress test** — Synthetic regime switches
59. **Performance regression** — Benchmark vs historical
60. **Data quality checks** — Gap detection, outlier flags

---

## 5. Data & Research Platform (8)

61. **Feature store** — Centralized factor library with versioning
61. **Data lineage** — Track source → transform → model
62. **Alternative data ingestion** — Satellite, credit card, shipping
62. **Data quality SLA** — Freshness, completeness, accuracy
63. **Research notebooks** — Versioned Jupyter with data access
63. **Model registry** — ML model versioning + A/B testing
64. **Feature importance** — SHAP values for ML models
64. **Data catalog** — Searchable metadata for all datasets

---

## 6. New Asset Classes & Markets (8)

65. **Equities (US/India)** — Expand beyond crypto
65. **Futures/Perpetuals** — Basis trading, calendar spreads
66. **Options** — Vol surface, gamma scalping, dispersion
66. **FX/Forwards** — Carry trades, basis
67. **Fixed income** — Yield curve, carry, roll-down
67. **Commodities** — Energy, metals, ags
67. **NFTs/Ordinals** — Floor price, rarity, liquidity
68. **RWA/Tokenized** — Treasury, real estate, credit

---

## 6. Governance & Compliance (5)

69. **Audit trail** — Immutable trade log with signatures
69. **Regulatory reporting** — MiCA, SEC, CFTC ready
70. **Conflict of interest** — Personal trading policy engine
70. **Insider trading guard** — MNPI detection
71. **Data privacy** — GDPR/CCPA compliance

---

## 7. Team & Knowledge (5)

72. **Runbook automation** — Incident response playbooks
72. **Onboarding docs** — New dev setup in <30 min
72. **Architecture decision records** — ADR log
72. **Post-mortem template** — Blameless post-mortems
73. **Knowledge base** — Searchable wiki with search

---

## 8. Quick Wins (5)

74. **Fundamentals CSV export** — Daily snapshot for Excel
74. **Slack/Discord alerts** — Rich embeds for critical alerts
74. **Keyboard shortcuts** — Power user HUD navigation
74. **Dark/light theme** — User preference
75. **Export API** — REST + WebSocket for external consumers

---

## Summary by Category

| Category | Tasks | Priority |
|----------|-------|----------|
| Risk & Portfolio | 10 | 🔴 Critical |
| Signal Quality | 15 | 🔴 Critical |
| Execution | 12 | 🟡 High |
| Dashboard | 10 | 🟡 High |
| Alpha Ops | 10 | 🟡 High |
| Infrastructure | 10 | 🟡 High |
| Testing | 8 | 🟢 Medium |
| Data Platform | 8 | 🟢 Medium |
| New Assets | 8 | 🔵 Low |
| Governance | 5 | 🔵 Low |
| Team | 5 | 🔵 Low |
| Quick Wins | 5 | 🟢 Medium |
| **Total** | **100** | |

---

## Suggested Next Sprint (Pick 3-5)

1. **Dynamic Kelly sizing** + **Drawdown circuit breakers** (Risk)
2. **Funding rate carry signals** + **Cross-asset momentum** (Alpha)
3. **TWAP execution** + **Slippage monitoring** (Execution)
4. **Real-time P&L dashboard** + **Alert dashboard** (Observability)
4. **Strategy incubator** + **Walk-forward optimization** (Alpha Ops)

---

*Last updated: 2026-11-21 | Fundamentals pipeline: ✅ Complete*