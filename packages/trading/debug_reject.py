"""Debug script: trace PaperBroker rejection step by step."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from alpha.execution.execution_engine import (
    ExecutionEngine, PaperBroker, Order, OrderSide, OrderType,
    max_position_check, max_notional_check, daily_loss_limit_check,
)
from dost.trading.strategy_engine import generate_all_signals
from dost.trading.backtest_engine import run_backtest
from dost.trading.position_sizer import calculate_position_size
from dost.data_access import generate_synthetic_ohlcv

SYMBOL = "NIFTY"
capital = 100_000.0
risk_per_trade = 0.02
max_daily_loss = 20_000.0
max_position_per_symbol = 10_000.0
max_total_notional = 50_000.0
seed = 20

candles = generate_synthetic_ohlcv(symbol=SYMBOL, days=252, start_price=22000.0,
                                   volatility=0.015, drift=0.0003, seed=seed)
signals = generate_all_signals("dbg", SYMBOL, candles, confidence_threshold=0.0)
sig = signals[0]
entry = float(sig.get("entry_price", 0) or 0)
size = 50_000.0 / entry  # notional-capped size
print(f"SIGNAL entry={entry} direction={sig.get('direction')}")
print(f"size={size} notional={size*entry}")

order = Order(symbol=SYMBOL, side=OrderSide.BUY, order_type=OrderType.MARKET,
              quantity=size, price=entry)

# Check each pre-trade check individually
checks = {
    "max_position(10000)": max_position_check(max_position_per_symbol)(order),
    "max_notional(50000)": max_notional_check(max_total_notional)(order),
    "daily_loss(20000)": daily_loss_limit_check(max_daily_loss, lambda: 0.0)(order),
}
print("PRE-TRADE CHECKS:", checks)

# Fresh broker directly
broker = PaperBroker(name="paper", initial_balance=capital)
filled = asyncio.run(broker.submit_order(order))
print("BROKER DIRECT:", filled.status, "filled_qty=", filled.filled_qty)

# Fresh engine + fresh broker, submit ONCE
engine = ExecutionEngine()
broker2 = PaperBroker(name="paper", initial_balance=capital)
engine.add_broker("paper", broker2, is_default=True)
for name, fn in [("pos", max_position_check(max_position_per_symbol)),
                 ("notional", max_notional_check(max_total_notional)),
                 ("daily", daily_loss_limit_check(max_daily_loss, lambda: 0.0))]:
    engine.add_pre_trade_check(fn)
order2 = Order(symbol=SYMBOL, side=OrderSide.BUY, order_type=OrderType.MARKET,
               quantity=size, price=entry)
r = asyncio.run(engine.submit_order(order2))
print("ENGINE (fresh):", r.status, "filled_qty=", r.filled_qty)
print("broker2 balances after:", broker2.balances)
