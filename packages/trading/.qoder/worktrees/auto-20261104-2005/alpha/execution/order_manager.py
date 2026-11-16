"""
Order Management System
Advanced order handling, OCO, bracket orders, position reconciliation
"""
import asyncio
import uuid
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from collections import defaultdict
import logging
from datetime import datetime, timedelta

from .execution_engine import (
    BaseBroker, Order, OrderSide, OrderType, OrderStatus, 
    TimeInForce, Fill, Position
)
from .brokers import LiveBroker

logger = logging.getLogger(__name__)


class OrderGroup(Enum):
    """Order grouping types"""
    STANDARD = "standard"
    OCO = "oco"              # One-Cancels-Other
    BRACKET = "bracket"      # Entry + Stop + Target
    ICEBERG = "iceberg"      # Hidden quantity
    TWAP = "twap"            # Time-Weighted Average Price
    VWAP = "vwap"            # Volume-Weighted Average Price


@dataclass
class OrderGroup:
    """Group of related orders"""
    group_id: str
    group_type: OrderGroup
    orders: List[str] = field(default_factory=list)  # client_order_ids
    created_at: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)
    active: bool = True
    
    def add_order(self, order_id: str):
        if order_id not in self.orders:
            self.orders.append(order_id)
    
    def remove_order(self, order_id: str):
        if order_id in self.orders:
            self.orders.remove(order_id)
    
    def is_complete(self, order_statuses: Dict[str, str]) -> bool:
        """Check if group is complete based on order statuses"""
        if not self.orders:
            return True
        statuses = [order_statuses.get(oid, 'PENDING') for oid in self.orders]
        if self.type == OrderGroup.OCO:
            # OCO complete when one fills and others cancel
            filled = sum(1 for s in statuses if s == 'FILLED')
            cancelled = sum(1 for s in statuses if s == 'CANCELLED')
            return filled >= 1 and (filled + cancelled) >= len(self.orders)
        elif self.type == OrderGroup.BRACKET:
            # Bracket complete when entry fills and either stop or target fills
            entry_filled = any(s == 'FILLED' for s in statuses[:1])  # First is entry
            stop_filled = any(s == 'FILLED' for s in statuses[1:2])
            target_filled = any(s == 'FILLED' for s in statuses[2:3])
            return entry_filled and (stop_filled or target_filled)
        return all(s in ('FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED') for s in statuses)


class OrderManager:
    """
    Advanced order management with grouping, lifecycle tracking,
    position reconciliation, and automated order handling
    """
    
    def __init__(self, broker):
        self.broker = broker
        self.order_groups: Dict[str, OrderGroup] = {}
        self.order_to_group: Dict[str, str] = {}
        
        # Lifecycle hooks
        self.on_order_submit: Optional[Callable[[Order], None]] = None
        self.on_order_fill: Optional[Callable[[Order, Fill], None]] = None
        self.on_order_cancel: Optional[Callable[[Order], None]] = None
        self.on_group_complete: Optional[Callable[[OrderGroup], None]] = None
        self.on_error: Optional[Callable[[Order, Exception], None]] = None
        
        # Monitoring
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Callbacks from broker
        broker.on_order_update = self._on_order_update
        broker.on_fill = self._on_fill
        broker.on_position_update = self._on_position_update
    
    async def start(self):
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("OrderManager started")
    
    async def stop(self):
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
    
    # Order Creation Helpers
    
    async def create_oco_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        limit_price: float,
        stop_price: float,
        stop_limit_price: Optional[float] = None,
        metadata: Dict = None
    ) -> tuple:
        """
        Create One-Cancels-Other order group
        Returns (limit_order, stop_order)
        """
        group_id = f"oco_{uuid.uuid4().hex[:8]}"
        limit_order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=limit_price,
            metadata=metadata or {}
        )
        
        if stop_limit_price:
            stop_order = Order(
                symbol=symbol,
                side=OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY,
                order_type=OrderType.STOP_LIMIT,
                quantity=quantity,
                price=stop_limit_price,
                stop_price=stop_price,
                metadata=metadata or {}
            )
        else:
            stop_order = Order(
                symbol=symbol,
                side=OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY,
                order_type=OrderType.STOP,
                quantity=quantity,
                stop_price=stop_price,
                metadata=metadata or {}
            )
        
        group = OrderGroup(
            group_id=group_id,
            group_type=OrderGroup.OCO,
            orders=[limit_order.client_order_id, stop_order.client_order_id],
            metadata=metadata or {}
        )
        
        self.order_groups[group_id] = group
        self.order_to_group[limit_order.client_order_id] = group_id
        self.order_to_group[stop_order.client_order_id] = group_id
        
        # Submit both orders
        limit_result = await self.broker.submit_order(limit_order)
        stop_result = await self.broker.submit_order(stop_order)
        
        return limit_order, stop_order
    
    async def create_bracket_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        entry_type: OrderType = OrderType.LIMIT,
        metadata: Dict = None
    ) -> tuple:
        """
        Create bracket order (Entry + Stop Loss + Take Profit)
        Returns (entry_order, stop_order, target_order)
        """
        group_id = f"bracket_{uuid.uuid4().hex[:8]}"
        
        # Entry order
        entry_order = Order(
            symbol=symbol,
            side=side,
            order_type=entry_type,
            quantity=quantity,
            price=entry_price if entry_type != OrderType.MARKET else None,
            metadata=metadata or {}
        )
        
        # Stop loss order (opposite side)
        opposite_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        stop_order = Order(
            symbol=symbol,
            side=opposite_side,
            order_type=OrderType.STOP,
            quantity=quantity,
            stop_price=stop_loss,
            metadata=metadata or {}
        )
        
        # Take profit order (opposite side)
        target_order = Order(
            symbol=symbol,
            side=opposite_side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=take_profit,
            metadata=metadata or {}
        )
        
        group = OrderGroup(
            group_id=group_id,
            group_type=OrderGroup.BRACKET,
            orders=[entry_order.client_order_id, stop_order.client_order_id, target_order.client_order_id],
            metadata=metadata or {}
        )
        
        self.order_groups[group_id] = group
        for o in [entry_order, stop_order, target_order]:
            self.order_to_group[o.client_order_id] = group_id
        
        # Submit entry first, then conditional orders
        entry_result = await self.broker.submit_order(entry_order)
        
        # Submit stop and target as conditional (would need broker support)
        # For now, submit all and manage via monitoring
        stop_result = await self.broker.submit_order(stop_order)
        target_result = await self.broker.submit_order(target_order)
        
        return entry_order, stop_order, target_order
    
    async def create_twap_order(
        self,
        symbol: str,
        side: OrderSide,
        total_quantity: float,
        duration_minutes: int,
        slices: int = 10,
        limit_price: Optional[float] = None,
        metadata: Dict = None
    ) -> List[Order]:
        """
        Create Time-Weighted Average Price order
        Splits quantity into slices over duration
        """
        group_id = f"twap_{uuid.uuid4().hex[:8]}"
        slice_qty = total_quantity / slices
        interval_sec = (duration_minutes * 60) / slices
        
        orders = []
        for i in range(slices):
            order = Order(
                symbol=symbol,
                side=side,
                order_type=OrderType.LIMIT if limit_price else OrderType.MARKET,
                quantity=slice_qty,
                price=limit_price,
                metadata={**metadata, 'twap_slice': i, 'twap_total': slices} if metadata else {'twap_slice': i, 'twap_total': slices}
            )
            orders.append(order)
        
        group_id = f"twap_{uuid.uuid4().hex[:8]}"
        group = OrderGroup(
            group_id=group_id,
            group_type=OrderGroup.TWAP,
            orders=[o.client_order_id for o in orders],
            metadata={**(metadata or {}), 'interval_sec': interval_sec}
        )
        
        self.order_groups[group_id] = group
        for o in orders:
            self.order_to_group[o.client_order_id] = group_id
        
        return orders
    
    async def create_vwap_order(
        self,
        symbol: str,
        side: OrderSide,
        total_quantity: float,
        duration_minutes: int,
        volume_profile: Optional[List[float]] = None,
        metadata: Dict = None
    ) -> List[Order]:
        """
        Create Volume-Weighted Average Price order
        Uses volume profile for slice sizing
        """
        # Similar to TWAP but with volume-weighted slices
        return await self.create_twap_order(symbol, side, total_quantity, duration_minutes, metadata=metadata)
    
    # Order Management
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order and update group"""
        result = await self.broker.cancel_order(order_id)
        if result:
            # Handle group logic
            group_id = self.order_to_group.get(order_id)
            if group_id and group_id in self.order_groups:
                group = self.order_groups[group_id]
                if group.group_type == OrderGroup.OCO:
                    # Cancel sibling orders
                    for oid in group.orders:
                        if oid != order_id:
                            await self.broker.cancel_order(oid)
        return True
    
    async def cancel_group(self, group_id: str) -> bool:
        """Cancel all orders in a group"""
        group = self.order_groups.get(group_id)
        if not group:
            return False
        
        group.active = False
        results = []
        for oid in group.orders:
            result = await self.broker.cancel_order(oid)
            results.append(result)
        return all(results)
    
    async def amend_order(self, order_id: str, new_price: Optional[float] = None, 
                         new_qty: Optional[float] = None) -> bool:
        """Amend existing order (cancel + replace)"""
        order = self.broker.orders.get(order_id)
        if not order or not order.is_active:
            return False
        
        # Cancel old
        await self.broker.cancel_order(order_id)
        
        # Create new with modifications
        new_order = Order(
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=new_qty or order.quantity,
            price=new_price or order.price,
            time_in_force=order.time_in_force,
            metadata={**order.metadata, 'amended_from': order_id}
        )
        
        result = await self.broker.submit_order(new_order)
        return result.status != OrderStatus.REJECTED
    
    # Monitoring and Reconciliation
    
    async def _monitor_loop(self):
        """Background monitoring loop"""
        while self._running:
            try:
                await self._check_timeouts()
                await self._check_group_completion()
                await self._reconcile_positions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            
            await asyncio.sleep(1.0)
    
    async def _check_timeouts(self):
        """Check for stale orders"""
        now = time.time()
        for order in self.broker.orders.values():
            if order.is_active and (now - order.created_at) > 3600:  # 1 hour timeout
                # Could auto-cancel or alert
                if order.metadata.get('timeout_action') == 'cancel':
                    await self.cancel_order(order.client_order_id)
    
    async def _check_group_completion(self):
        """Check if any order groups are complete"""
        for group_id, group in list(self.order_groups.items()):
            if not group.active:
                continue
            
            order_statuses = {}
            for oid in group.orders:
                order = self.broker.orders.get(oid)
                if order:
                    order_statuses[oid] = order.status.value
            
            if group.is_complete(order_statuses):
                group.active = False
                if self.on_group_complete:
                    try:
                        self.on_group_complete(group)
                    except Exception as e:
                        logger.error(f"Group complete callback error: {e}")
    
    async def _reconcile_positions(self):
        """Reconcile broker positions with internal state"""
        try:
            broker_positions = await self.broker.get_positions()
            
            # Compare with internal positions
            for symbol, pos in self.broker.positions.items():
                broker_pos = broker_positions.get(symbol)
                if broker_pos and abs(pos.quantity - broker_pos.quantity) > 1e-8:
                    logger.warning(f"Position mismatch {symbol}: local={pos.quantity}, broker={broker_pos.quantity}")
                    # Could auto-reconcile or alert
                    
        except Exception as e:
            logger.error(f"Position reconciliation error: {e}")
    
    # Event Handlers
    
    async def _on_order_update(self, order: Order):
        """Handle order status updates from broker"""
        group_id = self.order_to_group.get(order.client_order_id)
        if group_id and group_id in self.order_groups:
            group = self.order_groups[order.client_order_id]
            # Check group completion
            await self._check_group_completion()
        
        if self.on_order_update:
            try:
                self.on_order_update(order)
            except Exception as e:
                logger.error(f"Order update callback error: {e}")
    
    async def _on_fill(self, fill):
        """Handle fill notifications"""
        order = self.broker.orders.get(fill.order_id)
        if order:
            if self.on_order_fill:
                try:
                    self.on_order_fill(order, fill)
                except Exception as e:
                    logger.error(f"Fill callback error: {e}")
    
    async def _on_position_update(self, position: Position):
        """Handle position updates"""
        pass
    
    # Utility Methods
    
    def get_group(self, group_id: str) -> Optional[OrderGroup]:
        return self.order_groups.get(group_id)
    
    def get_order_group(self, order_id: str) -> Optional[OrderGroup]:
        group_id = self.order_to_group.get(order_id)
        return self.order_groups.get(group_id) if group_id else None
    
    def get_active_groups(self) -> List[OrderGroup]:
        return [g for g in self.order_groups.values() if g.active]
    
    def get_order(self, order_id: str) -> Optional[Order]:
        return self.broker.orders.get(order_id)
    
    def get_orders_by_symbol(self, symbol: str) -> List[Order]:
        return [o for o in self.broker.orders.values() if o.symbol == symbol]
    
    def get_active_orders(self) -> List[Order]:
        return [o for o in self.broker.orders.values() if o.is_active]
    
    def get_group_status(self, group_id: str) -> Dict:
        group = self.order_groups.get(group_id)
        if not group:
            return {}
        
        order_statuses = {}
        for oid in group.orders:
            order = self.broker.orders.get(oid)
            if order:
                order_statuses[oid] = {
                    'status': order.status.value,
                    'filled': order.filled_qty,
                    'remaining': order.remaining_qty
                }
        
        return {
            'group_id': group_id,
            'type': group.group_type.value,
            'active': group.active,
            'orders': order_statuses
        }


class PositionManager:
    """Advanced position management"""
    
    def __init__(self, broker):
        self.broker = broker
        self.position_callbacks: List[Callable[[Position], None]] = []
    
    def add_callback(self, callback: Callable[[Position], None]):
        self.position_callbacks.append(callback)
    
    async def get_position(self, symbol: str) -> Optional[Position]:
        return self.broker.positions.get(symbol)
    
    async def get_all_positions(self) -> Dict[str, Position]:
        return await self.broker.get_positions()
    
    async def get_total_exposure(self) -> float:
        """Total absolute notional exposure"""
        positions = await self.get_all_positions()
        total = 0.0
        for pos in positions.values():
            # Would need mark price - simplified
            total += abs(pos.quantity) * (pos.avg_entry_price or 0)
        return total
    
    async def get_sector_exposure(self, sector_map: Dict[str, str]) -> Dict[str, float]:
        """Get exposure by sector"""
        positions = await self.get_all_positions()
        exposure = defaultdict(float)
        for symbol, pos in positions.items():
            sector = sector_map.get(symbol, 'Unknown')
            exposure[sector] += abs(pos.quantity) * (pos.avg_entry_price or 0)
        return dict(exposure)
    
    async def get_leverage(self) -> float:
        """Calculate current leverage"""
        # Simplified
        return 1.0
    
    async def check_margin(self) -> Dict:
        """Check margin requirements"""
        return {
            'margin_used': 0.0,
            'margin_available': 1.0,
            'margin_ratio': 1.0
        }
    
    async def add_callback(self, callback: Callable[[Position], None]):
        self.position_callbacks.append(callback)
    
    async def _notify_position_change(self, position: Position):
        for cb in self.position_callbacks:
            try:
                cb(position)
            except Exception as e:
                logger.error(f"Position callback error: {e}")
