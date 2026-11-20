"""
Order Execution Engine
Supports paper trading and live trading with multiple brokers
"""
import asyncio
import uuid
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from collections import defaultdict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TWAP = "twap"
    VWAP = "vwap"
    ICEBERG = "iceberg"


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(Enum):
    GTC = "gtc"          # Good Till Cancelled
    IOC = "ioc"          # Immediate or Cancel
    FOK = "fok"          # Fill or Kill
    GTD = "gtd"          # Good Till Date
    DAY = "day"          # Day order


@dataclass
class Order:
    """Order representation"""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.GTC
    client_order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    exchange_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    commission: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)
    
    @property
    def remaining_qty(self) -> float:
        return self.quantity - self.filled_qty
    
    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL)
    
    @property
    def is_terminal(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED)


@dataclass
class Fill:
    """Trade fill"""
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    commission: float
    timestamp: float
    exchange_fill_id: str
    liquidity: str = "unknown"  # maker, taker, unknown


@dataclass
class Position:
    """Position tracking"""
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    updated_at: float = field(default_factory=time.time)
    
    @property
    def is_long(self) -> bool:
        return self.quantity > 0
    
    @property
    def is_short(self) -> bool:
        return self.quantity < 0
    
    @property
    def is_flat(self) -> bool:
        return self.quantity == 0


class BaseBroker(ABC):
    """Abstract base class for brokers"""
    
    def __init__(self, name: str, paper_trading: bool = True):
        self.name = name
        self.paper_trading = paper_trading
        self.orders: Dict[str, Order] = {}
        self.fills: List = []
        self.positions: Dict[str, Position] = {}
        
        # Callbacks
        self.on_order_update: Optional[Callable[[Order], None]] = None
        self.on_fill: Optional[Callable[[Fill], None]] = None
        self.on_position_update: Optional[Callable[[Position], None]] = None
    
    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """Submit order to exchange"""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order"""
        pass
    
    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get order status"""
        pass
    
    @abstractmethod
    async def get_positions(self) -> Dict[str, Position]:
        """Get current positions"""
        pass
    
    @abstractmethod
    async def get_balances(self) -> Dict[str, float]:
        """Get account balances"""
        pass
    
    async def _update_order(self, order: Order):
        """Update order and trigger callbacks"""
        order.updated_at = time.time()
        self.orders[order.client_order_id] = order
        if self.on_order_update:
            try:
                self.on_order_update(order)
            except Exception as e:
                logger.error(f"Order update callback error: {e}")
    
    async def _process_fill(self, fill: Fill):
        """Process fill and update position"""
        order = self.orders.get(fill.order_id)
        if not order:
            logger.warning(f"Fill for unknown order: {fill.order_id}")
            return
        
        # Update order
        order.filled_qty += fill.quantity
        total_value = order.avg_fill_price * (order.filled_qty - fill.quantity) + fill.price * fill.quantity
        order.avg_fill_price = total_value / order.filled_qty if order.filled_qty > 0 else 0
        order.commission += fill.commission
        
        if order.filled_qty >= order.quantity - 1e-8:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIAL
        
        await self._update_order(order)
        
        # Update position
        pos = self.positions.get(fill.symbol)
        if pos is None:
            pos = Position(symbol=fill.symbol)
            self.positions[fill.symbol] = pos
        side_mult = 1 if fill.side == OrderSide.BUY else -1
        prev_qty = pos.quantity
        pos.quantity += side_mult * fill.quantity
        
        if prev_qty == 0:
            pos.avg_entry_price = fill.price
        elif (prev_qty > 0 and pos.quantity > 0) or (prev_qty < 0 and pos.quantity < 0):
            # Same direction, update avg price
            pos.avg_entry_price = (
                (prev_qty * pos.avg_entry_price + fill.quantity * fill.price) / pos.quantity
            )
        else:
            # Direction change or flattening
            if pos.quantity == 0:
                pos.realized_pnl += (fill.price - pos.avg_entry_price) * prev_qty * side_mult
                pos.avg_entry_price = fill.price if pos.quantity != 0 else 0
            elif abs(pos.quantity) < abs(prev_qty):
                # Partial close
                realized = (fill.price - pos.avg_entry_price) * fill.quantity * side_mult
                pos.realized_pnl += realized
        
        pos.unrealized_pnl = 0  # Will be updated with mark price
        pos.updated_at = time.time()
        
        if self.on_position_update:
            try:
                self.on_position_update(pos)
            except Exception as e:
                logger.error(f"Position update callback error: {e}")
        
        if self.on_fill:
            try:
                self.on_fill(fill)
            except Exception as e:
                logger.error(f"Fill callback error: {e}")
        
        self.fills.append(fill)


class PaperBroker(BaseBroker):
    """Paper trading broker for simulation"""
    
    def __init__(self, name: str = "paper", initial_balance: float = 100000.0):
        super().__init__("paper", paper_trading=True)
        self.balances: Dict[str, float] = {"USDT": 100000.0}
        self._market_data: Dict[str, float] = {}  # symbol -> mid price
        self._slippage_model = None
        self._latency_ms = 10  # Simulated latency in ms
    
    def set_market_data(self, symbol: str, price: float):
        """Update market price for simulation"""
        self._market_data[uppercase(symbol)] = price
    
    def get_market_price(self, symbol: str) -> Optional[float]:
        return self._market_data.get(symbol.upper())
    
    def set_slippage_model(self, model: Callable[[str, float, float], float]):
        """Set slippage model: (symbol, qty, price) -> slippage"""
        self._slippage_model = model
    
    async def submit_order(self, order: Order) -> Order:
        order.status = OrderStatus.SUBMITTED
        await self._update_order(order)
        
        # Simulate network latency
        await asyncio.sleep(self._latency_ms / 1000)
        
        # Check balance
        if not self._check_balance(order):
            order.status = OrderStatus.REJECTED
            await self._update_order(order)
            return order
        
        # Simulate execution
        if order.order_type == OrderType.MARKET:
            await self._execute_market(order)
        elif order.order_type == OrderType.LIMIT:
            await self._handle_limit(order)
        else:
            order.status = OrderStatus.REJECTED
            await self._update_order(order)
        
        return order
    
    def _check_balance(self, order: Order) -> bool:
        if order.side == OrderSide.BUY:
            required = order.quantity * (order.price or self.get_market_price(order.symbol) or 0)
            return self.balances.get("USDT", 0) >= required * 1.01  # 1% buffer
        else:
            pos = self.positions.get(order.symbol, Position(symbol=order.symbol))
            return pos.quantity >= order.quantity
    
    async def _execute_market(self, order: Order):
        price = order.price or self.get_market_price(order.symbol)
        if not price:
            order.status = OrderStatus.REJECTED
            await self._update_order(order)
            return
        
        # Apply slippage
        if self._slippage_model:
            slippage = self._slippage_model(order.symbol, order.quantity, price)
            price *= (1 + slippage) if order.side == OrderSide.BUY else (1 - slippage)
        
        fill = Fill(
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            commission=order.quantity * price * 0.001,  # 0.1% commission
            timestamp=time.time(),
            exchange_fill_id=f"paper_{uuid.uuid4().hex[:8]}"
        )
        
        order.filled_qty = order.quantity
        order.avg_fill_price = price
        order.commission = fill.commission
        order.status = OrderStatus.FILLED
        
        await self._update_order(order)
        await self._process_fill(fill)
        
        # Update balances
        if order.side == OrderSide.BUY:
            self.balances["USDT"] -= order.quantity * price + fill.commission
        else:
            self.balances["USDT"] += order.quantity * price - fill.commission
    
    async def _handle_limit(self, order: Order):
        if not order.price:
            order.status = OrderStatus.REJECTED
            await self._update_order(order)
            return
        
        # Check if limit is immediately executable
        market_price = self.get_market_price(order.symbol) or order.price
        
        can_fill = (
            (order.side == OrderSide.BUY and market_price <= order.price) or
            (order.side == OrderSide.SELL and market_price >= order.price)
        )
        
        if can_fill:
            # Immediately fillable
            await self._execute_market(Order(
                symbol=order.symbol,
                side=order.side,
                order_type=OrderType.MARKET,
                quantity=order.quantity,
                client_order_id=order.client_order_id
            ))
        else:
            # Store as pending limit order
            order.status = OrderStatus.SUBMITTED
            await self._update_order(order)
            # In real implementation, would register for price monitoring
    
    async def cancel_order(self, order_id: str) -> bool:
        order = self.orders.get(order_id)
        if not order or not order.is_active:
            return False
        order.status = OrderStatus.CANCELLED
        await self._update_order(order)
        return True
    
    async def get_order_status(self, order_id: str) -> OrderStatus:
        order = self.orders.get(order_id)
        return order.status if order else OrderStatus.REJECTED
    
    async def get_positions(self) -> Dict[str, Position]:
        return dict(self.positions)
    
    async def get_balances(self) -> Dict[str, float]:
        return dict(self.balances)
    
    def update_mark_price(self, symbol: str, price: float):
        """Update mark price for unrealized P&L"""
        self._market_data[symbol.upper()] = price
        pos = self.positions.get(symbol.upper())
        if pos and pos.quantity != 0:
            pos.unrealized_pnl = (price - pos.avg_entry_price) * pos.quantity


class ExecutionEngine:
    """Main execution engine coordinating brokers and orders"""
    
    def __init__(self):
        self.brokers: Dict[str, BaseBroker] = {}
        self.default_broker: Optional[str] = None
        self.order_router: Optional[Callable[[Order], str]] = None
        
        # Persistence (StateStore-like: set/get/get_all)
        self.state_store: Any = None
        self.persistence_category: str = "execution"
        
        # Drawdown tracking (peak equity)
        self._peak_equity: float = 0.0
        self._max_drawdown: float = 0.0
        
        # Risk checks
        self.pre_trade_checks: List[Callable[[Order], bool]] = []
        
        # Callbacks
        self.on_order_update: Optional[Callable[[Order], None]] = None
        self.on_fill: Optional[Callable[[Fill], None]] = None
        self.on_position_update: Optional[Callable[[Position], None]] = None
        
        # OpenClaw snapshot path (optional shared location)
        self.openclaw_snapshot_path: Optional[str] = None

    def set_state_store(self, state_store: Any, category: str = "execution") -> None:
        """Attach a StateStore-like object for persisting positions/orders/balances."""
        self.state_store = state_store
        self.persistence_category = category

    def set_openclaw_snapshot_path(self, path: str) -> None:
        """Set a path to write a portfolio snapshot that OpenClaw can read."""
        self.openclaw_snapshot_path = path
    
    def add_broker(self, name: str, broker: BaseBroker, is_default: bool = False):
        self.brokers[name] = broker
        if is_default or not self.default_broker:
            self.default_broker = name
        
        # Forward callbacks
        broker.on_order_update = self._on_order_update
        broker.on_fill = self._on_fill
        broker.on_position_update = self._on_position_update
    
    def set_order_router(self, router: Callable[[Order], str]):
        self.order_router = router
    
    def add_pre_trade_check(self, check: Callable[[Order], bool]):
        self.pre_trade_checks.append(check)
    
    async def submit_order(self, order: Order) -> Order:
        # Run pre-trade checks
        for check in self.pre_trade_checks:
            if not check(order):
                order.status = OrderStatus.REJECTED
                return order
        
        # Route to broker
        broker_name = self.order_router(order) if self.order_router else self.default_broker
        broker = self.brokers.get(broker_name)
        
        if not broker:
            order.status = OrderStatus.REJECTED
            return order
        
        return await broker.submit_order(order)
    
    async def cancel_order(self, order_id: str, broker_name: Optional[str] = None) -> bool:
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return False
        return await broker.cancel_order(order_id)
    
    async def get_order(self, order_id: str, broker_name: Optional[str] = None) -> Optional[Order]:
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return None
        return broker.orders.get(order_id)
    
    async def get_positions(self, broker_name: Optional[str] = None) -> Dict[str, Position]:
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return {}
        return await broker.get_positions()
    
    async def get_balances(self, broker_name: Optional[str] = None) -> Dict[str, float]:
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return {}
        return await broker.get_balances()
    
    def _on_order_update(self, order: Order):
        if self.on_order_update:
            self.on_order_update(order)
    
    def _on_fill(self, fill: Fill):
        if self.on_fill:
            self.on_fill(fill)
    
    def _on_position_update(self, position: Position):
        if self.on_position_update:
            self.on_position_update(position)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _order_to_dict(order: Order) -> dict:
        return {
            "symbol": order.symbol,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "quantity": order.quantity,
            "price": order.price,
            "stop_price": order.stop_price,
            "time_in_force": order.time_in_force.value,
            "client_order_id": order.client_order_id,
            "exchange_order_id": order.exchange_order_id,
            "status": order.status.value,
            "filled_qty": order.filled_qty,
            "avg_fill_price": order.avg_fill_price,
            "commission": order.commission,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "metadata": order.metadata,
        }

    @staticmethod
    def _order_from_dict(d: dict) -> Order:
        return Order(
            symbol=d["symbol"],
            side=OrderSide(d["side"]),
            order_type=OrderType(d["order_type"]),
            quantity=d.get("quantity", 0.0),
            price=d.get("price"),
            stop_price=d.get("stop_price"),
            time_in_force=TimeInForce(d.get("time_in_force", TimeInForce.GTC.value)),
            client_order_id=d.get("client_order_id") or str(uuid.uuid4()),
            exchange_order_id=d.get("exchange_order_id"),
            status=OrderStatus(d["status"]),
            filled_qty=d.get("filled_qty", 0.0),
            avg_fill_price=d.get("avg_fill_price", 0.0),
            commission=d.get("commission", 0.0),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            metadata=d.get("metadata", {}),
        )

    @staticmethod
    def _position_to_dict(pos: Position) -> dict:
        return {
            "symbol": pos.symbol,
            "quantity": pos.quantity,
            "avg_entry_price": pos.avg_entry_price,
            "unrealized_pnl": pos.unrealized_pnl,
            "realized_pnl": pos.realized_pnl,
            "updated_at": pos.updated_at,
        }

    @staticmethod
    def _position_from_dict(d: dict) -> Position:
        return Position(
            symbol=d["symbol"],
            quantity=d.get("quantity", 0.0),
            avg_entry_price=d.get("avg_entry_price", 0.0),
            unrealized_pnl=d.get("unrealized_pnl", 0.0),
            realized_pnl=d.get("realized_pnl", 0.0),
            updated_at=d.get("updated_at", time.time()),
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    async def save_state(self, broker_name: Optional[str] = None) -> None:
        """Persist positions, active orders, and balances to the StateStore.

        Called on each fill and on each execution-loop tick so state survives
        restarts. Only active (non-terminal) orders are persisted.
        """
        if not self.state_store:
            return
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return
        try:
            positions = broker.positions if hasattr(broker, "positions") else await broker.get_positions()
            balances = broker.balances if hasattr(broker, "balances") else await broker.get_balances()
            active_orders = {oid: o for oid, o in broker.orders.items() if o.is_active}

            # Refresh drawdown tracking from current equity so it survives restarts
            self.get_portfolio_summary(broker_name)

            payload = {
                "broker": broker_name,
                "positions": {sym: self._position_to_dict(p) for sym, p in positions.items()},
                "orders": {oid: self._order_to_dict(o) for oid, o in active_orders.items()},
                "balances": balances,
                "saved_at": time.time(),
                "peak_equity": self._peak_equity,
                "max_drawdown": self._max_drawdown,
            }
            self.state_store.set("execution_state", payload, category=self.persistence_category)
        except Exception as e:
            logger.error(f"save_state failed: {e}")

    async def load_state(self, broker_name: Optional[str] = None) -> bool:
        """Restore positions, active orders, and balances from the StateStore.

        Returns True if state was restored, False if nothing was stored.
        """
        if not self.state_store:
            return False
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return False
        try:
            data = self.state_store.get("execution_state", default=None, category=self.persistence_category)
            if not data:
                return False

            # Restore balances
            balances = data.get("balances", {})
            if hasattr(broker, "balances") and isinstance(balances, dict):
                broker.balances = dict(balances)

            # Restore positions
            positions = data.get("positions", {})
            for sym, pdict in positions.items():
                broker.positions[sym] = self._position_from_dict(pdict)

            # Restore active orders
            orders = data.get("orders", {})
            for oid, odict in orders.items():
                broker.orders[oid] = self._order_from_dict(odict)

            self._peak_equity = float(data.get("peak_equity", 0.0))
            self._max_drawdown = float(data.get("max_drawdown", 0.0))

            logger.info(
                f"Restored execution state: {len(positions)} positions, "
                f"{len(orders)} active orders, equity_peak={self._peak_equity:.2f}"
            )
            return True
        except Exception as e:
            logger.error(f"load_state failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Mark-to-market
    # ------------------------------------------------------------------
    async def update_mark_prices(self, market_prices: Dict[str, float],
                                 broker_name: Optional[str] = None) -> None:
        """Mark-to-market: refresh unrealized P&L for all open positions.

        `market_prices` maps symbol -> latest mid/trade price.
        """
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return
        positions = broker.positions if hasattr(broker, "positions") else await broker.get_positions()
        for sym, pos in positions.items():
            if pos.quantity == 0:
                continue
            price = market_prices.get(sym) or market_prices.get(sym.upper())
            if price is None:
                continue
            if hasattr(broker, "update_mark_price"):
                broker.update_mark_price(sym, price)
            else:
                pos.unrealized_pnl = (price - pos.avg_entry_price) * pos.quantity
                pos.updated_at = time.time()

    # ------------------------------------------------------------------
    # Pending order processing (limit orders that become executable)
    # ------------------------------------------------------------------
    async def process_pending_orders(self, broker_name: Optional[str] = None) -> int:
        """Process pending limit orders against the latest market prices.

        Returns the number of orders filled.
        """
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return 0
        market_data = getattr(broker, "_market_data", {})
        count = 0
        for oid, order in list(broker.orders.items()):
            if not order.is_active or order.order_type != OrderType.LIMIT:
                continue
            if not order.price or order.remaining_qty <= 0:
                continue
            price = market_data.get(order.symbol.upper())
            if price is None:
                continue
            can_fill = (
                (order.side == OrderSide.BUY and price <= order.price)
                or (order.side == OrderSide.SELL and price >= order.price)
            )
            if not can_fill:
                continue
            market_order = Order(
                symbol=order.symbol,
                side=order.side,
                order_type=OrderType.MARKET,
                quantity=order.remaining_qty,
                price=order.price,
                client_order_id=order.client_order_id,
            )
            await broker.submit_order(market_order)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Portfolio summary
    # ------------------------------------------------------------------
    def get_portfolio_summary(self, broker_name: Optional[str] = None) -> dict:
        """Compute portfolio summary: equity, realized+unrealized P&L, drawdown."""
        broker_name = broker_name or self.default_broker
        broker = self.brokers.get(broker_name)
        if not broker:
            return {}

        positions = broker.positions if hasattr(broker, "positions") else {}
        balances = broker.balances if hasattr(broker, "balances") else {}

        cash = float(balances.get("USDT", 0.0))
        market_value = 0.0
        total_realized = 0.0
        total_unrealized = 0.0
        position_summaries = {}

        for sym, pos in positions.items():
            total_realized += float(pos.realized_pnl)
            total_unrealized += float(pos.unrealized_pnl)
            mark = None
            if hasattr(broker, "get_market_price"):
                mark = broker.get_market_price(sym)
            if mark is None:
                # No live mark price: value at avg entry (no unrealized P&L)
                mark = float(pos.avg_entry_price) if pos.quantity != 0 else 0.0
            if pos.quantity != 0:
                market_value += float(pos.quantity) * float(mark)
            position_summaries[sym] = {
                "quantity": float(pos.quantity),
                "avg_entry_price": float(pos.avg_entry_price),
                "unrealized_pnl": float(pos.unrealized_pnl),
                "realized_pnl": float(pos.realized_pnl),
                "mark_price": float(mark),
            }

        equity = cash + market_value
        total_pnl = total_realized + total_unrealized

        if equity > self._peak_equity:
            self._peak_equity = equity
        drawdown = self._peak_equity - equity
        if drawdown > self._max_drawdown:
            self._max_drawdown = drawdown

        snapshot = {
            "broker": broker_name,
            "cash": cash,
            "market_value": market_value,
            "equity": equity,
            "realized_pnl": total_realized,
            "unrealized_pnl": total_unrealized,
            "total_pnl": total_pnl,
            "peak_equity": self._peak_equity,
            "max_drawdown": self._max_drawdown,
            "drawdown": drawdown,
            "positions": position_summaries,
            "timestamp": time.time(),
        }

        # Optional OpenClaw shared snapshot
        if self.openclaw_snapshot_path:
            try:
                from pathlib import Path
                import json
                Path(self.openclaw_snapshot_path).parent.mkdir(parents=True, exist_ok=True)
                with open(self.openclaw_snapshot_path, "w") as f:
                    json.dump(snapshot, f, indent=2)
            except Exception as e:
                logger.debug(f"OpenClaw snapshot write failed: {e}")

        return snapshot


# Risk check functions
def max_position_check(max_qty: float) -> Callable[[Order], bool]:
    def check(order: Order) -> bool:
        return order.quantity <= max_qty
    return check


def max_notional_check(max_notional: float) -> Callable[[Order], bool]:
    def check(order: Order) -> bool:
        price = order.price or 0
        return order.quantity * price <= max_notional
    return check


def max_drawdown_check(max_dd: float, get_portfolio_value: Callable[[], float]) -> Callable[[Order], bool]:
    def check(order: Order) -> bool:
        # Simplified - in reality would check current drawdown
        return True
    return check


def position_limit_check(max_positions: int, get_positions: Callable[[], Dict]) -> Callable[[Order], bool]:
    def check(order: Order) -> bool:
        positions = get_positions()
        if order.symbol not in positions:
            return len(positions) < max_positions
        return True
    return check


def daily_loss_limit_check(max_loss: float, get_daily_pnl: Callable[[], float]) -> Callable[[Order], bool]:
    def check(order: Order) -> bool:
        return get_daily_pnl() > -max_loss
    return check


# Helper
def uppercase(s: str) -> str:
    return s.upper()


# Example usage
async def main():
    engine = ExecutionEngine()
    
    # Add paper broker
    paper = PaperBroker(initial_balance=100000.0)
    engine.add_broker("paper", paper, is_default=True)
    
    # Add risk checks
    engine.add_pre_trade_check(max_position_check(10000))
    engine.add_pre_trade_check(max_notional_check(50000))
    
    # Set up callbacks
    def on_fill(fill):
        print(f"Fill: {fill.symbol} {fill.side.value} {fill.quantity}@{fill.price}")
    
    engine.on_fill = on_fill
    
    # Submit order
    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.1,
        price=50000.0
    )
    
    result = await engine.submit_order(order)
    print(f"Order status: {result.status}, filled: {result.filled_qty}@{result.avg_fill_price}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
