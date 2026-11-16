# Profit Attribution & Optimization Features

## Overview
This summary describes the profit attribution and optimization features added to the alpha-system to enhance profit analysis, risk-adjusted returns, and capital allocation decisions.

## New Features Added

### 1. Profit Attribution Functions (`alpha/validation/metrics.py`)

#### `calculate_profit_attribution_by_factor`
- **Purpose**: Decompose portfolio returns by individual factors using Brinson-style attribution
- **Inputs**: 
  - `factor_returns`: DataFrame of factor returns (periods x factors)
  - `factor_weights`: DataFrame of factor weights (periods x factors)
  - `periods_per_year`: Int (default 252 for daily data)
- **Output**: DataFrame with columns [factor, total_return, attribution, contribution_pct]
- **Use Case**: Identify which factors (momentum, value, quality, etc.) are driving performance

#### `calculate_profit_attribution_by_regime`
- **Purpose**: Attribute returns to different market regimes (trend up, trend down, chop, etc.)
- **Inputs**:
  - `returns`: Series of period returns
  - `regimes`: Series of regime labels matching returns index
  - `periods_per_year`: Int (default 252)
- **Output**: DataFrame with columns [regime, total_return, annualized_return, contribution_pct]
- **Use Case**: Understand performance in different market environments

#### `calculate_profit_attribution_by_model`
- **Purpose**: Attribute returns to different predictive models
- **Inputs**:
  - `model_predictions`: Dict of model_name → predictions Series
  - `actual_returns`: Series of actual forward returns
  - `model_weights`: Dict of model_name → weight
  - `periods_per_year`: Int (default 252)
- **Output**: DataFrame with columns [model, weight, ic, attribution, contribution_pct]
- **Use Case**: Evaluate model performance and inform ensemble weighting

#### `calculate_factor_half_life`
- **Purpose**: Estimate how long a factor's edge persists before decaying to half
- **Inputs**:
  - `factor_returns`: Series of factor returns over time
  - `periods_per_year`: Int (default 252)
- **Output**: Float (half-life in periods)
- **Use Case**: Monitor factor decay and timely strategy retirement

#### `calculate_regime_transition_probability`
- **Purpose**: Calculate Markov transition probabilities between market regimes
- **Inputs**:
  - `regime_history`: Series of historical regime labels
- **Output**: DataFrame (transition probability matrix)
- **Use Case**: Improve regime detection models and expected holding period calculations

### 2. Integration with Existing Architecture

#### Kelly Sizing (Already Implemented)
- The `DecisionBrain._calculate_position_size()` method already uses Kelly estimates from `LearningBrain`
- Kelly estimates are updated based on trade outcomes and persisted to state store
- Position sizing incorporates:
  - Kelly fraction per regime
  - Signal strength adjustment
  - Regime scalars
  - Volatility targeting (inverse vol)
  - Survival state adjustments (reduce size after losses)
  - Maximum position limits
  - Kelly caps

#### State Persistence
- `StateStore` already persists:
  - Model weights (`save_model_weights`/`load_model_weights`)
  - Kelly estimates (`save_kelly_estimates`/`load_kelly_estimates`) 
  - Graveyard entries (disabled patterns)
  - Survival state (daily/weekly P&L and drawdown)

## Usage Examples

See `/Users/aryanagarwal/alpha-system/examples/profit_attribution_demo.py` for a complete walkthrough.

### Basic Usage:
```python
from alpha.validation.metrics import *

# Factor attribution
attribution = calculate_profit_attribution_by_factor(factor_returns, factor_weights)

# Regime attribution  
regime_attrib = calculate_profit_attribution_by_regime(returns, regimes)

# Model attribution
model_attrib = calculate_profit_attribution_by_model(model_preds, actual_returns, model_weights)

# Factor decay monitoring
half_life = calculate_factor_half_life(factor_returns['momentum'])

# Regime transitions
transition_matrix = calculate_regime_transition_probability(regime_history)
```

## Benefits

1. **Enhanced Transparency**: Clearly see what's driving performance (factors, regimes, models)
2. **Better Decision Making**: Allocate capital to highest-contributing factors/models
3. **Risk Management**: Identify decaying factors before they hurt performance
4. **Regime Awareness**: Understand performance in different market environments
5. **Model Accountability**: Quantify each model's contribution to ensemble performance
6. **Timely Interventions**: Detect regime changes and factor decay early

## Integration Points

1. **Notebooks**: Add attribution analysis to alpha model demo notebook
2. **Live Trading**: Run attribution analysis daily/weekly to inform rebalancing
3. **Research**: Use in strategy development to isolate factor/model performance
4. **Reporting**: Include in performance reports to stakeholders
5. **Optimization**: Feed attribution results into capital allocation algorithms

## Future Enhancements

1. **Transaction Cost Attribution**: Separate alpha from trading costs
2. **Tax-Aware Attribution**: Especially important for crypto (30% flat + 1% TDS in India)
3. **Time-Varying Attribution**: Rolling window attribution to see evolution
4. **Monte Carlo Attribution**: Simulate attribution uncertainty
5. **Factor Timing vs Selection**: Deeper Brinson-style attribution
