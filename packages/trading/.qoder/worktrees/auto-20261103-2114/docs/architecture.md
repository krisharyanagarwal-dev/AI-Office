# System Architecture

## Overview

The Alpha Trading System implements a three-brain architecture inspired by neuroscience research on decision-making. Each brain specializes in different aspects of the trading process, working together to make adaptive, intelligent trading decisions.

![Architecture Diagram](architecture_diagram.png)

*Figure 1: The three-brain architecture with data flow and feedback loops*

## Component Breakdown

### 1. ChartBrain 🧠
**Responsibility**: Real-time market state analysis and feature generation

**Functions**:
- Maintains rolling window of OHLCV data
- Computes technical indicators incrementally (ATR, RSI, ADX, etc.)
- Detects market regimes using HMM (Hidden Markov Model)
- Identifies candlestick and chart patterns
- Tracks support/resistance levels
- Classifies volatility regimes
- Provides immutable ChartContext to DecisionBrain

**Key Data Structures**:
- `Bar`: Immutable OHLCV data point
- `ChartContext`: Snapshot of market state for decision making
- `PatternSignal`: Detected pattern with direction and strength
- `SRLevel`: Support/resistance level with strength and age

### 2. DecisionBrain 💭
**Responsibility**: Generating trading decisions based on market state

**Functions**:
- Generates raw signals from factor library and ML models
- Applies regime-adaptive model blending
- Modulates signals by detected patterns
- Enforces hard risk gates (survival rules)
- Calculates optimal position sizing (Kelly criterion, volatility targeting)
- Creates executable orders (market, limit, stop)
- Provides decision rationale and risk metrics

**Key Data Structures**:
- `Signal`: Model/factor output (-1 to 1)
- `Decision`: Collection of orders with rationale and risk metrics
- `Order`: Executable order specification
- `Position`: Current position tracking

### 3. LearningBrain 📚
**Responsibility**: Online adaptation and meta-learning

**Functions**:
- Records decision outcomes and calculates P&L
- Updates Kelly criterion estimates per regime
- Tracks pattern performance and maintains graveyard
- Adapts model weights based on regime performance
- Adjusts learning rates dynamically
- Persists state for survival across restarts
- Provides performance analytics

**Key Data Structures**:
- `ModelWeights`: Regime-specific model weights
- `KellyEstimate`: Win rate, avg win/loss, Kelly fraction
- `GraveyardEntry`: Failed patterns with disablement logic
- `PnL`: Realized and unrealized profit/loss

### 4. TradingBot 🤖
**Responsibility**: Orchestration, execution, and system management

**Functions**:
- Initializes and coordinates all three brains
- Manages WebSocket connections (Binance, Bybit)
- Processes market data bars through the brain pipeline
- Executes trades (paper or live mode)
- Tracks performance and position status
- Persists system state
- Provides status reporting and monitoring interfaces

**Key Data Structures**:
- Internal state tracking (positions, orders, performance)
- WebSocket connection management
- Thread-safe bar processing queue
- Configuration management

## Data Flow

1. **Data Ingestion**: WebSocket provider receives real-time bar data
2. **ChartBrain Update**: Bar data updates market state and indicators
3. **Decision Making**: ChartContext fed to DecisionBrain for signal generation
4. **Order Creation**: Non-flat decisions converted to executable orders
5. **Execution**: Orders filled (simulated or real) and positions updated
6. **Learning**: Outcomes recorded and models adapted
7. **Persistence**: State saved periodically to survive restarts

## State Persistence

The system uses a layered persistence approach:

- **StateStore**: SQLite/PostgreSQL backend for all persistent state
- **ChartBrain**: Saves chart context and technical indicator state
- **DecisionBrain**: Saves model configurations (if applicable)
- **LearningBrain**: Saves model weights, Kelly estimates, graveyard
- **TradingBot**: Saves operational metrics and survival state
- **Position Tracking**: Current positions saved and loaded on startup

## Threading Model

- **Main Thread**: Application coordination and user interface
- **WebSocket Thread**: Receives and parses real-time market data
- **Processing Thread**: Consumes bar queue and runs the brain pipeline
- All state access is thread-safe via locking or immutable data structures

## Error Handling & Resilience

- Graceful degradation when components fail
- Automatic WebSocket reconnection with exponential backoff
- State checkpointing every N bars to minimize data loss
- Comprehensive logging with structured JSON output
- Circuit breaker patterns for external API calls
- Health checks and self-diagnosis capabilities

## Configuration

All system behavior is controlled through `settings.yaml`:
- Brain-specific parameters (lookback periods, thresholds)
- Risk management rules (drawdown limits, position sizing)
- Execution parameters (order types, slippage models)
- Monitoring and alerting thresholds
- Data provider selection and fallback chains

## Extensibility

The modular design allows for easy extension:
- Add new factors to the factor library
- Implement new ML models in the models module
- Add new regime detection algorithms
- Implement alternative execution algorithms
- Add new data providers (websocket, REST, file-based)
- Customize risk rules without changing core logic

## Profit Attribution Engine

### Overview
Post-trade performance decomposition using Brinson-style attribution across multiple dimensions.

### Components

#### Factor Attribution
- Brinson-style decomposition: Allocation + Selection
- Inputs: Factor returns (assets × factors), Factor weights (assets × factors)
- Output: Per-factor contribution, % of total return

#### Regime Attribution
- Performance decomposition by market regime (trend_up, trend_down, chop)
- Inputs: Period returns, Regime labels
- Output: Per-regime total/annualized return, contribution %

#### Model Attribution
- Ensemble model contribution via IC-weighting
- Inputs: Model predictions, Actual returns, Model weights
- Output: IC per model, weighted attribution, contribution %

#### Factor Half-Life Analysis
- Autocorrelation decay estimation
- Inputs: Factor return series
- Output: Half-life in periods

#### Regime Transition Matrix
- Markov transition probabilities
- Inputs: Historical regime sequence
- Output: Probability matrix (from × to)

### Data Flow
1. Factor returns generated from market data
2. Regime labels from trend signal
3. Model predictions from ensemble
4. Attribution functions compute contributions
5. Results displayed in notebook cells 14-17

### Integration Points
- `alpha/validation/metrics.py`: Core functions
- `examples/profit_attribution_demo.py`: Standalone usage
- `alpha_model.ipynb` cells 14-17: Notebook integration

### Configuration
- `periods_per_year`: 252 (daily), 12 (monthly), 52 (weekly)
- Half-life max lag: 252 (default)
- Regime detection threshold: configurable via `settings.yaml`

### New Enhanced Attribution Functions (v0.2.0+)

#### Transaction-Cost-Aware Factor Attribution
```python
calculate_profit_attribution_by_factor_tca(
    factor_returns, factor_weights, transaction_costs
)
```
- Subtracts per-factor transaction costs from gross attribution
- Cost model: `turnover * cost_per_trade` per factor
- Output: net attribution after costs

#### Factor Timing Attribution
```python
calculate_factor_timing_attribution(
    factor_returns, factor_weights, 
    benchmark_weights
)
```
- Brinson-style: Allocation + Selection + Interaction
- Compare dynamic weights vs static benchmark weights
- Output: timing alpha per factor

#### Portfolio-Level Brinson Attribution
```python
calculate_brinson_attribution(
    portfolio_returns, benchmark_returns,
    portfolio_weights, benchmark_weights,
    sector_returns=None
)
```
- Classic Brinson: Allocation + Selection + Interaction
- Optional sector decomposition
- Returns dict: `total`, `by_asset`, `by_sector`, `by_factor`

## Performance Characteristics

- **Latency**: Sub-millisecond decision making from bar receipt to order
- **Throughput**: Capable of processing 1000+ bars/second on modest hardware
- **Memory**: Constant memory footprint based on lookback window size
- **Scalability**: Horizontal scaling possible by symbol partitioning
- **Fault Tolerance**: Single component failures don't crash the system

---

*Last updated: $(date)*  
*Alpha Trading System v0.2.0*
