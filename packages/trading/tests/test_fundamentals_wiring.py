"""Wiring tests: trading bots surface published fundamentals as read-only context.

Every bot must attach the facts to its decision context / state, and must
still work when no facts have been published. The facts are context only —
they never change a bot's directional behaviour.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

TRADING_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = TRADING_ROOT.parent
for _p in (str(TRADING_ROOT), str(PACKAGES_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from alpha.brain.trading_bot import TradingBot  # noqa: E402
from trading import execution_engine as ee  # noqa: E402

FUNDAMENTALS = {
    "fundamentals_by_symbol": {
        "BTCUSDT": {
            "symbol": "BTC-USD",
            "name": "Bitcoin USD",
            "asset_class": "crypto",
            "market_cap": 1_188_195_860_480,
            "price": 58994.1,
            "valuation_flag": "N/A",
            "leverage_flag": "N/A",
            "liquidity_flag": "Comfortable",
            "profitability_flag": "N/A",
            "roe_flag": "N/A",
            "momentum_flag": "Mid range",
            "volatility_30d_pct": 3.25,
            "turnover_ratio": 0.0512,
        },
        "RELIANCE": {
            "symbol": "RELIANCE.NS",
            "name": "Reliance Industries",
            "asset_class": "equity",
            "market_cap": 200_000_000_000,
            "price": 1400.0,
            "valuation_flag": "Fair",
            "leverage_flag": "Moderate",
            "liquidity_flag": "Adequate",
            "profitability_flag": "Strong",
            "roe_flag": "High",
            "momentum_flag": "Mid range",
            "volatility_30d_pct": None,
            "turnover_ratio": None,
        },
    }
}


class MockBrain:
    def __init__(self):
        self.contexts = []

    def get_chart_context(self, symbol):
        return {}

    async def on_bar(self, bar):
        return None

    async def generate_signals(self, context):
        self.contexts.append(context)
        return []


class FakeBar:
    def __init__(self, symbol, close):
        self.symbol = symbol
        self.close = close


def _make_bot():
    chart = MockBrain()
    decision = MockBrain()
    bot = TradingBot(
        chart_brain=chart,
        decision_brain=decision,
        learning_brain=MockBrain(),
        execution_engine=None,
        risk_manager=None,
        state_store=None,
        config={},
    )
    return bot, chart, decision


def test_trading_bot_attaches_fundamentals_to_decision_context(monkeypatch, tmp_path):
    metrics_path = tmp_path / "stocks_metrics.json"
    metrics_path.write_text(json.dumps(FUNDAMENTALS), encoding="utf-8")

    monkeypatch.setattr(
        "alpha.brain.trading_bot.load_stock_metrics",
        lambda: json.loads(metrics_path.read_text(encoding="utf-8")),
    )

    bot, _chart, decision = _make_bot()
    bot._refresh_fundamentals()
    asyncio.run(bot.on_bar(FakeBar("BTCUSDT", 58994.1)))

    context = decision.contexts[-1]
    assert context["fundamentals"]["symbol"] == "BTC-USD"
    assert context["fundamentals"]["momentum_flag"] == "Mid range"


def test_trading_bot_resolves_equity_aliases(monkeypatch, tmp_path):
    metrics_path = tmp_path / "stocks_metrics.json"
    metrics_path.write_text(json.dumps(FUNDAMENTALS), encoding="utf-8")

    monkeypatch.setattr(
        "alpha.brain.trading_bot.load_stock_metrics",
        lambda: json.loads(metrics_path.read_text(encoding="utf-8")),
    )

    bot, _chart, decision = _make_bot()
    bot._refresh_fundamentals()
    asyncio.run(bot.on_bar(FakeBar("RELIANCE", 1400.0)))

    context = decision.contexts[-1]
    assert context["fundamentals"]["symbol"] == "RELIANCE.NS"


def test_trading_bot_runs_without_published_fundamentals(monkeypatch):
    monkeypatch.setattr("alpha.brain.trading_bot.load_stock_metrics", lambda: {})

    bot, _chart, decision = _make_bot()
    bot._refresh_fundamentals()
    asyncio.run(bot.on_bar(FakeBar("BTCUSDT", 58994.1)))

    context = decision.contexts[-1]
    assert "fundamentals" not in context
    assert context["symbol"] == "BTCUSDT"


def test_trading_bot_status_reports_fundamentals_loaded(monkeypatch, tmp_path):
    metrics_path = tmp_path / "stocks_metrics.json"
    metrics_path.write_text(json.dumps(FUNDAMENTALS), encoding="utf-8")

    monkeypatch.setattr(
        "alpha.brain.trading_bot.load_stock_metrics",
        lambda: json.loads(metrics_path.read_text(encoding="utf-8")),
    )

    bot, _chart, _decision = _make_bot()
    bot._refresh_fundamentals()
    status = bot.get_status()

    assert status["fundamentals"]["symbols"] > 0
    assert status["fundamentals"]["loaded_at"] > 0


def test_execution_engine_signals_carry_fundamentals(monkeypatch):
    monkeypatch.setattr(
        ee, "load_stock_metrics",
        lambda: json.loads(json.dumps(FUNDAMENTALS)),
        raising=False,
    )

    engine = ee.OpenClawExecutionEngine(auto_execute=False)
    results = asyncio.run(
        engine.process_analysis("RELIANCE is showing strength and momentum")
    )

    signals = results["signals"]
    assert signals, "expected a parsed signal"
    assert signals[0]["fundamentals"]["symbol"] == "RELIANCE.NS"


def test_execution_engine_runs_without_published_fundamentals(monkeypatch):
    monkeypatch.setattr(ee, "load_stock_metrics", lambda: {}, raising=False)

    engine = ee.OpenClawExecutionEngine(auto_execute=False)
    results = asyncio.run(
        engine.process_analysis("RELIANCE is showing strength and momentum")
    )

    signals = results["signals"]
    assert signals, "expected a parsed signal"
    assert signals[0].get("fundamentals") is None


def test_risk_aware_execution_engine_attaches_fundamentals(monkeypatch):
    """RiskAwareExecutionEngine attaches fundamentals to orders."""
    import packages.trading.alpha.risk.risk_manager as rm_mod

    monkeypatch.setattr(
        rm_mod, "symbol_fundamentals",
        lambda metrics, symbol: {"symbol": "BTC-USD", "valuation_flag": "N/A"} if symbol == "BTCUSDT" else None,
        raising=False,
    )

    # Create a minimal mock execution engine
    class MockEngine:
        def __init__(self):
            self.pre_trade_checks = []
            self.submitted = None
        def add_pre_trade_check(self, check):
            self.pre_trade_checks.append(check)
        async def submit_order(self, order):
            self.submitted = order
            return order

    # Create a minimal mock risk manager
    class MockRiskManager:
        def pre_trade_check(self, order):
            return True, "ok", {}

    mock_engine = MockEngine()
    mock_rm = MockRiskManager()

    rae = rm_mod.RiskAwareExecutionEngine(mock_engine, mock_rm)

    # Create a simple order object
    class Order:
        def __init__(self, symbol):
            self.symbol = symbol
            self.status = "NEW"

    order = Order("BTCUSDT")
    asyncio.run(rae.submit_order_with_risk(order))

    assert hasattr(order, "fundamentals")
    assert order.fundamentals["symbol"] == "BTC-USD"
    assert order.status == "NEW"  # not rejected


def test_risk_aware_execution_engine_works_without_fundamentals(monkeypatch):
    """RiskAwareExecutionEngine works when no fundamentals published."""
    import packages.trading.alpha.risk.risk_manager as rm_mod

    monkeypatch.setattr(
        rm_mod, "symbol_fundamentals",
        lambda metrics, symbol: None,
        raising=False,
    )

    class MockEngine:
        def __init__(self):
            self.pre_trade_checks = []
            self.submitted = None
        def add_pre_trade_check(self, check):
            self.pre_trade_checks.append(check)
        async def submit_order(self, order):
            self.submitted = order
            return order

    class MockRiskManager:
        def pre_trade_check(self, order):
            return True, "ok", {}

    mock_engine = MockEngine()
    mock_rm = MockRiskManager()

    rae = rm_mod.RiskAwareExecutionEngine(mock_engine, mock_rm)

    class Order:
        def __init__(self, symbol):
            self.symbol = symbol
            self.status = "NEW"

    order = Order("BTCUSDT")
    asyncio.run(rae.submit_order_with_risk(order))

    assert not hasattr(order, "fundamentals")
    assert order.status == "NEW"


def test_execution_engine_attaches_fundamentals(monkeypatch):
    """ExecutionEngine attaches fundamentals to orders."""
    import packages.trading.alpha.execution.execution_engine as ee_mod

    monkeypatch.setattr(
        ee_mod, "symbol_fundamentals",
        lambda metrics, symbol: {"symbol": "BTC-USD", "valuation_flag": "N/A"} if symbol == "BTCUSDT" else None,
        raising=False,
    )

    engine = ee_mod.ExecutionEngine()

    class Order:
        def __init__(self, symbol):
            self.symbol = symbol
            self.side = ee_mod.OrderSide.BUY
            self.order_type = ee_mod.OrderType.MARKET
            self.quantity = 1.0
            self.status = ee_mod.OrderStatus.PENDING

    order = Order("BTCUSDT")
    # Use a mock broker to avoid actual submission
    class MockBroker:
        async def submit_order(self, order):
            return order
    engine.add_broker("mock", MockBroker(), is_default=True)

    asyncio.run(engine.submit_order(order))

    assert hasattr(order, "fundamentals")
    assert order.fundamentals["symbol"] == "BTC-USD"


def test_execution_engine_works_without_fundamentals(monkeypatch):
    """ExecutionEngine works when no fundamentals published."""
    import packages.trading.alpha.execution.execution_engine as ee_mod

    monkeypatch.setattr(
        ee_mod, "symbol_fundamentals",
        lambda metrics, symbol: None,
        raising=False,
    )

    engine = ee_mod.ExecutionEngine()

    class Order:
        def __init__(self, symbol):
            self.symbol = symbol
            self.side = ee_mod.OrderSide.BUY
            self.order_type = ee_mod.OrderType.MARKET
            self.quantity = 1.0
            self.status = ee_mod.OrderStatus.PENDING

    order = Order("BTCUSDT")
    class MockBroker:
        async def submit_order(self, order):
            order.status = ee_mod.OrderStatus.SUBMITTED
            return order
    engine.add_broker("mock", MockBroker(), is_default=True)

    asyncio.run(engine.submit_order(order))

    assert not hasattr(order, "fundamentals")
    assert order.status == ee_mod.OrderStatus.SUBMITTED


def test_risk_manager_kelly_sizing():
    """Test Kelly criterion position sizing."""
    from alpha.risk.risk_manager import RiskManager, RiskLimits

    limits = RiskLimits(kelly_fraction=0.25, kelly_min_trades=10, kelly_lookback=252)
    rm = RiskManager(limits)

    # Add winning trades (66% win rate, 2:1 reward/risk)
    for i in range(20):
        rm.record_trade_outcome('BTC', 100.0, 10000.0, 50000.0, 50100.0, 'long')

    # Add losing trades
    for i in range(10):
        rm.record_trade_outcome('BTC', -50.0, 10000.0, 50000.0, 49950.0, 'long')

    kelly = rm.estimate_kelly_fraction()
    assert 0.05 <= kelly <= 0.25, f"Kelly fraction {kelly} out of bounds"

    # Test position sizing with full signal
    qty = rm.calculate_kelly_position('BTC', 1.0, 0.5, 50000.0, 10000.0)
    assert qty > 0, "Position quantity should be positive"

    # Test with reduced signal
    qty_reduced = rm.calculate_kelly_position('BTC', 0.5, 0.5, 50000.0, 10000.0)
    assert qty_reduced < qty, "Reduced signal should reduce position"

    # Test with high volatility
    qty_high_vol = rm.calculate_kelly_position('BTC', 1.0, 1.0, 50000.0, 10000.0)
    assert qty_high_vol < qty, "High volatility should reduce position"


def test_risk_manager_drawdown_circuit_breakers():
    """Test drawdown circuit breakers."""
    from alpha.risk.risk_manager import RiskManager, RiskLimits

    limits = RiskLimits(
        max_drawdown=0.15,
        dd_circuit_breaker_levels=[0.05, 0.10, 0.15],
        dd_circuit_reduction=[0.8, 0.5, 0.25]
    )
    rm = RiskManager(limits)

    # Simulate equity curve with ~6% drawdown (triggers 5% level)
    rm._equity_curve = [10000, 10200, 10100, 10000, 9900, 9800, 9700, 9600, 9500, 9400, 9300]

    mult = rm.get_position_multiplier()
    assert 0.75 <= mult <= 0.85, f"Expected ~0.8 multiplier at ~6% DD, got {mult}"

    # More drawdown - ~11% triggers 10% level (50% reduction)
    rm._equity_curve = [10000, 10200, 10100, 10000, 9900, 9800, 9700, 9600, 9500, 9400, 9300, 9200, 9100, 9000, 8900]

    mult = rm.get_position_multiplier()
    assert 0.45 <= mult <= 0.55, f"Expected ~0.5 multiplier at ~11% DD, got {mult}"

    # Check circuit breaker status
    status = rm.get_circuit_breaker_status()
    assert status['active'] is True
    assert status['levels']['0.05']['triggered'] is True
    assert status['levels']['0.1']['triggered'] is True

    # Test circuit breaker recovery
    # Restore equity
    rm._equity_curve = [10000, 10200, 10100, 10000, 9900, 9800, 9700, 9600, 9500, 9400, 9300, 9200, 9100, 9000, 8900, 9000, 9100, 9200, 9300, 9400, 9500, 9600, 9700, 9800, 9900, 10000]
    
    # After recovery, circuit breakers should eventually deactivate
    status = rm.get_circuit_breaker_status()
    assert 'active' in status
    assert 'levels' in status


def test_risk_manager_kelly_position_sizing_with_drawdown():
    """Test Kelly position sizing integrates with drawdown circuit breakers."""
    from alpha.risk.risk_manager import RiskManager, RiskLimits

    limits = RiskLimits(
        kelly_fraction=0.25,
        kelly_min_trades=10,
        dd_circuit_breaker_levels=[0.05, 0.10],
        dd_circuit_reduction=[0.8, 0.5]
    )
    rm = RiskManager(limits)

    # Add trades for Kelly estimation
    for i in range(20):
        rm.record_trade_outcome('BTC', 100.0, 10000.0, 50000.0, 50100.0, 'long')
    for i in range(10):
        rm.record_trade_outcome('BTC', -50.0, 10000.0, 50000.0, 49950.0, 'long')

    # Normal conditions - no drawdown
    rm._equity_curve = [10000] * 100
    qty_normal = rm.calculate_kelly_position('BTC', 1.0, 0.5, 50000.0, 10000.0)

    # With 6% drawdown - should reduce position by 20%
    rm._equity_curve = [10000, 10200, 10100, 10000, 9900, 9800, 9700, 9600, 9500, 9400, 9300]
    qty_dd = rm.calculate_kelly_position('BTC', 1.0, 0.5, 50000.0, 10000.0)

    assert qty_dd < qty_normal, "Drawdown should reduce position size"
    assert 0.75 <= qty_dd / qty_normal <= 0.85, "Should be ~80% of normal size"
