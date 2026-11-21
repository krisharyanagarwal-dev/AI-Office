#!/usr/bin/env python3
"""
TWAP (Time-Weighted Average Price) Execution Algorithm

Breaks large orders into smaller slices executed at regular intervals
to minimize market impact and achieve average price over time window.
"""
import asyncio
import time
import uuid
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from collections import deque
import logging

from .execution_engine import Order, OrderSide, OrderType, OrderStatus, TimeInForce, BaseBroker

logger = logging.getLogger(__name__)


class TWAPStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class TWAPSlice:
    """Single TWAP slice order"""
    slice_id: str
    parent_id: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    limit_price: Optional[float]
    time_in_force: TimeInForce
    created_at: float
    submitted_at: Optional[float] = None
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    order_id: Optional[str] = None


@dataclass
class TWAPOrder:
    """TWAP parent order"""
    order_id: str
    symbol: str
    side: OrderSide
    total_quantity: float
    slices: List[TWAPSlice] = field(default_factory=list)
    status: TWAPStatus = TWAPStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    # TWAP parameters
    duration_seconds: int = 3600           # Total duration (default 1 hour)
    slice_interval_seconds: int = 300      # Time between slices (default 5 min)
    max_slice_size: Optional[float] = None # Max slice quantity
    min_slice_size: float = 0.001          # Minimum slice quantity
    participation_rate: float = 0.1        # Max participation rate (10%)
    price_limit: Optional[float] = None    # Price limit (optional)
    randomize_slices: bool = True          # Randomize slice sizes
    slice_variance: float = 0.2            # Slice size variance (20%)
    
    # Progress tracking
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    slice_index: int = 0
    
    # Callbacks
    on_slice_filled: Optional[Callable[[TWAPSlice], None]] = None
    on_complete: Optional[Callable[["TWAPOrder"], None]] = None
    on_error: Optional[Callable[["TWAPOrder", str], None]] = None


class TWAPExecutor:
    """
    TWAP (Time-Weighted Average Price) Execution Algorithm
    
    Splits a large order into smaller slices executed at regular intervals
    over a specified time window to minimize market impact.
    """
    
    def __init__(self, broker: BaseBroker):
        self.broker = broker
        self.active_orders: Dict[str, TWAPOrder] = {}
        self.order_history: List[TWAPOrder] = []
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the TWAP executor"""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("TWAP executor started")
    
    async def stop(self):
        """Stop the TWAP executor"""
        self._running = False
        
        # Cancel all active orders
        for order in self.active_orders.values():
            await self.cancel_twap(order.order_id)
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("TWAP executor stopped")
    
    def create_twap_order(
        self,
        symbol: str,
        side: OrderSide,
        total_quantity: float,
        duration_seconds: int = 3600,
        slice_interval_seconds: int = 300,
        max_slice_size: Optional[float] = None,
        min_slice_size: float = 0.001,
        participation_rate: float = 0.1,
        price_limit: Optional[float] = None,
        randomize_slices: bool = True,
        slice_variance: float = 0.2,
        order_type: OrderType = OrderType.MARKET,
        time_in_force: TimeInForce = TimeInForce.IOC
    ) -> TWAPOrder:
        """
        Create a new TWAP order.
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            total_quantity: Total quantity to execute
            duration_seconds: Total execution window (seconds)
            slice_interval_seconds: Time between slices (seconds)
            max_slice_size: Maximum slice size (None = auto)
            min_slice_size: Minimum slice size
            participation_rate: Max participation rate (0-1)
            price_limit: Optional price limit
            randomize_slices: Whether to randomize slice sizes
            slice_variance: Slice size variance (0-1)
            
        Returns:
            TWAPOrder object
        """
        order_id = str(uuid.uuid4())
        
        # Calculate number of slices
        num_slices = max(1, duration_seconds // slice_interval_seconds)
        
        # Calculate base slice size
        base_slice_size = total_quantity / num_slices
        
        if max_slice_size:
            base_slice_size = min(base_slice_size, max_slice_size)
            num_slices = max(1, int(total_quantity / base_slice_size) + 1)
        
        # Generate slice quantities
        slice_quantities = self._generate_slice_quantities(
            total_quantity, num_slices, slice_variance
        )
        
        # Create slices
        slices = []
        for i, qty in enumerate(slice_quantities):
            slice_order = TWAPSlice(
                slice_id=str(uuid.uuid4()),
                parent_id="",  # Will be set after TWAPOrder creation
                symbol=symbol,
                side=side,
                quantity=qty,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force=TimeInForce.IOC,
                created_at=time.time()
            )
            slices.append(slice_order)
        
        # Create TWAP order
        twap_order = TWAPOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            slices=slices,
            duration_seconds=duration_seconds,
            slice_interval_seconds=slice_interval_seconds,
            max_slice_size=max_slice_size,
            min_slice_size=min_slice_size,
            participation_rate=participation_rate,
            price_limit=price_limit
        )
        
        # Set parent_id on slices
        for slice_obj in slices:
            slice_obj.parent_id = order_id
        
        self.active_orders[order_id] = twap_order
        logger.info(f"Created TWAP order {order_id}: {symbol} {side.value} {total_quantity} over {duration_seconds}s")
        
        return twap_order
    
    def _generate_slice_quantities(
        self, 
        total_quantity: float, 
        num_slices: int, 
        variance: float
    ) -> List[float]:
        """Generate randomized slice quantities that sum to total"""
        if num_slices <= 1:
            return [total_quantity]
        
        base = total_quantity / num_slices
        quantities = []
        remaining = total_quantity
        
        for i in range(num_slices - 1):
            # Add random variance
            max_var = base * variance
            qty = base + (random.random() - 0.5) * 2 * max_var
            qty = max(0.001, min(qty, remaining * 0.5))  # Don't exceed half of remaining
            quantities.append(qty)
            remaining -= qty
        
        quantities.append(remaining)
        
        # Shuffle to randomize execution order
        random.shuffle(quantities)
        
        return quantities
    
    async def execute_twap(self, twap_order: TWAPOrder) -> TWAPOrder:
        """Execute a TWAP order"""
        if twap_order.order_id not in self.active_orders:
            twap_order.status = TWAPOrder.FAILED
            logger.error(f"TWAP order {twap_order.order_id} not found")
            return twap_order
        
        twap_order.status = TWAPOrder.RUNNING
        twap_order.started_at = time.time()
        
        logger.info(f"Starting TWAP execution: {twap_order.order_id}")
        
        try:
            for i, slice_obj in enumerate(twap_order.slices):
                if not self._running:
                    twap_order.status = TWAPOrder.CANCELLED
                    break
                
                if twap_order.status == TWAPOrder.PAUSED:
                    # Wait while paused
                    while twap_order.status == TWAPOrder.PAUSED and self._running:
                        await asyncio.sleep(1.0)
                    if not self._running:
                        twap_order.status = TWAPOrder.CANCELLED
                        break
                
                if twap_order.status == TWAPOrder.CANCELLED:
                    break
                
                twap_order.slice_index = i
                
                # Execute slice
                await self._execute_slice(twap_order, slice_obj)
                
                # Update progress
                twap_order.filled_quantity += slice_obj.filled_quantity
                if twap_order.filled_quantity > 0:
                    total_filled = sum(s.filled_quantity * s.avg_fill_price for s in twap_order.slices if s.filled_quantity > 0)
                    total_qty = sum(s.filled_quantity for s in twap_order.slices if s.filled_quantity > 0)
                    twap_order.avg_fill_price = total_filled / total_qty if total_qty > 0 else 0
                
                # Callback
                if twap_order.on_slice_filled:
                    try:
                        twap_order.on_slice_filled(slice_obj)
                    except Exception as e:
                        logger.error(f"Slice callback error: {e}")
                
                # Wait for next slice interval
                if i < len(twap_order.slices) - 1:
                    await asyncio.sleep(twap_order.slice_interval_seconds)
            
            if twap_order.status == TWAPOrder.RUNNING:
                twap_order.status = TWAPOrder.COMPLETED
                twap_order.completed_at = time.time()
                logger.info(f"TWAP completed: {twap_order.order_id}, "
                           f"filled={twap_order.filled_quantity:.4f}/{twap_order.total_quantity:.4f}, "
                           f"avg_price={twap_order.avg_fill_price:.4f}")
                
                if twap_order.on_complete:
                    try:
                        twap_order.on_complete(twap_order)
                    except Exception as e:
                        logger.error(f"Completion callback error: {e}")
            
        except Exception as e:
            twap_order.status = TWAPOrder.FAILED
            logger.error(f"TWAP execution failed: {twap_order.order_id}: {e}")
            if twap_order.on_error:
                try:
                    twap_order.on_error(twap_order, str(e))
                except Exception as e2:
                    logger.error(f"Error callback error: {e2}")
        
        # Move to history
        self.active_orders.pop(twap_order.order_id, None)
        self.order_history.append(twap_order)
        
        return twap_order
    
    async def _execute_slice(self, twap_order: TWAPOrder, slice_obj: TWAPSlice):
        """Execute a single slice"""
        # Check price limit
        if twap_order.price_limit:
            # Would need current market price - simplified for now
            pass
        
        # Create broker order
        from .execution_engine import Order as BrokerOrder
        broker_order = BrokerOrder(
            symbol=slice_obj.symbol,
            side=slice_obj.side,
            order_type=slice_obj.order_type,
            quantity=slice_obj.quantity,
            price=slice_obj.limit_price,
            time_in_force=slice_obj.time_in_force
        )
        
        # Submit to broker
        slice_obj.submitted_at = time.time()
        filled_order = await self.broker.submit_order(broker_order)
        
        slice_obj.order_id = filled_order.order_id
        slice_obj.status = filled_order.status
        slice_obj.filled_quantity = filled_order.filled_qty
        slice_obj.avg_fill_price = filled_order.avg_fill_price
        
        return slice_obj
    
    async def cancel_twap(self, order_id: str) -> bool:
        """Cancel a TWAP order"""
        if order_id not in self.active_orders:
            return False
        
        twap_order = self.active_orders[order_id]
        twap_order.status = TWAPOrder.CANCELLED
        
        # Cancel pending slices
        for slice_obj in twap_order.slices:
            if slice_obj.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                slice_obj.status = OrderStatus.CANCELLED
                if slice_obj.order_id:
                    try:
                        await self.broker.cancel_order(slice_obj.order_id)
                    except Exception as e:
                        logger.error(f"Failed to cancel slice {slice_obj.slice_id}: {e}")
        
        self.active_orders.pop(order_id, None)
        self.order_history.append(twap_order)
        
        logger.info(f"TWAP order cancelled: {order_id}")
        return True
    
    def pause_twap(self, order_id: str) -> bool:
        """Pause a TWAP order"""
        if order_id not in self.active_orders:
            return False
        self.active_orders[order_id].status = TWAPOrder.PAUSED
        return True
    
    def resume_twap(self, order_id: str) -> bool:
        """Resume a paused TWAP order"""
        if order_id not in self.active_orders:
            return False
        if self.active_orders[order_id].status != TWAPOrder.PAUSED:
            return False
        self.active_orders[order_id].status = TWAPOrder.RUNNING
        return True
    
    def get_twap_status(self, order_id: str) -> Optional[Dict]:
        """Get TWAP order status"""
        if order_id in self.active_orders:
            twap = self.active_orders[order_id]
        else:
            # Check history
            twap = next((o for o in self.order_history if o.order_id == order_id), None)
            if not twap:
                return None
        
        return {
            'order_id': twap.order_id,
            'symbol': twap.symbol,
            'side': twap.side.value,
            'status': twap.status.value,
            'total_quantity': twap.total_quantity,
            'filled_quantity': twap.filled_quantity,
            'fill_pct': twap.filled_quantity / twap.total_quantity if twap.total_quantity > 0 else 0,
            'avg_fill_price': twap.avg_fill_price,
            'slice_index': twap.slice_index,
            'total_slices': len(twap.slices),
            'created_at': twap.created_at,
            'started_at': twap.started_at,
            'completed_at': twap.completed_at,
            'slices': [
                {
                    'slice_id': s.slice_id,
                    'quantity': s.quantity,
                    'filled': s.filled_quantity,
                    'avg_price': s.avg_fill_price,
                    'status': s.status.value
                }
                for s in twap.slices
            ]
        }
    
    async def _monitor_loop(self):
        """Background monitoring loop"""
        while self._running:
            try:
                # Check for stale orders
                now = time.time()
                for order_id, twap in list(self.active_orders.items()):
                    if twap.status == TWAPOrder.RUNNING:
                        # Check for stuck slices
                        if twap.slice_index < len(twap.slices):
                            slice_obj = twap.slices[twap.slice_index]
                            if slice_obj.submitted_at and (now - slice_obj.submitted_at) > 60:
                                # Slice stuck for >60s
                                logger.warning(f"Slice {slice_obj.slice_id} stuck, status: {slice_obj.status}")
                
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TWAP monitor error: {e}")
                await asyncio.sleep(5.0)
    
    def get_active_orders(self) -> List[Dict]:
        """Get all active TWAP orders"""
        return [self.get_twap_status(oid) for oid in self.active_orders]
    
    def get_order_history(self, limit: int = 100) -> List[Dict]:
        """Get order history"""
        return [self.get_twap_status(o.order_id) for o in self.order_history[-limit:]]
    
    def get_metrics(self) -> Dict:
        """Get TWAP executor metrics"""
        total_filled = sum(o.filled_quantity for o in self.order_history)
        total_volume = sum(o.total_quantity for o in self.order_history)
        completed = sum(1 for o in self.order_history if o.status == TWAPOrder.COMPLETED)
        failed = sum(1 for o in self.order_history if o.status == TWAPOrder.FAILED)
        
        return {
            'active_orders': len(self.active_orders),
            'total_orders': len(self.order_history),
            'completed': completed,
            'failed': failed,
            'total_filled': total_filled,
            'total_volume': total_volume,
            'fill_rate': total_filled / total_volume if total_volume > 0 else 0
        }


# Convenience function for quick TWAP execution
async def execute_twap(
    broker: BaseBroker,
    symbol: str,
    side: OrderSide,
    total_quantity: float,
    duration_seconds: int = 3600,
    slice_interval_seconds: int = 300,
    **kwargs
) -> TWAPOrder:
    """Quick TWAP execution"""
    executor = TWAPExecutor(broker)
    await executor.start()
    
    try:
        order = executor.create_twap_order(
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            duration_seconds=duration_seconds,
            slice_interval_seconds=slice_interval_seconds,
            **kwargs
        )
        result = await executor.execute_twap(order)
        return result
    finally:
        await executor.stop()