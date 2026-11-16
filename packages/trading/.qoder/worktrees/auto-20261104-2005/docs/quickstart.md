# Quick Start Guide

Get up and running with the Alpha Trading System in under 5 minutes.

## Prerequisites

- Python 3.8 or higher
- Git (for cloning the repository)
- Internet connection (for initial data download)

## Installation

### Option 1: From PyPI (Recommended for Users)

```bash
pip install alpha-trading-system[notebook]
```

### Option 2: From Source (For Developers and Contributors)

```bash
# Clone the repository
git clone https://github.com/aryanagarwal12/alpha-trading-system.git
cd alpha-trading-system

# Install in development mode
pip install -e .[dev,notebook]
```

## Your First Paper Trade

Let's run a simple paper trading example with Bitcoin:

```bash
# Run the paper trading bot
python -m alpha.brain.trading_bot \
    --symbol BTC-USD \
    --paper-trading \
    --config ./config/settings.yaml
```

You should see output similar to:

```
2024-01-15 10:30:00,123 - alpha.brain.trading_bot - INFO - Starting trading bot for BTC-USD
2024-01-15 10:30:00,125 - alpha.brain.chart_brain - INFO - ChartBrain initialized for BTC-USD
2024-01-15 10:30:00,126 - alpha.brain.decision_brain - INFO - DecisionBrain initialized
2024-01-15 10:30:00,127 - alpha.brain.learning_brain - INFO - LearningBrain initialized
2024-01-15 10:30:00,128 - alpha.data.ws_provider - INFO - Connecting to Binance WebSocket: wss://stream.binance.com:9443/ws/btcusdt@1m
2024-01-15 10:30:00,500 - alpha.data.ws_provider - INFO - WebSocket connection opened
2024-01-15 10:30:00,501 - alpha.brain.trading_bot - INFO - Trading bot started
```

The bot will now:
1. Connect to Binance WebSocket for real-time BTC-USD data
2. Analyze market conditions using the three-brain architecture
3. Make paper trading decisions based on market state
4. Display periodic status updates
5. Continue running until you stop it with Ctrl+C

### What You're Seeing

The bot is operating in **paper trading mode**, which means:
- No real money is at risk
- Orders are simulated based on real market data
- Performance is tracked as if real trades were executed
- All logic is identical to live trading mode

## Exploring the System

### View Current Status

While the bot is running, you can check its status at any time by sending a SIGUSR1 signal:

```bash
# In another terminal, find the bot's PID and send signal:
ps aux | grep alpha.brain.trading_bot
kill -USR1 <PID>
```

Or use the built-in status command:

```bash
python -m alpha.brain.trading_bot --status
```

### Stopping the Bot

To stop the bot gracefully:

```bash
# Send SIGINT (Ctrl+C equivalent)
kill -INT <PID>
```

Or simply press Ctrl+C in the terminal where the bot is running.

The bot will:
1. Finish processing the current bar
2. Save its state to disk
3. Close WebSocket connections
4. Exit cleanly

## Running a Backtest

Let's test the system on historical data:

```bash
# Run a 3-month backtest on AAPL
python -m alpha.backtest.engine \
    --symbol AAPL \
    --start 2023-01-01 \
    --end 2023-03-31 \
    --initial-capital 100000
```

Sample output:
```
2024-01-15 11:00:00,000 - alpha.backtest.engine - INFO - Starting backtest for AAPL
2024-01-15 11:00:00,001 - alpha.backtest.engine - INFO - Period: 2023-01-01 to 2023-03-31 (90 days)
2024-01-15 11:00:00,002 - alpha.backtest.engine - INFO - Initial capital: $100,000.00
2024-01-15 11:00:00,003 - alpha.backtest.engine - INFO - Processing 1,260 market bars...
2024-01-15 11:00:05,123 - alpha.backtest.engine - INFO - Backtest complete!
2024-01-15 11:00:05,124 - alpha.backtest.engine - INFO - Final equity: $127,450.30
2024-01-15 11:00:05,125 - alpha.backtest.engine - INFO - Total return: +27.45%
2024-01-15 11:00:05,126 - alpha.backtest.engine - INFO - Sharpe ratio: 1.82
2024-01-15 11:00:05,127 - alpha.backtest.engine - INFO - Max drawdown: -8.32%
2024-01-15 11:00:05,128 - alpha.backtest.engine - INFO - Win rate: 58.7%
```

## Using Jupyter Notebooks

For interactive exploration and strategy development:

```bash
# Launch JupyterLab
jupyter lab

# Navigate to notebooks/ and open:
# - alpha_model_demo.ipynb: Complete alpha model demonstration
# - brain_architecture.ipynb: Interactive exploration of the three brains
# - factor_explorer.ipynb: Visualize and test individual factors
# - backtest_workshop.ipynb: Learn to run and analyze backtests
```

### Notebook: Alpha Model Demo

This notebook demonstrates:
1. Downloading multi-asset price data
2. Computing 100+ technical and alternative factors
3. Computing factor information coefficients (ICs)
4. Building and validating ML models (LightGBM, XGBoost, etc.)
5. Generating today's trading signals
6. Visualizing performance and risk metrics
7. Exporting signals for execution

## Next Steps

### 1. Customize Your Universe

Edit `config/settings.yaml` to trade the instruments you care about:

```yaml
universe:
  equities:
    - "AAPL"   # Apple Inc.
    - "MSFT"   # Microsoft Corp.
    - "GOOGL"  # Alphabet Inc.
    - "AMZN"   # Amazon.com Inc.
    - "TSLA"   # Tesla Inc.
  
  crypto:
    - "BTC-USD"
    - "ETH-USD"
```

### 2. Adjust Risk Parameters

Tune risk management to match your risk tolerance:

```yaml
risk:
  survival_rules:
    max_daily_dd: 0.03    # Reduce from 5% to 3% daily drawdown limit
    max_position_pct: 0.05 # Reduce from 10% to 5% max position
    max_leverage: 1.5      # Reduce from 2x to 1.5x leverage
```

### 3. Enable Live Trading

When you're ready to trade with real capital:

```bash
# Switch to live mode (USE WITH CAUTION)
python -m alpha.brain.trading_bot \
    --symbol AAPL \
    --live-trading \
    --broker alpaca \
    --account YOUR_ACCOUNT_ID
```

**⚠️ WARNING**: Live trading involves real financial risk. Start with small position sizes and thoroughly test in paper trading first.

### 4. Deploy as a Service

For continuous operation:

```bash
# Create a systemd service
sudo cp scripts/alpha-trading-system.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start alpha-trading-system
sudo systemctl enable alpha-trading-system

# View logs
journalctl -u alpha-trading-system -f
```

## Need Help?

- **Documentation**: See the `docs/` directory for detailed guides
- **Examples**: Check the `examples/` directory for complete use cases
- **Community**: Join our Discord server for questions and discussion
- **Issues**: Report bugs or request features on GitHub Issues

Happy trading! 📈
