"""Paper execution venue for the best-signal bot.

The venue is the only place where a paper target becomes a position. It
refuses any broker whose ``paper_trading`` flag is off before a single order
is built, so the bot can never reach a live venue.

Cash follows standard broker accounting (a buy debits cash, a sell credits
it), the perp leg reserves margin, and every fill pays the research model's
5 bps per leg so the paper book costs the same as the out-of-sample harness.
The spot leg is treated as outright: the short spot's borrow requirement is
not modelled here and stays a separate cost line in the research harness.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from alpha.execution.execution_engine import (
    ExecutionEngine,
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperBroker,
    Position,
)
from best_signal.fill_journal import FillJournal, record_fill
from best_signal.funding import DEFAULT_DATA_DIR
from risk import LimitStatus, RiskGovernor
from risk import RiskLimits as GovernorLimits

DEFAULT_FEE = 0.0005
DEFAULT_MARGIN_RATIO = 0.10
MODE_PAPER = "PAPER"

ACTION_OPEN = "OPEN"
ACTION_HOLD = "HOLD"
ACTION_FLIP = "FLIP"
ACTION_CLOSE = "CLOSE"
ACTION_NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class ExecutionRealismConfig:
    """Execution realism applied to paper fills (paper mode only).

    Slippage is applied against the direction of the trade: a buy fills at a
    higher price, a sell at a lower price. Partial fills are deterministic ---
    a fixed fraction of the order quantity fills --- so runs stay reproducible.
    Latency is a fixed sleep per market order and never reaches a live venue.
    All defaults are zero, so existing behaviour is preserved exactly.
    """

    slippage_bps: float = 0.0
    latency_ms: float = 0.0
    partial_fill_enabled: bool = False
    partial_fill_fraction: float = 0.5


@dataclass(frozen=True)
class Leg:
    """One side of a carry: a spot leg or its perp counterpart."""

    symbol: str
    market: str
    side: str
    quantity: float
    price: float
    notional: float


@dataclass(frozen=True)
class ExecutionResult:
    """What the venue did with one target."""

    symbol: str
    action: str
    legs: tuple
    fees: float
    filled: bool
    reason: str
    mode: str = MODE_PAPER
    live: bool = False
    partial: bool = False


class LiveVenueRefused(RuntimeError):
    """Raised when a venue that is not paper-only is handed to the bot."""


class CarryPaperBroker(PaperBroker):
    """Paper broker for a delta-flat carry: one spot leg plus one perp leg."""

    def __init__(
        self,
        name: str = "paper",
        initial_balance: float = 100_000.0,
        commission_rate: float = DEFAULT_FEE,
        margin_ratio: float = DEFAULT_MARGIN_RATIO,
        realism: Optional[ExecutionRealismConfig] = None,
        fill_journal: Optional[FillJournal] = None,
    ):
        super().__init__(name=name, initial_balance=initial_balance)
        self.balances = {"USDT": float(initial_balance)}
        self.commission_rate = commission_rate
        self.margin_ratio = margin_ratio
        self.margin_used: Dict[str, float] = {}
        self.fees_total = 0.0
        self.realized_pnl: Dict[str, float] = {}
        self.realism = realism or ExecutionRealismConfig()
        self.slippage_bps = self.realism.slippage_bps
        self.latency_ms = self.realism.latency_ms
        self.partial_fill_enabled = self.realism.partial_fill_enabled
        self.partial_fill_fraction = self.realism.partial_fill_fraction
        self.fill_journal = fill_journal

    @property
    def free_cash(self) -> float:
        """Cash left after the margin the open perp legs reserve."""
        return self.balances.get("USDT", 0.0) - sum(self.margin_used.values())

    def _check_balance(self, order: Order) -> bool:
        price = order.price or self.get_market_price(order.symbol) or 0.0
        notional = order.quantity * price
        if order.side == OrderSide.BUY:
            return self.balances.get("USDT", 0.0) >= notional * 1.01
        position = self.positions.get(order.symbol)
        held = position.quantity if position else 0.0
        if held >= order.quantity - 1e-8:
            return True
        return self.free_cash >= self.margin_ratio * notional * 1.01

    async def _execute_market(self, order: Order):
        price = order.price or self.get_market_price(order.symbol)
        if not price:
            order.status = OrderStatus.REJECTED
            await self._update_order(order)
            return

        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000.0)

        # Slippage fills against the direction of the trade: a buy prints a
        # higher price, a sell a lower price.
        fill_price = price
        if self.slippage_bps:
            if order.side == OrderSide.BUY:
                fill_price = price * (1 + self.slippage_bps / 10_000.0)
            else:
                fill_price = price * (1 - self.slippage_bps / 10_000.0)

        position = self.positions.get(order.symbol)
        prev_qty = position.quantity if position else 0.0
        prev_avg = position.avg_entry_price if position else 0.0

        fill_qty = order.quantity
        if self.partial_fill_enabled and not getattr(order, "fill_fully", False):
            fill_qty = order.quantity * self.partial_fill_fraction

        fill = Fill(
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            commission=fill_qty * fill_price * self.commission_rate,
            timestamp=time.time(),
            exchange_fill_id=f"paper_{uuid.uuid4().hex[:8]}",
        )
        await self._process_fill(fill)

        # After processing fill, record to journal if attached
        if self.fill_journal is not None:
            record_fill(self.fill_journal, fill, order, self)

        if order.side == OrderSide.BUY:
            self.balances["USDT"] -= fill_qty * fill_price + fill.commission
        else:
            self.balances["USDT"] += fill_qty * fill_price - fill.commission
        self.fees_total += fill.commission
        self._book_realized_pnl(order.symbol, prev_qty, prev_avg, fill)
        self._recompute_margin()

    def _book_realized_pnl(
        self, symbol: str, prev_qty: float, prev_avg: float, fill: Fill
    ) -> None:
        """Realised P&L on the closed part of a fill, signed by the old side."""
        if abs(prev_qty) <= 1e-12:
            return
        position = self.positions.get(symbol)
        new_qty = position.quantity if position else 0.0
        if prev_qty * new_qty > 0:
            return
        closed_qty = min(abs(prev_qty), abs(fill.quantity))
        direction = 1.0 if prev_qty > 0 else -1.0
        total = self.realized_pnl.get(symbol, 0.0) + (
            (fill.price - prev_avg) * closed_qty * direction
        )
        self.realized_pnl[symbol] = total
        if position is not None:
            position.realized_pnl = total

    def _recompute_margin(self) -> None:
        margin: Dict[str, float] = {}
        for symbol, position in self.positions.items():
            if not symbol.endswith("_PERP"):
                continue
            if abs(position.quantity) <= 1e-12:
                continue
            required = (
                abs(position.quantity)
                * position.avg_entry_price
                * self.margin_ratio
            )
            margin[symbol] = round(required, 8)
        self.margin_used = margin


def perp_symbol(symbol: str) -> str:
    """The perp counterpart of a spot symbol."""
    return f"{symbol}_PERP"


def legs_for_target(
    symbol: str, side: int, notional: float, price: float
) -> Tuple[Leg, ...]:
    """The two legs of a delta-flat carry for one target side.

    Side +1 is long spot plus short perp; side -1 is short spot plus long
    perp. Both legs carry the same notional, so the book is delta-flat.
    """
    quantity = (notional / price) if price else 0.0
    spot_side = "buy" if side >= 0 else "sell"
    perp_side = "sell" if side >= 0 else "buy"
    return (
        Leg(
            symbol=symbol,
            market="spot",
            side=spot_side,
            quantity=quantity,
            price=price,
            notional=notional,
        ),
        Leg(
            symbol=perp_symbol(symbol),
            market="perp",
            side=perp_side,
            quantity=quantity,
            price=price,
            notional=notional,
        ),
    )


def risk_limits_for(bot_limits, equity: float) -> GovernorLimits:
    """Map the bot's own caps onto the repo's risk governor limits.

    A carry is two legs, so the gross exposure of one symbol is twice its
    per-leg notional; the governor must see that gross, not the net.
    """
    max_symbol_exposure = (
        2.0 * bot_limits.max_symbol_notional / equity if equity > 0 else 0.0
    )
    max_total_exposure = (
        2.0 * bot_limits.max_gross_notional / equity if equity > 0 else 0.0
    )
    return GovernorLimits(
        min_confidence=0.0,
        max_notional_pct=1.0,
        max_notional_abs=bot_limits.max_symbol_notional,
        max_symbol_exposure_pct=max_symbol_exposure,
        max_total_exposure_pct=max_total_exposure,
        max_open_positions=bot_limits.max_symbols + 1,
        max_daily_loss_pct=bot_limits.max_daily_loss_pct,
        start_of_day_equity=equity,
        high_water_mark=equity,
    )


def approve_target(
    governor: RiskGovernor,
    symbol: str,
    gross_notional: float,
    equity: float,
    per_leg_notional: Optional[float] = None,
    positions: Optional[dict] = None,
) -> Tuple[bool, Optional[str]]:
    """Check a projected book against the governor and commit it on a pass.

    On a failure the governor's book is left exactly as it was, so a
    rejected target leaves no exposure behind.
    """
    previous = dict(governor.limits.positions)
    if positions is None:
        projected = dict(previous)
        projected[symbol] = {
            "quantity": 0.0,
            "avg_entry_price": 0.0,
            "gross_notional": float(gross_notional),
        }
    else:
        projected = {key: dict(value) for key, value in positions.items()}
    governor.limits.positions = projected

    notional = (
        per_leg_notional
        if per_leg_notional is not None
        else float(gross_notional) / 2.0
    )
    status, reason = governor.check_all(
        confidence=1.0,
        symbol=symbol,
        notional=notional,
        equity=equity,
    )
    if status != LimitStatus.PASS:
        governor.limits.positions = previous
        return False, reason
    return True, None


def build_paper_venue(
    equity: float,
    name: str = "paper",
    realism: Optional[ExecutionRealismConfig] = None,
    fill_journal: Optional[FillJournal] = None,
):
    """Build a paper venue funded for one carry plus its margin."""
    balance = round(equity * (1 + DEFAULT_MARGIN_RATIO) * 1.01, 8)
    broker = CarryPaperBroker(
        name=name, initial_balance=balance, realism=realism, fill_journal=fill_journal
    )
    engine = ExecutionEngine()
    engine.add_broker(name, broker, is_default=True)
    return engine, broker


def venue_snapshot(broker) -> dict:
    """The venue's state, in a form that can be written to disk and restored."""
    return {
        "cash": broker.balances.get("USDT", 0.0),
        "positions": {
            symbol: {
                "quantity": position.quantity,
                "avg_entry_price": position.avg_entry_price,
                "realized_pnl": position.realized_pnl,
            }
            for symbol, position in sorted(broker.positions.items())
        },
        "margin_used": dict(sorted(broker.margin_used.items())),
        "fees_total": broker.fees_total,
        "realized_pnl_total": sum(broker.realized_pnl.values()),
        "paper_trading": bool(broker.paper_trading),
        "live": False,
        "mode": MODE_PAPER,
    }


def restore_venue(broker, snapshot: dict) -> None:
    """Restore a venue from a snapshot taken by :func:`venue_snapshot`."""
    broker.balances["USDT"] = float(
        snapshot.get("cash", broker.balances.get("USDT", 0.0))
    )
    broker.positions = {}
    broker.realized_pnl = {}
    for symbol, data in (snapshot.get("positions") or {}).items():
        realized = float(data.get("realized_pnl", 0.0))
        broker.positions[symbol] = Position(
            symbol=symbol,
            quantity=float(data.get("quantity", 0.0)),
            avg_entry_price=float(data.get("avg_entry_price", 0.0)),
            realized_pnl=realized,
        )
        broker.realized_pnl[symbol] = realized
    broker.margin_used = {
        symbol: float(value)
        for symbol, value in (snapshot.get("margin_used") or {}).items()
    }
    broker.fees_total = float(snapshot.get("fees_total", 0.0))


def load_price_at(symbol: str, ts_ms: int, data_dir=None) -> Tuple[float, str]:
    """The last 15m close at or before ``ts_ms``.

    Falls back to a unit price so a missing price file degrades the run
    instead of aborting it; the source is reported so the fallback is
    visible in the artifacts.
    """
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    path = root / f"{symbol}_15m.parquet"
    if not path.is_file():
        return 1.0, "notional_unit"
    frame = pd.read_parquet(path)
    if "open_time" not in frame.columns or "close" not in frame.columns:
        return 1.0, "notional_unit"
    bars = frame[frame["open_time"] <= ts_ms].sort_values("open_time")
    if bars.empty:
        return 1.0, "notional_unit"
    return float(bars["close"].iloc[-1]), "15m_close"


def _drive(coro):
    """Run an engine coroutine from synchronous code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    outcome: Dict[str, object] = {}

    def worker() -> None:
        outcome["value"] = asyncio.run(coro)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    if "value" not in outcome:
        raise RuntimeError("paper execution did not complete")
    return outcome["value"]


def _close_legs(
    broker, symbol: str, price: float, current_notional: float, current_side: int
) -> Tuple[Leg, ...]:
    """The legs that flatten the venue's current carry."""
    perp = perp_symbol(symbol)
    spot_position = broker.positions.get(symbol)
    perp_position = broker.positions.get(perp)
    if spot_position is not None and perp_position is not None:
        spot_qty = abs(spot_position.quantity)
        perp_qty = abs(perp_position.quantity)
        spot_side = "sell" if spot_position.quantity > 0 else "buy"
        perp_side = "buy" if perp_position.quantity < 0 else "sell"
    else:
        quantity = (current_notional / price) if price else 0.0
        spot_qty = perp_qty = quantity
        spot_side = "sell" if current_side >= 0 else "buy"
        perp_side = "buy" if current_side >= 0 else "sell"
    return (
        Leg(
            symbol=symbol,
            market="spot",
            side=spot_side,
            quantity=spot_qty,
            price=price,
            notional=spot_qty * price,
        ),
        Leg(
            symbol=perp,
            market="perp",
            side=perp_side,
            quantity=perp_qty,
            price=price,
            notional=perp_qty * price,
        ),
    )


def _submit_leg(engine, leg: Leg, fill_fully: bool = False) -> Order:
    order = Order(
        symbol=leg.symbol,
        side=OrderSide.BUY if leg.side == "buy" else OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=leg.quantity,
        price=leg.price,
    )
    if fill_fully:
        # Rollback legs must fill fully: a rollback may never leave a
        # half-carry behind, even when partial fills are enabled.
        order.fill_fully = True
    return _drive(engine.submit_order(order))


def _rollback(engine, filled_legs: List[Leg]) -> List[Order]:
    """Reverse the legs that already filled so no half-carry is left open.

    Every reversal fills fully: a rollback must never leave a half-carry
    behind, even when partial fills are enabled.
    """
    orders = []
    for leg in reversed(filled_legs):
        reverse = Leg(
            symbol=leg.symbol,
            market=leg.market,
            side="sell" if leg.side == "buy" else "buy",
            quantity=leg.quantity,
            price=leg.price,
            notional=leg.notional,
        )
        orders.append(_submit_leg(engine, reverse, fill_fully=True))
    return orders


def _keep_flat_legs(broker, legs: List[Leg]) -> None:
    """Leave an explicit flat record for every leg the venue touched.

    A leg that was rejected never created a position, so the book would
    otherwise hide one half of the carry it just refused to open.
    """
    for leg in legs:
        if leg.symbol in broker.positions:
            continue
        broker.positions[leg.symbol] = Position(
            symbol=leg.symbol,
            quantity=0.0,
            avg_entry_price=0.0,
        )


def run_paper_execution(
    engine,
    broker,
    symbol: str,
    side: int,
    notional: float,
    price: float,
    equity: float,
    governor: Optional[RiskGovernor] = None,
    action: str = ACTION_OPEN,
    current_side: int = 0,
    current_notional: float = 0.0,
) -> ExecutionResult:
    """Turn one target into paper fills, or refuse to trade at all."""
    if not getattr(broker, "paper_trading", False):
        raise LiveVenueRefused(
            f"broker {getattr(broker, 'name', 'unknown')} is not paper-only; "
            "the bot refuses to send an order to it"
        )

    if action == ACTION_NO_TRADE:
        return ExecutionResult(
            symbol=symbol,
            action=action,
            legs=(),
            fees=0.0,
            filled=True,
            reason="stand_down",
        )
    if action == ACTION_HOLD:
        return ExecutionResult(
            symbol=symbol,
            action=action,
            legs=(),
            fees=0.0,
            filled=True,
            reason="held",
        )

    governor_snapshot = None
    if action in (ACTION_OPEN, ACTION_FLIP) and governor is not None:
        governor_snapshot = {k: dict(v) for k, v in governor.limits.positions.items()}
        approved, reason = approve_target(
            governor,
            symbol,
            2.0 * notional,
            equity,
            per_leg_notional=notional,
        )
        if not approved:
            return ExecutionResult(
                symbol=symbol,
                action=action,
                legs=(),
                fees=0.0,
                filled=False,
                reason=reason or "risk_rejected",
            )

    legs: List[Leg] = []
    if action == ACTION_CLOSE:
        legs.extend(_close_legs(broker, symbol, price, current_notional, current_side))
    elif action == ACTION_FLIP:
        legs.extend(_close_legs(broker, symbol, price, current_notional, current_side))
        legs.extend(legs_for_target(symbol, side, notional, price))
    else:
        legs.extend(legs_for_target(symbol, side, notional, price))

    orders: List[Order] = []
    filled_legs: List[Leg] = []
    for leg in legs:
        order = _submit_leg(engine, leg)
        orders.append(order)
        if order.status != OrderStatus.FILLED:
            rollback_orders = _rollback(engine, filled_legs)
            if order.filled_qty > 0:
                # A partial fill reached the venue: reverse it so the
                # rollback leaves the book flat instead of a half-carry.
                reverse = Leg(
                    symbol=leg.symbol,
                    market=leg.market,
                    side="sell" if leg.side == "buy" else "buy",
                    quantity=order.filled_qty,
                    price=order.avg_fill_price or leg.price,
                    notional=order.filled_qty * (order.avg_fill_price or leg.price),
                )
                rollback_orders.append(_submit_leg(engine, reverse, fill_fully=True))
            _keep_flat_legs(broker, legs)
            if governor_snapshot is not None and governor is not None:
                governor.limits.positions = governor_snapshot
            fees = sum(item.commission for item in orders)
            fees += sum(item.commission for item in rollback_orders)
            return ExecutionResult(
                symbol=symbol,
                action="ROLLED_BACK",
                legs=tuple(filled_legs),
                fees=fees,
                filled=False,
                partial=order.filled_qty > 0,
                reason=(
                    f"partial_fill:{leg.symbol}"
                    if order.status == OrderStatus.PARTIAL
                    else f"leg_rejected:{leg.symbol}"
                ),
            )
        filled_legs.append(leg)

    result = ExecutionResult(
        symbol=symbol,
        action=action,
        legs=tuple(legs),
        fees=sum(item.commission for item in orders),
        filled=True,
        reason="filled",
        partial=False,
    )

    if action == ACTION_CLOSE and governor is not None and result.filled:
        governor.limits.positions.pop(symbol, None)

    return result
