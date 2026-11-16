# Alpha Trading System

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)

Multi-brain regime-adaptive trading system combining factor investing, machine learning, and advanced risk management.

## 🧠 Architecture

The system implements a three-brain architecture inspired by neuroscience:

1. **ChartBrain** - Real-time market state analysis
   - Regime detection (trend, chop, volatility expansion)
   - Technical indicators (ATR, RSI, ADX, momentum)
   - Pattern recognition (candlestick, chart patterns)
   - Support/Resistance levels
   - Volatility regime classification

2. **DecisionBrain** - Regime-adaptive decision making
   - Factor-based signal generation (100+ factors)
   - Model blending by regime (LightGBM, XGBoost, Neural Nets)
   - Pattern-based signal modulation
   - Hard risk gates (drawdown, volatility, position limits)
   - Kelly criterion position sizing
   - Order generation (market, limit, stop)

3. **LearningBrain** - Online adaptation and meta-learning
   - Online outcome recording
   - Kelly estimation per regime
   - Pattern performance tracking and graveyard
   - Model weight adaptation
   - Learning rate annealing
   - Survival statistics tracking

4. **TradingBot** - Orchestrator and execution layer
   - WebSocket integration (Binance, Bybit)
   - Paper/live trading modes
   - State persistence (PostgreSQL/SQLite)
   - Performance tracking and reporting
   - Risk management integration

## 🚀 Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/aryanagarwal12/alpha-trading-system.git
cd alpha-trading-system

# Install with development dependencies
pip install -e .[dev,notebook]

# Install live trading dependencies (optional)
pip install -e .[live]
```

### Paper Trading Demo

```bash
# Run the paper trading bot
python -m alpha.brain.trading_bot --symbol BTCUSDT --paper-trading

# Or use the convenience script
python scripts/run_paper_trading.py
```

### Notebook Demo

```bash
# Launch Jupyter with the alpha model demo
jupyter lab notebooks/alpha_model_demo.ipynb
```

### Backtesting

```bash
# Run vectorized backtest
python -m alpha.backtest.engine --start 2023-01-01 --end 2023-12-31

# Or run event-driven backtest
python -m alpha.backtest.event_driven --strategy momentum
```

## 📊 Features

- **100+ Factors**: Momentum, reversal, volatility, volume, technical, pattern, alternative, microstructure
- **Multi-Model Ensemble**: LightGBM, XGBoost, CatBoost, Ridge, Lasso, ElasticNet, MLP, LSTM, Transformer
- **Regime Detection**: HMM-based market regime classification (trend_up, trend_down, chop, vol_expansion)
- **Online Learning**: Kelly criterion updates, pattern graveyard, meta-learning
- **Risk Management**: Survival rules, drawdown limits, volatility targeting, correlation limits
- **Execution**: Paper trading, live trading (Binance, Interactive Brokers, Alpaca), TWAP/VWAP
- **Data**: Yahoo Finance primary, Binance/WebSocket fallback, alternative data (funding rates, open interest)
- **Persistence**: PostgreSQL/SQLite state storage with connection pooling
- **Monitoring**: JSON logging, Prometheus metrics, alerting system

## 📖 Documentation

See the [docs/](docs/) directory for detailed documentation:

- [Architecture Overview](docs/architecture.md)
- [Configuration Reference](docs/configuration.md)
- [Factor Library](docs/factor_library.md)
- [Model Training Guide](docs/model_training.md)
- [Risk Management](docs/risk_management.md)
- [Backtesting Framework](docs/backtest_framework.md)
- [Deployment Guide](docs/deployment.md)

## 🐳 Docker Deployment

```bash
# Build image
docker build -t alpha-trading-system .

# Run paper trading
docker run --env-file .env alpha-trading-system

# Run with custom config
docker run -v $(pwd)/config:/app/config alpha-trading-system python -m alpha.brain.trading_bot --config config/production.yaml
```

## 📈 Performance

See [results/](results/) for:
- Backtest reports (2020-2024)
- Factor IC analysis
- Drawdown analysis
- Regime performance breakdown
- Transaction cost analysis

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Inspired by neuroscience research on decision-making
- Built on open-source libraries: pandas, numpy, scikit-learn, lightgbm, yfinance
- Factor definitions based on academic literature and industry best practices
- Risk management principles adapted from quantitative trading literature

---
*Built with ❤️ for the quantitative trading community*
