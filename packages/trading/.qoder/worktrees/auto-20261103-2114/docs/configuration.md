# Configuration Reference

The Alpha Trading System uses a centralized YAML configuration file (`settings.yaml`) to control all aspects of system behavior. This document provides a complete reference to all configuration options.

## Configuration File Location

By default, the system looks for `settings.yaml` in:
- Current working directory
- `./config/settings.yaml` (relative to executable)
- `/etc/alpha-trading-system/settings.yaml` (system-wide)
- Path specified by `ALPHA_CONFIG_PATH` environment variable

## Configuration Structure

The configuration is organized into logical sections:

```yaml
# Top-level sections
universe:       # Tradable instruments and markets
data:           # Data acquisition and caching
factors:        # Technical and alternative factors
models:         # Machine learning model configuration
validation:     # Model validation and backtesting
risk:           # Risk management parameters
portfolio:      # Portfolio construction and optimization
execution:      # Order execution and broker integration
monitoring:     # Logging, metrics, and alerting
feature_store:  # Feature storage and versioning
model_registry: # Model registry and promotion
```

Each section contains nested configuration options specific to that domain.

## Detailed Reference

### Universe Configuration

Defines the set of instruments the system can trade.

```yaml
universe:
  equities:
    - "SPY"   # S&P 500 ETF
    - "QQQ"   # Nasdaq-100 ETF
    - "IWM"   # Russell 2000 ETF
    # ... additional equity ETFs
  
  crypto:
    - "BTC-USD"   # Bitcoin/USD
    - "ETH-USD"   # Ethereum/USD
    - "SOL-USD"   # Solana/USD
    # ... additional cryptocurrencies
  
  futures:
    - "ES=F"   # E-mini S&P 500 futures
    - "NQ=F"   # E-mini Nasdaq-100 futures
    # ... additional futures contracts
```

### Data Configuration

Controls how market data is acquired, cached, and processed.

```yaml
data:
  start_date: "2020-01-01"        # Historical data start date
  end_date: "2024-12-31"          # Historical data end date (null for present)
  frequency: "1d"                 # Data frequency: 1m, 5m, 15m, 1h, 1d, 1w
  adjust: true                    # Adjust for splits and dividends
  cache_dir: "./data/cache"       # Directory for cached data
  
  providers:
    primary: "yfinance"           # Primary data provider
    fallback:                     # Ordered fallback providers
      - "alphavantage"
      - "polygon"
      - "binance"
  
  alternative:
    funding_rates: true           # Enable funding rates data
    open_interest: true           # Enable open interest data
    fear_greed: true              # Enable fear & greed index
    google_trends: false          # Disable Google Trends data
    whale_alerts: false           # Disable whale alert data
    exchange_flows: false         # Disable exchange flow data
```

### Factors Configuration

Configuration for the 100+ technical and alternative factors.

```yaml
factors:
  # Momentum factors
  momentum:
    lookbacks: [5, 10, 20, 60, 120, 252]  # Lookback periods in days
    skip: 21                                # Skip period for 12-1 momentum
    enabled: true                           # Enable momentum factors
  
  # Mean reversion factors
  reversal:
    lookbacks: [1, 5, 10, 21, 63]         # Lookback periods
    enabled: true                           # Enable reversal factors
  
  # Volatility factors
  volatility:
    lookbacks: [10, 20, 60, 120, 252]     # Lookback periods
    realized: true                          # Use realized volatility
    parkinson: true                         # Use Parkinson volatility estimator
    enabled: true                           # Enable volatility factors
  
  # Volume factors
  volume:
    lookbacks: [5, 10, 20, 60]            # Lookback periods
    enabled: true                           # Enable volume factors
  
  # Technical indicators
  technical:
    rsi: [14]                               # RSI periods
    macd:                                   # MACD configuration
      fast: 12
      slow: 26
      signal: 9
    bollinger_bands:                        # Bollinger Bands
      period: 20
      std_dev: 2
    enabled: true                           # Enable technical indicators
  
  # Alternative data factors
  alternative:
    sentiment: true                         # Enable sentiment factors
    flow_based: true                        # Enable flow-based factors
    breadth: true                           # Enable market breadth factors
    enabled: true                           # Enable alternative factors
```

### Models Configuration

Machine learning model configuration and hyperparameters.

```yaml
models:
  # Linear models
  linear:
    ridge:                                  # Ridge regression
      alpha: 1.0
    lasso:                                  # Lasso regression
      alpha: 0.1
    elastic_net:                            # Elastic Net
      alpha: 0.1
      l1_ratio: 0.5
    enabled: true
  
  # Tree-based models
  tree:
    lightgbm:                               # LightGBM
      n_estimators: 200
      max_depth: 5
      learning_rate: 0.05
      num_leaves: 31
    xgboost:                                # XGBoost
      n_estimators: 200
      max_depth: 5
      learning_rate: 0.05
      subsample: 0.8
    catboost:                               # CatBoost
      iterations: 200
      depth: 6
      learning_rate: 0.03
    enabled: true
  
  # Neural networks
  neural:
    mlp:                                    # Multi-layer Perceptron
      hidden_layer_sizes: [100, 50]
      activation: 'relu'
      alpha: 0.0001
    lstm:                                   # Long Short-Term Memory
      units: 50
      dropout: 0.2
    transformer:                            # Transformer encoder
      d_model: 64
      n_heads: 4
      num_layers: 2
    enabled: true
  
  # Ensemble methods
  ensemble:
    voting:                                 # Voting classifier/regressor
      weights: null                         # Equal weights if null
    stacking:                               # Stacking classifier/regressor
      final_estimator: "ridge"
      cv: 5
    blending:                               # Blending (holdout)
      holdout_ratio: 0.1
    dynamic:                                # Dynamic weighting by regime
      update_frequency: "daily"
    enabled: true
```

### Validation Configuration

Model validation and backtesting configuration.

```yaml
validation:
  # Cross-validation methods
  cross_validation:
    method: "purged_kfold"                  # Options: kfold, purged_kfold, combinatorial_purged_kfold, timeseries
    n_splits: 5                             # Number of folds
    embargo_days: 1                         # Embargo period for purged CV
    purge_days: 1                           # Purge period for purged CV
  
  # Backtesting engine
  backtest:
    initial_capital: 100000                 # Starting capital in USD
    commission: 0.001                       # Commission per trade (0.1%)
    slippage: 0.0005                        # Slippage per trade (0.05%)
    spread: 0.0002                          # Assumed bid-ask spread
    margin_requirement: 0.2                 # Margin requirement for futures
    
    # Performance metrics
    metrics:
      - "total_return"
      - "annualized_return"
      - "volatility"
      - "sharpe_ratio"
      - "sortino_ratio"
      - "calmar_ratio"
      - "max_drawdown"
      - "win_rate"
      - "profit_factor"
      - "expectancy"
```

### Risk Management Configuration

Risk controls and position sizing parameters.

```yaml
risk:
  # Survival rules (hard limits that cannot be violated)
  survival_rules:
    max_daily_dd: 0.05                      # Maximum daily drawdown (5%)
    max_weekly_dd: 0.15                     # Maximum weekly drawdown (15%)
    max_position_pct: 0.10                  # Maximum position size (10% of equity)
    max_leverage: 2.0                       # Maximum leverage (2x)
    min_edge_bp: 0.5                        # Minimum edge required (0.5 basis points)
    kelly_cap: 0.25                         # Maximum Kelly fraction to use (25%)
    vol_extreme_threshold: 0.95             # Volatility percentile for EXTREME regime
    news_blackout_minutes: 30               # No trading around news events
  
  # Position sizing methods
  position_sizing:
    method: "kelly"                         # Options: fixed_fraction, kelly, volatility_target, risk_parity, max_sharpe, min_variance
    kelly_fraction: 0.5                     # Fraction of Kelly to use (half-Kelly)
    target_vol: 0.15                        # Target annualized volatility (15%)
    lookback_period: 252                    # Lookback period for volatility calculation (trading days)
  
  # Portfolio constraints
  portfolio_constraints:
    max_correlation: 0.7                    # Maximum average correlation between positions
    max_sector_exposure: 0.3                # Maximum exposure to any single sector
    max_factor_exposure: 0.2                # Maximum exposure to any single factor
    turnover_limit: 0.3                     # Maximum monthly portfolio turnover
  
  # Drawdown controls
  drawdown_controls:
    reduce_on_dd: true                      # Reduce position sizing during drawdowns
    dd_thresholds:                          # Drawdown levels that trigger reduction
      0.05: 0.8                             # At 5% DD, use 80% of normal size
      0.10: 0.6                             # At 10% DD, use 60% of normal size
      0.20: 0.4                             # At 20% DD, use 40% of normal size
      0.30: 0.2                             # At 30% DD, use 20% of normal size
```

### Portfolio Configuration

Portfolio construction and optimization parameters.

```yaml
portfolio:
  # Optimization methods
  optimization:
    method: "risk_parity"                   # Options: mean_variance, min_variance, max_sharpe, risk_parity, max_diversion, equal_weight, dollar_neutral
    lookback_period: 252                    # Lookback period for covariance estimation
    shrinkage: true                         # Use Ledoit-Wolf shrinkage for covariance
    rebalance_frequency: "monthly"          # How often to rebalance: daily, weekly, monthly, quarterly
    transaction_cost_model:                 # Model for estimating transaction costs
      fixed: 0.001                          # Fixed cost per trade
      proportional: 0.0005                  # Proportional cost of trade value
      market_impact: 0.0001                 # Market impact model parameter
  
  # Constraints
  constraints:
    long_only: false                        # Allow short positions
    max_weight: 0.10                        # Maximum weight per position
    min_weight: -0.10                       # Minimum weight per position (for shorts)
    max_leverage: 1.5                       # Maximum portfolio leverage
    max_turnover: 0.2                       # Maximum monthly turnover
  
  # Risk budgeting
  risk_budgeting:
    method: "equal_risk_contribution"       # Options: equal_risk_contribution, risk_parity, inverse_volatility, max_diversion
    lookback_period: 252
```

### Execution Configuration

Order execution and broker integration settings.

```yaml
execution:
  mode: "paper"                             # Options: paper, live, backtest
  broker: "interactive_brokers"             # Options: ib, alpaca, binance, bybit, kraken, coinbase_pro
  account: ""                               # Account identifier (if required by broker)
  
  # Order sizing
  sizing:
    method: "kelly"                         # Options: fixed_amount, fixed_fraction, kelly, volatility_target, risk_parity, dollar_neutral
    kelly_fraction: 0.5                     # Fraction of Kelly to use
    target_vol: 0.15                        # Target volatility for vol-target sizing
    max_leverage: 2.0                       # Maximum leverage allowed
  
  # Order types and timing
  orders:
    type: "limit"                           # Options: market, limit, stop, stop_limit, twap, vwap, iceberg
    time_in_force: "DAY"                    # Options: DAY, GTC, GTX, IOC, FOK
    max_slippage: 0.001                     # Maximum acceptable slippage (0.1%)
    retry_attempts: 3                       # Number of retry attempts on failure
    retry_delay: 5                          # Seconds to wait between retries
  
  # Pre-trade risk checks
  risk_checks:
    pre_trade: true                         # Enable pre-trade risk checks
    max_order_size: 0.1                     # Maximum order size as fraction of equity
    max_daily_loss: 0.02                    # Maximum daily loss before halting trading (2%)
    max_drawdown: 0.1                       # Maximum drawdown before halting trading (10%)
    correlation_limit: 0.7                  # Maximum correlation with existing positions
    concentration_limit: 0.2                # Maximum concentration in any single position
```

### Monitoring Configuration

Logging, metrics, and alerting configuration.

```yaml
monitoring:
  logging:
    level: "INFO"                           # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
    format: "json"                          # Options: json, text, csv
    file: "./logs/alpha.log"                # Log file path
    max_size: "100MB"                       # Maximum log file size before rotation
    backup_count: 10                        # Number of backup logs to keep
  
  metrics:
    prometheus: false                       # Enable Prometheus metrics endpoint
    prometheus_port: 8000                   # Port for Prometheus metrics
    grafana: false                          # Enable Grafana dashboard
    grafana_port: 3000                      # Port for Grafana
    datadog: false                          # Send metrics to Datadog
    datadog_api_key: ""                     # Datadog API key
  
  alerts:
    email: true                             # Enable email alerts
    email_smtp_server: "smtp.gmail.com"     # SMTP server for email
    email_smtp_port: 587                    # SMTP port
    email_username: ""                      # SMTP username
    email_password: ""                      # SMTP password (use app password or env var)
    email_from: "alpha-trading-system@example.com"
    email_to: ["trader@example.com"]
    
    slack: false                            # Enable Slack alerts
    slack_webhook_url: ""                   # Slack webhook URL
    slack_channel: "#alpha-alerts"          # Slack channel for alerts
    
    pagerduty: false                        # Enable PagerDuty alerts
    pagerduty_integration_key: ""           # PagerDuty integration key
    
    thresholds:                             # Alert thresholds
      drawdown: 0.05                        # Alert when drawdown exceeds 5%
      daily_loss: 0.02                      # Alert when daily loss exceeds 2%
      sharpe_degradation: 0.5               # Alert when Sharpe ratio degrades by 50%
      model_drift: 0.1                      # Alert when model performance drifts by 10%
      data_staleness: 3600                  # Alert if data is older than 1 hour (seconds)
      connection_loss: 60                   # Alert if WebSocket disconnected for >60 seconds
  
  dashboard:
    enabled: true                           # Enable built-in dashboard
    port: 8080                              # Port for dashboard
    refresh: 60                             # Dashboard refresh rate in seconds
    host: "0.0.0.0"                         # Host to bind dashboard (0.0.0.0 = all interfaces)
```

### Feature Store Configuration

Configuration for the feature storage system.

```yaml
feature_store:
  enabled: true                             # Enable feature storage
  path: "./data/features"                   # Directory for storing features
  format: "parquet"                         # Storage format: parquet, feather, hdf5
  versioning: true                          # Enable versioning of features
  ttl_days: 30                              # Time-to-live for features (days)
  compression: "SNAPPY"                     # Compression algorithm: SNAPPY, GZIP, BZ2, LZ4, ZSTD
  partition_by: ["date", "symbol"]          # Partition features by these columns
  max_file_size_mb: 1024                    # Maximum size of individual files (MB)
```

### Model Registry Configuration

Configuration for the model registry and promotion system.

```yaml
model_registry:
  enabled: true                             # Enable model registry
  path: "./models/registry"                 # Directory for storing models
  versioning: true                          # Enable versioning of models
  storage_format: "pickle"                  # Storage format: pickle, joblib, onnx
  
  # Model metadata to store with each model
  metadata:
    - "train_date"                          # Date when model was trained
    - "features"                            # List of features used
    - "hyperparameters"                     # Model hyperparameters
    - "metrics"                             # Training/validation metrics
    - "regime"                              # Predominant regime during training
    - "data_hash"                           # Hash of training data for reproducibility
    - "git_commit"                          # Git commit hash at training time
  
  # Model promotion rules
  promotion:
    method: "ic_threshold"                  # Options: ic_threshold, sharpe_threshold, drawdown_threshold, composite_score
    ic_threshold: 0.02                      # Minimum IC required for promotion
    sharpe_threshold: 1.0                   # Minimum Sharpe ratio required
    max_drawdown: 0.1                       # Maximum drawdown allowed
    min_trades: 30                          # Minimum number of trades for evaluation
    evaluation_window: 252                  # Lookback period for performance evaluation (days)
    
    # A/B testing for model promotion
    ab_test:
      enabled: false                        # Enable A/B testing before full promotion
      traffic_percentage: 10                # Percentage of traffic to send to new model
      evaluation_period: 14                 # Days to evaluate before full promotion
      minimum_improvement: 0.005            # Minimum IC improvement required for promotion
```

### Advanced Configuration Options

Additional configuration options for advanced use cases.

```yaml
# System-wide settings
system:
  timezone: "UTC"                           # Default timezone for timestamps
  date_format: "%Y-%m-%d"                   # Date format for display
  datetime_format: "%Y-%m-%d %H:%M:%S"      # DateTime format for display
  float_precision: 4                        # Decimal places for floating point display
  
# Performance optimization
performance:
  use_numba: true                           # Use Numba JIT compilation where possible
  numba_parallel: true                      # Enable parallel execution in Numba
  chunk_size: 1000                          # Chunk size for batch processing
  max_memory_mb: 2048                       # Maximum memory usage before warning
  
# Debugging and development
development:
  debug_mode: false                         # Enable debug mode (more verbose logging)
  profile_code: false                       # Enable code profiling
  save_artifacts: false                     # Save intermediate artifacts for debugging
  test_mode: false                          # Run in test mode (uses synthetic data)
```

## Configuration Validation

The system performs validation on startup to ensure configuration values are within acceptable ranges. Invalid configurations will prevent the system from starting and will display descriptive error messages.

### Validation Rules

- All percentage values must be between 0 and 1 (or 0 and 100 if specified as percentage)
- All time periods must be positive integers
- All price-related values must be positive
- All lookback periods must be greater than 0
- All risk limits must be reasonable (e.g., max_leverage >= 1.0)
- All probabilities must be between 0 and 1

## Environment Variable Overrides

Certain configuration values can be overridden using environment variables:

- `ALPHA_CONFIG_PATH`: Path to custom configuration file
- `ALPHA_ENV`: Environment name (development, staging, production)
- `ALPHA_LOG_LEVEL`: Override logging level (DEBUG, INFO, WARNING, ERROR)
- `ALPHA_MONITORING_PORT`: Override monitoring dashboard port
- `ALPHA_WEBSOCKET_URL`: Override WebSocket endpoint URL
- `ALPHA_BROKER_API_KEY`: Override broker API credential
- `ALPHA_BROKER_SECRET`: Override broker API secret

## Example Configurations

### Minimal Configuration for Paper Trading

```yaml
universe:
  equities:
    - "SPY"
    - "QQQ"

data:
  frequency: "1d"
  adjust: true
  providers:
    primary: "yfinance"

factors:
  momentum:
    enabled: true
  reversal:
    enabled: true

models:
  linear:
    enabled: true
  tree:
    enabled: true

risk:
  survival_rules:
    max_daily_dd: 0.05
    max_position_pct: 0.10

execution:
  mode: "paper"
  broker: "ib_insync"
```

### High-Frequency Trading Configuration

```yaml
universe:
  crypto:
    - "BTC-USD"
    - "ETH-USD"

data:
  frequency: "1m"
  adjust: false
  providers:
    primary: "binance"
    fallback: ["bybit", "kraken"]

factors:
  # Short-term factors only for HFT
  momentum:
    lookbacks: [5, 10, 20]
    enabled: true
  volatility:
    lookbacks: [5, 10, 20]
    enabled: true
  volume:
    lookbacks: [5, 10, 20]
    enabled: true
  technical:
    rsi: [7, 14]
    bollinger_bands:
      period: 10
      std_dev: 2
    enabled: true

models:
  # Fast models for HFT
  linear:
    enabled: true
  tree:
    lightgbm:
      n_estimators: 50
      max_depth: 3
      learning_rate: 0.1
    enabled: true

risk:
  survival_rules:
    max_daily_dd: 0.02          # Tighter daily drawdown limit
    max_position_pct: 0.05      # Smaller position sizes
    max_leverage: 3.0           # Higher leverage allowed
    news_blackout_minutes: 5    # Shorter news blackout

execution:
  mode: "live"
  broker: "binance"
  orders:
    type: "market"              # Market orders for immediacy
    time_in_force: "IOC"        # Immediate or cancel
    max_slippage: 0.0005        # Tighter slippage tolerance
```

## Best Practices

1. **Version Control**: Keep your configuration files in version control (Git)
2. **Environment Separation**: Use different config files for development, staging, and production
3. **Secrets Management**: Never commit API keys or secrets to version control; use environment variables or secret management systems
4. **Incremental Changes**: Make small, tested changes to configuration rather than large overhauls
5. **Documentation**: Comment non-obvious configuration choices in your config file
6. **Validation**: Always test configuration changes in paper trading before deploying to live
7. **Backups**: Regularly backup your configuration files along with your data

## Troubleshooting

### Common Configuration Issues

- **Invalid YAML Syntax**: Use a YAML validator to check syntax
- **Missing Required Sections**: Ensure all required sections are present
- **Invalid Data Types**: Make sure values are of correct type (string, number, boolean, list)
- **Out of Range Values**: Check that values are within allowed ranges
- **Incorrect Provider Names**: Verify provider names match those in the codebase
- **Path Issues**: Use absolute paths or paths relative to the config file location

### Debugging Configuration

To see the effective configuration being used by the system:

```bash
python -c "
import yaml
from alpha.config import load_config
config = load_config('settings.yaml')
print(yaml.dump(config, default_flow_style=False))
```
