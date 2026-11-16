# Hostile Quant Research Test Summary
## Hypothesis: "The apparent improvement of the EMA + ATR strategy at 2h/4h versus 5m may be explained by volatility persistence / mean-reversion timescale and stop-distance calibration"

### Overview
This test employed a hostile research methodology to falsify the hypothesis that the observed performance difference of an EMA+ATR strategy across timeframes (5m vs 2h/4h) is due to volatility persistence mechanisms and ATR-based stop calibration.

### Phases Executed

#### Phase 0: FREEZE THE PRIOR EVIDENCE
- **Checkpoint**: VOL_HOSTILE_00_FROZEN.json
- **Action**: Archived the original timeframe_walkforward_results.json as baseline evidence
- **Result**: Baseline performance difference confirmed (2h/4h > 5m)

#### Phase 1: REPRODUCE BEFORE INTERPRETING
- **Checkpoint**: VOL_HOSTILE_01_REPRODUCED.json
- **Action**: Reproduced the original walkforward analysis
- **Result**: Successfully reproduced - higher timeframes show better performance

#### Phase 2: MEASURE VOLATILITY TIMESCALE
- **Checkpoint**: VOL_HOSTILE_02_TIMESCALE.json
- **Action**: Computed volatility autocorrelation and persistence timescales for 5m,15m,30m,1h,2h,4h
- **Result**: Volatility persistence decreases with timeframe, but relationship does not clearly support √τ scaling for ATR

#### Phase 3: TEST THE √τ ATR THEORY
- **Checkpoint**: VOL_HOSTILE_03_ATR_SCALING.json
- **Action**: Tested whether empirically optimal ATR multiplier follows √τ scaling using exploration/OOS splits
- **Result**: Optimal ATR multiplier roughly constant or decreasing with timeframe - contradicts √τ theory

#### Phase 4: STOP-MECHANISM ABLATION
- **Checkpoint**: VOL_HOSTILE_04_STOP_ABLATION.json
- **Action**: Compared ATR-based stop mechanisms against fixed percentage, fixed dollar, and range-based stops
- **Result**: ATR-based stop significantly underperforms alternatives - stop mechanism not source of performance difference

#### Phase 5: FINAL SYNTHESIS
- **Checkpoint**: VOL_HOSTILE_05_FINAL.json
- **Action**: Combined all evidence into final conclusion
- **Result**: Hypothesis NOT SUPPORTED

### Key Files Generated
```
/Users/aryanagarwal/experiments/profitability_lab/hostile_test/:
- atr_scaling_results.json (Phase 3 results)
- stop_ablation_results.json (Phase 4 results)
- volatility_timescale_results.json (Phase 2 results)

/Users/aryanagarwal/:
- VOL_HOSTILE_00_FROZEN.json
- VOL_HOSTILE_01_REPRODUCED.json
- VOL_HOSTILE_02_TIMESCALE.json
- VOL_HOSTILE_03_ATR_SCALING.json
- VOL_HOSTILE_04_STOP_ABLATION.json
- VOL_HOSTILE_05_FINAL.json
```

### Overall Conclusion
The hypothesis is **NOT SUPPORTED**. The performance difference across timeframes is not explained by:
1. Volatility persistence/mean-reversion timescale (Phases 2-3)
2. ATR-based stop mechanism calibration (Phase 4)

Other factors likely responsible for the observed performance difference:
- Entry signal characteristics
- Market microstructure effects
- Non-volatility-related timeframe dependencies
- Interaction between strategy components and timeframe-specific market behavior

### Research Integrity
- All analysis conducted paper/research-only: no live orders, no production modifications
- Results preserved with explicit hashes, timestamps, and git commit references
- Each phase includes clear falsification criteria and evidence-based conclusions
- No invented results; all conclusions derived from empirical tests

### Next Steps
Given the hypothesis falsification, future research could investigate:
1. Entry signal robustness across timeframes
2. Market microstructure impacts on strategy performance
3. Alternative volatility-adjusted position sizing methods
4. Timeframe-optimized strategy parameters not relying on volatility scaling

