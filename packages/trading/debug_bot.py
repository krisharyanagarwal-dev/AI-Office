"""Replicate AllInOneBot exactly to find the rejection cause."""
import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from alpha.execution.execution_engine import (
    ExecutionEngine, PaperBroker, Order, OrderSide, OrderType,
    max_position_check, max_notional_check, daily_loss_limit_check,
)
from alpha.brain.state_store import StateStore
from alpha.risk.risk_manager import RiskLimits
from dost.trading.strategy_engine import generate_all_signals
from dost.trading.backtest_engine import run_backtest
from dost.trading.position_sizer import calculate_position_size
from dost.data_access import generate_synthetic_ohlcv

SYMBOL = "NIFTY"
capital = 100_000.0
config_capital = capital
risk_per_trade = 0.02
max_daily_loss = 20_000.0
max_drawdown = 0.10
max_position_per_symbol = 10_000.0
max_total_notional = 50_000.0
symbols = ["NIFTY"]
days = 252
seed = 20
confidence_threshold = 0.0
state_db_path = "./data/all_in_one_state.db"

run_id = f"aio-{uuid.uuid4().hex[:8]}"
started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")

state_store = StateStore({"path": state_db_path})
engine = ExecutionEngine()
broker = PaperBroker(name="paper", initial_balance=config_capital)
engine.add_broker("paper", broker, is_default=True)

limits = RiskLimits(
    max_position_per_symbol=max_position_per_symbol,
    max_total_notional=max_total_notional,
    max_daily_loss=max_daily_loss,
    max_drawdown=max_drawdown,
)
risk_manager = None

engine.add_pre_trade_check(max_position_check(max_position_per_symbol))
engine.add_pre_trade_check(max_notional_check(max_total_notional))


def _daily_pnl():
    try:
        summary = engine.get_portfolio_summary()
        return float(summary.get("total_pnl", 0.0))
    except Exception:
        return 0.0


engine.add_pre_trade_check(daily_loss_limit_check(max_daily_loss, _daily_pnl))
engine.set_state_store(state_store)

candles = generate_synthetic_ohlcv(symbol=SYMBOL, days=days, start_price=22000.0,
                                   volatility=0.015, drift=0.0003, seed=seed)
signals = generate_all_signals("all-in-one-bot", SYMBOL, candles,
                               confidence_threshold=confidence_threshold)
sig = signals[0]
print("SIGNAL:", {k: sig.get(k) for k in ("direction", "entry_price", "stop_loss", "confidence")})

bt = run_backtest(signal=sig, candles=candles, initial_capital=capital,
                  risk_per_trade=risk_per_trade)
print("BACKTEST:", bt.get("status"), bt.get("total_return_pct"))

pos = calculate_position_size(
    agent_id="all-in-one-bot", instrument=SYMBOL, direction=sig["direction"],
    signal_confidence=float(sig.get("confidence", 0.5)),
    entry_price=float(sig.get("entry_price", 0) or 0),
    stop_loss=sig.get("stop_loss"), cost_units=1, method="fixed_fraction",
    capital=capital, risk_per_trade=risk_per_trade,
)
entry = float(pos.get("entry_price", 0) or 0)
size = float(pos.get("position_size", 0) or 0)
if size > 0 and entry > 0:
    max_qty_by_notional = max_total_notional / entry
    size = min(size, max_qty_by_notional, max_position_per_symbol)
    pos["position_size"] = round(size, 6)
    pos["position_value"] = round(size * entry, 2)
print("POSITION:", pos.get("position_size"), pos.get("position_value"))

direction = sig["direction"].lower()
side = OrderSide.BUY if direction == "long" else OrderSide.SELL
order = Order(
    symbol=SYMBOL, side=side, order_type=OrderType.MARKET,
    quantity=pos.get("position_size"), price=float(sig.get("entry_price", 0) or 0),
    metadata={"run_id": run_id, "signal_id": sig.get("task_id"),
              "strategy": sig.get("strategy_name"), "paper_only": True},
)
print("ORDER qty=", order.quantity, "price=", order.price)

# Replicate each check result
for chk in engine.pre_trade_checks:
    print("check:", chk(order))

filled = asyncio.run(engine.submit_order(order))
print("RESULT:", filled.status, "filled_qty=", filled.filled_qty, "avg_px=", filled.avg_fill_price)
print("broker balances:", broker.balances)

asyncio.run(state_store.close())
