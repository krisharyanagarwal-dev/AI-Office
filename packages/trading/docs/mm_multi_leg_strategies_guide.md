
# PROFESSIONAL MARKET MAKER MULTI-LEG OPTIONS STRATEGIES
## Comprehensive Educational Reference
### Version: Professional Standards | Risk-First Approach

---

## TABLE OF CONTENTS
1. Core Philosophy & Risk Framework
2. The Greeks in Multi-Leg Context
3. Directional Spreads
4. Neutral/Income Strategies
5. Volatility Strategies
6. Advanced Compound Structures
7. Portfolio Greeks Management
8. Execution & Liquidity Framework
9. Risk Management Rules
10. Quick Reference Cards

---

## 1. CORE PHILOSOPHY & RISK FRAMEWORK

### Market Maker Mindset
- **Edge > Direction**: MMs profit from bid-ask spread capture, theta decay, and vol risk premium — NOT directional bets
- **Defined Risk**: Every position has max loss defined at inception
- **Greeks Neutral Target**: Delta, Gamma, Vega, Theta managed to target ranges
- **Liquidity First**: Only trade where you can exit at reasonable cost
- **Size to Survive**: Position sizing based on max drawdown tolerance, not conviction

### Risk Budget Framework
```
Daily Risk Budget = Portfolio Value × Daily VaR Limit (typically 1-2%)
Per-Trade Risk    = Daily Risk Budget ÷ Max Concurrent Trades (typically 5-10)
Position Size     = Per-Trade Risk ÷ Max Loss Per Contract
```

### Greeks Target Bands (Typical MM)
| Greek | Target Range | Action Trigger |
|-------|-------------|----------------|
| Delta | ±10% of Notional | Re-hedge at ±15% |
| Gamma | < 5% of Notional/1% spot | Reduce at > 7% |
| Vega  | ±5% of Notional/1% vol | Hedge at ±8% |
| Theta | Positive daily (collect) | Review if negative > 2 days |

---

## 2. THE GREEKS IN MULTI-LEG CONTEXT

### Delta (Δ) - Directional Sensitivity
```
Net Δ = Σ(Δᵢ × Quantityᵢ × 100)
```
**Key Insight**: In spreads, delta offset between legs reduces net exposure. Long vertical spread delta = Δ_long - Δ_short ≈ 0.3-0.5 typically.

### Gamma (Γ) - Delta Acceleration
```
Net Γ = Σ(Γᵢ × Quantityᵢ × 100)
```
**Critical for MMs**: Gamma peaks ATM. Short gamma = risk of delta moving against you rapidly. Always know your gamma exposure near strikes.

### Vega (ν) - Volatility Sensitivity
```
Net ν = Σ(νᵢ × Quantityᵢ × 100)
```
**Long Vega** = Long options net (benefit from IV rise)
**Short Vega** = Short options net (benefit from IV crush)

### Theta (Θ) - Time Decay
```
Net Θ = Σ(Θᵢ × Quantityᵢ × 100)
```
**MM Edge**: Net positive theta is the "rent" collected. Target Θ/vega ratio > 0.05 for income strategies.

### Higher-Order Greeks (When They Matter)
- **Vanna** (Δ/σ): Delta change per vol change — critical for skew trading
- **Vomma** (ν/σ): Vega convexity — matters for tail risk
- **Charm** (Δ/τ): Delta decay — important for overnight/weekend risk

---

## 3. DIRECTIONAL SPREADS

### 3.1 Bull Call Spread (Debit Spread)
```
Structure: Long Call K₁ + Short Call K₂ (K₁ < K₂)
Bias: Moderately Bullish
Max Profit: (K₂ - K₁) - Net Debit
Max Loss: Net Debit Paid
Breakeven: K₁ + Net Debit
```

| Parameter | Typical MM Settings |
|-----------|-------------------|
| Width | 5-10 pts (equity), 25-50 bps (rates) |
| DTE | 30-45 days |
| Delta Long | 0.55-0.65 |
| Delta Short | 0.25-0.35 |
| Net Delta | 0.25-0.35 |
| Target Return | 1.5-2.5× Risk |

**Greeks Profile**: +Δ, -Γ, -ν, +Θ (after midpoint)
**When to Use**: High IV percentile, defined risk bullish view
**MM Twist**: Sell the spread when IV percentile > 70 (collect premium), buy when IV percentile < 30

### 3.2 Bear Put Spread (Debit Spread)
```
Structure: Long Put K₁ + Short Put K₂ (K₁ > K₂)
Bias: Moderately Bearish
Max Profit: (K₁ - K₂) - Net Debit
Max Loss: Net Debit Paid
Breakeven: K₁ - Net Debit
```

**Skew Advantage**: In equity, put skew makes bear put spreads cheaper than bull call spreads for equivalent delta.

### 3.3 Bull Put Spread / Credit Put Spread
```
Structure: Short Put K₁ + Long Put K₂ (K₁ > K₂)
Bias: Neutral-to-Bullish (collect premium)
Max Profit: Net Credit Received
Max Loss: (K₁ - K₂) - Net Credit
Breakeven: K₁ - Net Credit
```

| Parameter | Typical MM Settings |
|-----------|-------------------|
| Width | 5-10 pts |
| DTE | 14-30 days (theta acceleration) |
| Short Delta | 0.15-0.25 (OTM) |
| Long Delta | 0.05-0.10 |
| Probability of Profit | 65-75% |
| Target Return | 15-25% on margin |

**Greeks Profile**: +Δ (small), -Γ (small), -ν, +Θ (strong)
**Key Risk**: Gamma blowup if underlying approaches short strike
**Management**: Roll/defend at 0.30 delta or 2× credit received

### 3.4 Bear Call Spread / Credit Call Spread
```
Structure: Short Call K₁ + Long Call K₂ (K₁ < K₂)
Bias: Neutral-to-Bearish
```
Mirror of bull put spread — same mechanics, opposite direction.

---

## 4. NEUTRAL / INCOME STRATEGIES

### 4.1 Iron Condor (The MM Staple)
```
Structure: 
  Short Put K₁ + Long Put K₂  (Put Credit Spread)
  Short Call K₃ + Long Call K₄ (Call Credit Spread)
  Where: K₂ < K₁ < Spot < K₃ < K₄
```

| Parameter | Typical MM Settings |
|-----------|-------------------|
| Put Spread Width | 5-10 pts |
| Call Spread Width | 5-10 pts |
| Wing Distance | 1.0-1.5 SD from spot |
| DTE | 21-45 days |
| Short Put Delta | 0.10-0.15 |
| Short Call Delta | 0.10-0.15 |
| Target Credit | 30-50% of width |
| POP | 70-85% |

**Greeks Profile**: ~Δ-neutral, -Γ, -ν, +Θ
**Profit Zone**: Between short strikes
**Max Loss**: Width - Credit (one side only at expiration)

**MM Enhancements**:
1. **Asymmetric Wings**: Wider wing on put side (skew premium)
2. **Delta-Weighted**: Adjust strikes so |Δ_put| ≈ |Δ_call|
3. **Rolling Ladder**: Layer 3-4 condors at different DTEs (7, 21, 35, 45)

**Defense Rules**:
- Test Level: Underlying touches short strike → roll untested side
- 2× Credit: Loss = 2× credit received → close entire position
- 21 DTE: Close regardless (gamma risk acceleration)

### 4.2 Butterfly Spread
```
Structure (Long Butterfly):
  Long Call K₁ + Short 2×Call K₂ + Long Call K₃
  Where: K₁ < K₂ < K₃, K₂ - K₁ = K₃ - K₂ (equidistant)
  
Variations:
- Call Butterfly (bullish bias if K₂ > spot)
- Put Butterfly (bearish bias if K₂ < spot)
- Iron Butterfly: Short Straddle + Long Wings (credit structure)
```

| Parameter | Long Butterfly | Iron Butterfly |
|-----------|----------------|----------------|
| Max Profit | K₂ - K₁ - Debit | Credit Received |
| Max Loss | Debit Paid | Wing Width - Credit |
| Best For | Pin risk at K₂ | High IV, expect pin |
| Delta | ~0 at K₂ | ~0 at K₂ |
| Gamma | High at K₂ | High at K₂ |
| Theta | + (near K₂) | + (near K₂) |
| Vega | - | - |

**MM Use Case**: 
- Long butterfly: Cheap lottery ticket for pin risk (earnings, Fed days)
- Iron butterfly: Sell when IV > realized vol + 3-5 vol points

### 4.3 Calendar / Time Spread
```
Structure: Short Near-term Option + Long Further-term Option (Same Strike)
Variations:
- Call Calendar (neutral/slightly bullish)
- Put Calendar (neutral/slightly bearish)
- Double Calendar: Put + Call at different strikes
```

| Parameter | Settings |
|-----------|----------|
| Strike | ATM or slightly OTM |
| Front Month | 7-21 DTE |
| Back Month | 35-60 DTE |
| Vega Exposure | Positive (long back month) |
| Theta | + (front decays faster) |

**Key Insight**: Profit from term structure (front IV > back IV) and theta differential.
**Risk**: Vega loss if IV collapses, gamma risk near strike in front month.

### 4.4 Diagonal Spread
```
Structure: Short Near-term OTM Option + Long Further-term ATM/ITM Option
Combines: Vertical (strike diff) + Calendar (time diff)
```

**MM Favorite**: Poor man's covered call / PMCC
- Long 60-90 DTE ITM Call (Δ 0.70-0.80)
- Short 14-30 DTE OTM Call (Δ 0.20-0.30)
- Roll short leg monthly, collect theta
- Delta-neutral-ish, positive theta, long vega

---

## 5. VOLATILITY STRATEGIES

### 5.1 Long Straddle
```
Structure: Long Call ATM + Long Put ATM (Same Strike, Same Expiry)
Bias: Large Move Expected (Direction Unknown)
Max Profit: Unlimited
Max Loss: Total Premium Paid
Breakevens: K ± Total Premium
```

| Parameter | Settings |
|-----------|----------|
| Strike | ATM |
| DTE | 30-60 (avoid gamma/theta conflict) |
| Entry Signal | IV Rank < 25, Realized > Implied |
| Target | 2-3× Premium or 1 SD move |
| Stop | 50% premium loss |

**Greeks**: Δ≈0, +Γ (max ATM), +ν (max), -Θ (high)
**MM View**: Expensive — only buy when edge identified (earnings, FDA, macro events)

### 5.2 Short Straddle (MM Core Income)
```
Structure: Short Call ATM + Short Put ATM
Bias: Range-bound, IV > Realized
Max Profit: Premium Collected
Max Loss: Unlimited (theoretically)
Breakevens: K ± Premium
```

**MM Reality Check**: NEVER naked short straddle. ALWAYS hedge:
- Delta hedge underlying
- Buy wings (→ Iron Butterfly)
- Or: Short Straddle + Long Strangle (Iron Condor)

### 5.3 Long Strangle
```
Structure: Long Call OTM + Long Put OTM (Different Strikes)
Bias: Large Move, Cheaper than Straddle
Strikes: Typically 1 SD OTM each side
```

**Advantage**: Lower cost, wider breakevens
**Disadvantage**: Need bigger move, more theta decay

### 5.4 Short Strangle (with Wings = Iron Condor)
```
The professional way to sell strangles: ALWAYS define risk with wings.
```

### 5.5 Ratio Spreads (Volatility Arbitrage)
```
Call Ratio Spread (Bearish Vol):
  Long 1× Call K₁ + Short 2× Call K₂ (K₂ > K₁)
  Net Credit or Small Debit
  Max Profit at K₂
  Unlimited Risk above K₂ + (K₂-K₁)

Put Ratio Spread (Bullish Vol):
  Long 1× Put K₁ + Short 2× Put K₂ (K₂ < K₁)
```

**MM Use**: Sell elevated skew — when OTM puts have rich IV vs ATM.
**Risk**: Tail risk — always buy back extra short or hedge with futures.

### 5.6 Volatility Swaps / Variance Swaps (Institutional)
```
Not exchange-traded typically. OTC.
Pay fixed vol strike, receive realized variance.
MMs delta-hedge daily to isolate vol exposure.
```

---

## 6. ADVANCED COMPOUND STRUCTURES

### 6.1 Jade Lizard / Twisted Sister
```
Jade Lizard (Bullish):
  Short Put K₁ + Short Call Spread (K₂/K₃)
  Where K₁ < Spot < K₂ < K₃
  No upside risk (call spread caps it)
  Downside risk: Put side only
  Collects premium from both sides
  
Twisted Sister (Bearish):
  Short Call K₁ + Short Put Spread (K₂/K₃)
  Mirror of Jade Lizard
```

**Why MMs Love It**: Collects 2× premium, eliminates one tail risk.

### 6.2 Broken Wing Butterfly (BWB)
```
Structure: Long Call K₁ + Short 2×Call K₂ + Long Call K₃
Where: K₃ - K₂ > K₂ - K₁ (wider top wing)
Can be done for CREDIT (unlike standard butterfly)

Bullish BWB: Credit received, max profit if pin K₂, risk only below K₁
Bearish BWB: Mirror with puts
```

**Key**: Asymmetric wings = credit possible + directional bias + defined risk.

### 6.3 Condor vs. Iron Condor vs. Butterfly vs. Iron Butterfly

| Structure | Credit/Debit | Risk | Reward | Best IV Env |
|-----------|--------------|------|--------|-------------|
| Iron Condor | Credit | Defined | Limited | High IV |
| Long Condor | Debit | Defined | Limited | Low IV |
| Iron Butterfly | Credit | Defined | Limited | Very High IV |
| Long Butterfly | Debit | Defined | High (if pin) | Any (cheap) |
| BWB | Credit | Defined (1 side) | High | High IV + Direction |

### 6.4 Box Spread / Jelly Roll (Interest Rate Play)
```
Box = Bull Call Spread + Bear Put Spread (Same Strikes)
    = Synthetic Long + Synthetic Short = Risk-free bond
    
Jelly Roll = Call Time Spread + Put Time Spread (Same Strikes)
           = Forward rate play
```

**MM Use**: Cash management, interest rate arbitrage, borrowing/lending synthetic.

### 6.5 Conversion / Reversal (Dividend/Interest Arbitrage)
```
Conversion: Long Stock + Long Put + Short Call (Same Strike)
           = Synthetic Long Bond (earn interest)
Reversal: Short Stock + Long Call + Short Put
         = Synthetic Short Bond (pay interest)
```

**MM Use**: Capture dividend + interest rate differential.

---

## 7. PORTFOLIO GREEKS MANAGEMENT

### 7.1 Greek Aggregation Framework
```python
# Conceptual portfolio Greeks
portfolio = {
    'delta': sum(pos.delta * pos.qty * 100 for pos in positions),
    'gamma': sum(pos.gamma * pos.qty * 100 for pos in positions),
    'vega':  sum(pos.vega  * pos.qty * 100 for pos in positions),
    'theta': sum(pos.theta * pos.qty * 100 for pos in positions),
    'vanna': sum(pos.vanna * pos.qty * 100 for pos in positions),
    'charm': sum(pos.charm * pos.qty * 100 for pos in positions),
}
```

### 7.2 Delta Hedging Protocol
```
1. Calculate net portfolio delta every 15 min (or real-time)
2. Hedge threshold: |Δ| > 10% of notional or > 500 delta
3. Hedge instrument: Futures (preferred) or ATM options
4. Hedge ratio: 1.0 for futures, adjust for option delta
5. Rebalance: End of day flat, or carry small overnight delta (< 2%)
```

### 7.3 Gamma Scalping (Long Gamma Portfolio)
```
When net Γ > 0:
- Delta hedge frequently (every 0.5-1% spot move)
- Profit from realized vol > implied vol paid
- Cost: Theta bleed
- Target: Realized vol > Entry IV + 2-3 pts

When net Γ < 0:
- Delta hedge infrequently (let delta run)
- Risk: Gap moves
- Benefit: Theta collection
- Must have: Defined risk structures, stop losses
```

### 7.4 Vega Management
```
Net Vega Target: ±$5k-$20k per 1% IV change (per $1M notional)

If Net Vega > Target:
  - Sell straddles/strangles
  - Buy calendar spreads (short near-term vega)
  - Reduce long option positions

If Net Vega < -Target:
  - Buy straddles/strangles  
  - Sell calendar spreads
  - Add long option positions

Skew Management:
  - Track 25Δ put IV vs 25Δ call IV
  - Adjust put/call ratio in condors
  - Use risk reversals for directional skew bets
```

### 7.5 Term Structure Management
```
Track IV by tenor: 7d, 14d, 30d, 60d, 90d
- Contango (front < back): Sell calendars, buy backspreads
- Backwardation (front > back): Buy calendars, sell backspreads
- Earnings/Fed in front month: Expect elevated front IV
```

---

## 8. EXECUTION & LIQUIDITY FRAMEWORK

### 8.1 Order Types & Routing
| Order Type | Use Case |
|------------|----------|
| Limit | Default for all legs |
| Spread Order (Complex) | Multi-leg atomic execution |
| Auction (CUBE, AIM, SAM) | Large size, price improvement |
| Sweep | Urgent, take liquidity across venues |
| Pegged | Market making, quote management |

### 8.2 Slippage Budget (Per Leg)
| Liquidity Tier | Max Slippage | Max Size |
|----------------|--------------|----------|
| SPY/SPX/QQQ ATM | 1-2¢ | 500+ |
| Liquid Single Stock | 2-5¢ | 100-200 |
| Semi-Liquid | 5-10¢ | 20-50 |
| Illiquid | 10-20¢ | <10 |

### 8.3 Legging Risk Management
```
NEVER leg into spreads manually unless:
- Size < 10 contracts
- Market very liquid
- You have millisecond advantage

ALWAYS use:
- Complex order book (CBOE, BOX, MIAX)
- Broker spread algorithms
- Multi-leg tickets
```

### 8.4 Venue Selection
| Product | Primary Venues |
|---------|----------------|
| Equity Options | CBOE, BOX, MIAX, NYSE Arca, NASDAQ PHLX |
| Index Options (SPX) | CBOE (primary), C2 |
| ETF Options | CBOE, MIAX, BOX |
| Futures Options | CME, ICE |
| Crypto Options | Deribit (primary), CME |

---

## 9. RISK MANAGEMENT RULES

### 9.1 Position-Level Rules
```
✓ Max loss per position defined at entry
✓ Stop loss at 2× credit received (credit spreads)
✓ Stop loss at 50% debit paid (debit spreads)
✓ Close at 21 DTE (gamma acceleration)
✓ Close at 0.30 delta on short strike (defense)
✓ Roll untested side when tested (iron condors)
✓ Never add to losing position (no averaging down)
```

### 9.2 Portfolio-Level Rules
```
✓ Daily P&L stop: -2% portfolio value
✓ Weekly P&L stop: -4% portfolio value  
✓ Monthly P&L stop: -6% portfolio value
✓ Max concurrent positions: 10-15
✓ Max delta exposure: ±10% notional
✓ Max vega exposure: ±$20k per 1% IV
✓ Max gamma exposure: < 5% notional per 1% spot
✓ Concentration limit: < 20% in single underlying
✓ Sector limit: < 30% in single sector
```

### 9.3 Tail Risk Protocols
```
VIX > 30: Reduce size 50%, widen strikes, avoid short gamma
VIX > 40: Reduce size 75%, only long premium / defined risk
VIX > 50: Hedge portfolio with long VIX calls / futures
Market Gap Risk: Overnight delta < 2% notional
Earnings/Fed: No undefined risk positions 24h before
```

### 9.4 Capital Allocation
```
Tier 1 (Core, 60%): Iron Condors, Credit Spreads, Butterflies
  - High POP, defined risk, consistent theta
  
Tier 2 (Tactical, 30%): Diagonals, Calendars, Ratio Spreads
  - Directional bias + vol view, moderate risk

Tier 3 (Speculative, 10%): Long Straddles/Strangles, Wings
  - Event-driven, high risk/reward, small size
```

---

## 10. QUICK REFERENCE CARDS

### Card A: Iron Condor Checklist
```
[ ] IV Rank > 50% (preferably > 70%)
[ ] 21-45 DTE
[ ] Short strikes at 0.10-0.15 delta
[ ] Wings 5-10 pts wide
[ ] Credit ≥ 30% of wing width
[ ] Asymmetric: put wing 1-2 pts wider
[ ] POP > 70% (Delta-based)
[ ] Margin requirement checked
[ ] Earnings/Fed dates checked (avoid)
[ ] Exit plan: 2× credit, 21 DTE, test level
```

### Card B: Vertical Spread Checklist
```
[ ] Directional conviction (technical/fundamental)
[ ] IV Rank context (buy low IV, sell high IV)
[ ] Width = 1.5-2× expected move
[ ] DTE 30-45 (debit) / 14-30 (credit)
[ ] Risk/Reward ≥ 1.5:1
[ ] Delta long 0.55-0.65 / short 0.25-0.35
[ ] Breakeven beyond key support/resistance
[ ] Liquidity: OI > 500, spread < 5¢
```

### Card C: Butterfly Checklist
```
[ ] Target: Pin risk at center strike
[ ] Event: Earnings, Fed, Expiration
[ ] Cost: < 15% of max value (long fly)
[ ] Credit: > 20% of width (iron fly)
[ ] DTE: 7-21 (pin risk highest near expiry)
[ ] Gamma risk accepted (high near center)
[ ] Size: Small (lottery ticket sizing)
```

### Card D: Diagonal / PMCC Checklist
```
[ ] Long: 60-90 DTE, ITM (Δ 0.70-0.80)
[ ] Short: 14-30 DTE, OTM (Δ 0.20-0.30)
[ ] Strike diff: ~1.5-2× expected monthly move
[ ] Extrinsic in long ≥ short premium (protection)
[ ] Roll short at 50% profit or 7 DTE
[ ] Manage early assignment risk (dividends)
[ ] Track: Net theta, net delta, net vega
```

### Card E: Greek Limits Quick Reference
```
PORTFOLIO LIMITS (per $100k notional):
├── Delta:      ±$10k (10%)
├── Gamma:      < $5k per 1% spot move
├── Vega:       ±$5k per 1% IV change
├── Theta:      Target +$50 to +$200/day
├── Vanna:      Monitor (skew exposure)
├── Charm:      Monitor (weekend decay)

PER TRADE LIMITS:
├── Max Loss:   1-2% portfolio
├── Max Delta:  200-500 per position
├── Max Vega:   $2k per 1% IV
├── Max Gamma:  $1k per 1% spot
```

---

## APPENDIX: COMMON MM ADJUSTMENTS

### Adjustment 1: Iron Condor - Tested Side
```
If put side tested (spot → short put):
1. Roll put spread DOWN (same width, lower strikes)
2. Collect additional credit
3. Keep call spread intact
4. New credit reduces overall breakeven
```

### Adjustment 2: Credit Spread - Challenged
```
If short strike approached (Δ > 0.30):
Option A: Roll entire spread out in time (same strikes, later expiry)
Option B: Roll spread further OTM (wider, more credit)
Option C: Close at 2× credit loss
Option D: Convert to iron condor (add other wing)
```

### Adjustment 3: Calendar - Front Month ITM
```
If front month goes ITM:
1. Roll front to next expiry (same strike)
2. Or: Close front, keep back (→ long option)
3. Or: Convert to diagonal (roll front to different strike)
```

### Adjustment 4: Butterfly - Missed Pin
```
If price moves away from center:
1. Close for remaining value (salvage)
2. Roll to new center strike (new butterfly)
3. Convert to condor (add wings)
```

---

## DISCLAIMER
This guide is for EDUCATIONAL PURPOSES ONLY.
Options trading involves substantial risk of loss.
Past performance does not guarantee future results.
Market making requires professional infrastructure, 
capital, and regulatory compliance.
Always consult qualified professionals before trading.

---

## VERSION HISTORY
v1.0 - Initial comprehensive guide
v1.1 - Added portfolio Greeks management
v1.2 - Added execution framework
v1.3 - Added risk management rules
v1.4 - Added quick reference cards

Last Updated: 2024
