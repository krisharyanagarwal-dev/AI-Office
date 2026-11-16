# Alpha Trading System - Backtesting Framework

## Overview

The Alpha Trading System provides two complementary backtesting approaches:

1. **Vectorized Backtester** - High-performance, vectorized operations for rapid strategy evaluation
2. **Event-Driven Backtester** - Chronological, bar-by-bar simulation for realistic trade execution

## Vectorized Backtester

### Architecture
- Processes entire time series at once using vectorized pandas/numpy operations
- Extremely fast for strategy evaluation and parameter sweeps
- Ideal for research, optimization, and initial strategy validation

### Features
- Vectorized operations for speed (100x+ faster than iterative approaches)
- Multi-asset portfolio support
- Transaction cost modeling (commission, slippage)
- Flexible signal generation
- Performance attribution
- Risk-adjusted metrics (Sharpe, Sortino, Calmar, etc.)
- Tear sheet generation

### Best For
- Strategy research and development
- Parameter optimization (grid search, Bayesian optimization)
- Walk-forward analysis
- Regime-based strategy testing
- High-frequency signal evaluation (when data permits)

### Limitations
- Assumes perfect execution at close prices (no intraday simulation)
- Limited ability to model complex order types
- Less realistic for strategies with high turnover or complex execution logic

## Event-Driven Backtester

### Architecture
- Processes market data chronologically, bar-by-bar
- Simulates realistic trade execution with order types and slippage
- Maintains internal state throughout the backtest
- Ideal for strategy validation and live trading preparation

### Features
- True chronological processing (tick, minute, hourly, daily data)
- Multiple order types (market, limit, stop, bracket)
- Position sizing algorithms (fixed fractional, Kelly, volatility targeting)
- Risk management integration (drawdown limits, VaR constraints)
- Commission and slippage modeling
- Advanced transaction cost modeling
- Detailed trade logging and analysis
- Realistic portfolio construction

### Best For
- Strategy validation before live deployment
- High-frequency trading strategy testing
- Complex order logic evaluation
- Risk management strategy testing
- Live trading simulation
- Strategy development requiring realistic execution assumptions

### Limitations
- Slower than vectorized approaches (especially with fine-grained data)
- More complex to configure and tune
- May require more careful parameter selection

## When to Use Which

### Choose Vectorized Backtester When:
- Early strategy research and idea generation
- Parameter optimization and sweeps
- Walk-forward analysis and regime testing
- High-volume strategy testing where speed is critical
- Initial validation before moving to event-driven simulation

### Choose Event-Driven Backtester When:
- Pre-live strategy validation and final testing
- Complex order types and execution logic
- Risk management strategy evaluation
- High-frequency strategies where execution realism matters
- Strategies sensitive to slippage and market impact
- Final validation before capital allocation

## Usage Examples

### Vectorized Backtester
```python
from alpha.backtest import VectorizedBacktester
import pandas as pd
import numpy as np

# Prepare data and signals
data = {'AAPL': price_dataframe, 'GOOGL': price_dataframe}
signals = {'AAPL': signal_series, 'GOOGL': signal_series}

# Run backtest
backtester = VectorizedBacktester()
results = backtester.run_backtest(
    signals=signals,
    data=data,
    initial_capital=100000,
    commission=0.001,
    slippage=0.0005
)

# Access results
print(f"Total Return: {results['metrics']['total_return']:.2%}")
print(f"Sharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
```

### Event-Driven Backtester
```python
from alpha.backtest import EventDrivenBacktester
import pandas as pd
import numpy as np

# Prepare data and signals
data = {'AAPL': price_dataframe, 'GOOGL': price_dataframe}
signals = {'AAPL': signal_series, 'GOOGL': signal_series}

# Run backtest
backtester = EventDrivenBacktester()
results = backtester.run_backtest(
    signals=signals,
    data=data,
    initial_capital=100000,
    commission=0.001,
    slippage=0.0005
)

# Access results
print(f"Total Return: {results['total_return']:.2%}")
print(f"Max Drawdown: {results['max_drawdown']:.2%}")
print(f"Total Trades: {results['total_trades']}")

# Generate tear sheet
print(backtester.get_tear_sheet())
```

## Configuration

Both backtesters accept configuration through:
1. Direct parameter passing to `run_backtest()` methods
2. Configuration files (YAML format) passed via constructor
3. Environment variable overrides for sensitive data (API keys)

See `config/settings.yaml` for example configuration structure.

## Performance Characteristics

| Aspect | Vectorized | Event-Driven |
|--------|------------|--------------|
| Speed | Very Fast (vectorized ops) | Moderate (chronological) |
| Memory Usage | High (full datasets in memory) | Moderate (streaming processing) |
| Realism | Lower (close-price assumption) | Higher (realistic simulation) |
| Flexibility | Moderate (signal-based) | High (order types, risk mgmt) |
| Best Use Case | Research & Optimization | Validation & Live Prep |

## API Reference

See the docstrings in `alpha/backtest/vectorized.py` and `alpha/backtest/event_driven.py` for detailed API documentation.

## Extending the Framework

To add new features:
1. **Vectorized Backtester**: Add new metrics, optimization techniques, or data transformations
2. **Event-Driven Backtester**: Add new order types, position sizing algorithms, or risk management rules
3. **Shared Components**: Enhance data providers, signal generators, or performance analytics

## References

- [Backtesting Principles](https://www.quantstart.com/articles/Backtesting-Principles-Part-1/)
- [Vectorized Backtesting Techniques](https://www.quantinsti.com/blog/vectorized-backtesting-python/)
- [Event-Driven Architecture in Trading Systems](https://www.quantconnect.com/tutorials/event-driven-backtesting/)
