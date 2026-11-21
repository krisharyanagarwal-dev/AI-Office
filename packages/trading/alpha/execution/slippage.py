#!/usr/bin/env python3
"""
Slippage Monitoring and Execution Quality Analysis

Tracks execution quality metrics including:
- Slippage (vs arrival, mid, VWAP)
- Market impact
- Timing analysis
- Fill quality metrics
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Deque
from enum import Enum
from collections import deque
import logging
import statistics

logger = logging.getLogger(__name__)


class SlippageType(Enum):
    ARRIVAL = "arrival"       # vs price at order submission
    MIDPOINT = "midpoint"     # vs mid price at submission
    VWAP = "vwap"             # vs VWAP over execution window
    TWAP = "twap"             # vs TWAP over execution window
    IMPLEMENTATION = "implementation"  # total implementation shortfall


@dataclass
class SlippageMetric:
    """Single slippage measurement"""
    metric_type: SlippageType
    symbol: str
    side: str              # "buy" or "sell"
    slippage_bps: float    # Basis points
    slippage_usd: float    # USD amount
    reference_price: float
    execution_price: float
    quantity: float
    notional: float
    timestamp: float
    metadata: Dict = field(default_factory=dict)


@dataclass
class ExecutionWindow:
    """Time window for VWAP/TWAP calculations"""
    symbol: str
    start_time: float
    end_time: float
    trades: List[Dict] = field(default_factory=list)  # {price, qty, timestamp}
    
    @property
    def vwap(self) -> float:
        if not self.trades:
            return 0.0
        total_notional = sum(t['price'] * t['qty'] for t in self.trades)
        total_qty = sum(t['qty'] for t in self.trades)
        return total_notional / total_qty if total_qty > 0 else 0.0
    
    @property
    def twap(self) -> float:
        if not self.trades:
            return 0.0
        return statistics.mean([t['price'] for t in self.trades])
    
    @property
    def total_volume(self) -> float:
        return sum(t['qty'] for t in self.trades)


@dataclass
class FillQualityMetrics:
    """Execution quality metrics for a single order/fill"""
    order_id: str
    symbol: str
    side: str
    order_type: str
    requested_qty: float
    filled_qty: float
    avg_fill_price: float
    arrival_price: float
    mid_price: float
    vwap_price: Optional[float] = None
    twap_price: Optional[float] = None
    
    # Slippage metrics (basis points)
    arrival_slippage_bps: float = 0.0
    midpoint_slippage_bps: float = 0.0
    vwap_slippage_bps: Optional[float] = None
    twap_slippage_bps: Optional[float] = None
    implementation_shortfall_bps: float = 0.0
    
    # USD amounts
    arrival_slippage_usd: float = 0.0
    midpoint_slippage_usd: float = 0.0
    
    # Timing
    order_time: float = 0.0
    first_fill_time: float = 0.0
    last_fill_time: float = 0.0
    execution_duration_ms: float = 0.0
    
    # Market context
    spread_bps: float = 0.0
    volatility: float = 0.0
    volume_participation: float = 0.0
    
    # Fill quality
    fill_rate: float = 0.0
    partial_fills: int = 0
    price_improvement_bps: float = 0.0


class SlippageMonitor:
    """
    Monitors and analyzes execution slippage across all orders.
    
    Tracks multiple slippage metrics:
    - Arrival slippage (vs price at order submission)
    - Midpoint slippage (vs mid price at submission)
    - VWAP slippage (vs volume-weighted average price)
    - TWAP slippage (vs time-weighted average price)
    - Implementation shortfall (total cost)
    """
    
    def __init__(self, max_history: int = 10000):
        self.metrics: Deque[SlippageMetric] = deque(maxlen=max_history)
        self.fill_quality: Deque[FillQualityMetrics] = deque(maxlen=max_history)
        self.execution_windows: Dict[str, ExecutionWindow] = {}
        self.market_data_cache: Dict[str, Dict] = {}  # symbol -> {mid, spread, vol}
        
        # Aggregated statistics
        self._stats_cache: Dict = {}
        self._stats_dirty = True
    
    def update_market_data(self, symbol: str, bid: float, ask: float, 
                           volume: float = 0, volatility: float = 0):
        """Update market data for slippage calculations"""
        mid = (bid + ask) / 2
        spread = ask - bid
        spread_bps = (spread / mid) * 10000 if mid > 0 else 0
        
        self.market_data_cache[symbol] = {
            'bid': bid,
            'ask': ask,
            'mid': mid,
            'spread': spread,
            'spread_bps': spread_bps,
            'volume': volume,
            'volatility': volatility,
            'timestamp': time.time()
        }
    
    def record_order_submission(self, order_id: str, symbol: str, side: str,
                                quantity: float, order_type: str,
                                limit_price: Optional[float] = None) -> FillQualityMetrics:
        """Record order submission for slippage tracking"""
        market = self.market_data_cache.get(symbol, {})
        arrival_price = market.get('mid', 0)
        mid_price = market.get('mid', 0)
        spread_bps = market.get('spread_bps', 0)
        
        metrics = FillQualityMetrics(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            requested_qty=0,  # Will be updated on fills
            filled_qty=0,
            avg_fill_price=0,
            arrival_price=arrival_price,
            mid_price=mid_price,
            order_time=time.time(),
            spread_bps=spread_bps,
            volatility=market.get('volatility', 0)
        )
        
        self.fill_quality.append(metrics)
        return metrics
    
    def record_fill(self, order_id: str, fill_price: float, fill_qty: float,
                    timestamp: Optional[float] = None):
        """Record a fill event"""
        timestamp = timestamp or time.time()
        
        # Find the fill quality metrics
        metrics = None
        for mq in self.fill_quality:
            if mq.order_id == order_id:
                metrics = mq
                break
        
        if not metrics:
            logger.warning(f"Fill for unknown order: {order_id}")
            return
        
        # Update fill metrics
        if metrics.filled_qty == 0:
            metrics.first_fill_time = timestamp
        metrics.last_fill_time = timestamp
        metrics.filled_qty += fill_qty
        
        # Update average fill price
        if metrics.filled_qty > 0:
            prev_notional = metrics.avg_fill_price * (metrics.filled_qty - fill_qty)
            metrics.avg_fill_price = (prev_notional + fill_price * fill_qty) / metrics.filled_qty
        
        metrics.execution_duration_ms = (metrics.last_fill_time - metrics.first_fill_time) * 1000
        
        # Calculate slippage metrics
        self._calculate_slippage(metrics)
        
        # Update execution window for VWAP
        self._update_execution_window(metrics.symbol, fill_price, fill_qty, timestamp)
    
    def _calculate_slippage(self, metrics: FillQualityMetrics):
        """Calculate all slippage metrics"""
        if metrics.filled_qty == 0 or metrics.avg_fill_price <= 0:
            return
        
        side_mult = 1 if metrics.side.lower() == 'buy' else -1
        
        # Arrival slippage (vs price at order submission)
        if metrics.arrival_price > 0:
            metrics.arrival_slippage_bps = side_mult * (
                (metrics.avg_fill_price - metrics.arrival_price) / metrics.arrival_price
            ) * 10000
            metrics.arrival_slippage_usd = (
                metrics.avg_fill_price - metrics.arrival_price
            ) * metrics.filled_qty
        
        # Midpoint slippage (vs mid price)
        if metrics.mid_price > 0:
            metrics.midpoint_slippage_bps = side_mult * (
                (metrics.avg_fill_price - metrics.mid_price) / metrics.mid_price
            ) * 10000
            metrics.midpoint_slippage_usd = (
                metrics.avg_fill_price - metrics.mid_price
            ) * metrics.filled_qty
        
        # VWAP slippage
        window = self.execution_windows.get(metrics.symbol)
        if window and window.vwap > 0:
            metrics.vwap_price = window.vwap
            metrics.vwap_slippage_bps = side_mult * (
                (metrics.avg_fill_price - window.vwap) / window.vwap
            ) * 10000
        
        # TWAP slippage
        if window and window.twap > 0:
            metrics.twap_price = window.twap
            metrics.twap_slippage_bps = side_mult * (
                (metrics.avg_fill_price - window.twap) / window.twap
            ) * 10000
        
        # Implementation shortfall (total cost vs arrival)
        metrics.implementation_shortfall_bps = metrics.arrival_slippage_bps
        
        # Price improvement (negative slippage = improvement)
        if metrics.arrival_slippage_bps < 0:
            metrics.price_improvement_bps = abs(metrics.arrival_slippage_bps)
        
        # Fill rate
        metrics.fill_rate = metrics.filled_qty / metrics.requested_qty if metrics.requested_qty > 0 else 0
    
    def _update_execution_window(self, symbol: str, price: float, qty: float, timestamp: float):
        """Update execution window for VWAP/TWAP"""
        if symbol not in self.execution_windows:
            self.execution_windows[symbol] = ExecutionWindow(
                symbol=symbol,
                start_time=timestamp,
                end_time=timestamp
            )
        
        window = self.execution_windows[symbol]
        window.trades.append({'price': price, 'qty': qty, 'timestamp': timestamp})
        window.end_time = timestamp
        
        # Keep only last hour of trades
        cutoff = timestamp - 3600
        window.trades = [t for t in window.trades if t['timestamp'] >= cutoff]
    
    def finalize_order(self, order_id: str, requested_qty: float) -> Optional[FillQualityMetrics]:
        """Finalize order metrics"""
        for mq in self.fill_quality:
            if mq.order_id == order_id:
                mq.requested_qty = requested_qty
                mq.fill_rate = mq.filled_qty / requested_qty if requested_qty > 0 else 0
                return mq
        return None
    
    def get_slippage_stats(self, symbol: Optional[str] = None, 
                           hours: float = 24) -> Dict:
        """Get aggregated slippage statistics"""
        cutoff = time.time() - hours * 3600
        
        relevant = [
            m for m in self.fill_quality
            if m.order_time >= cutoff and (symbol is None or m.symbol == symbol)
        ]
        
        if not relevant:
            return {}
        
        arrival_bps = [m.arrival_slippage_bps for m in relevant if m.arrival_slippage_bps != 0]
        mid_bps = [m.midpoint_slippage_bps for m in relevant if m.midpoint_slippage_bps != 0]
        vwap_bps = [m.vwap_slippage_bps for m in relevant if m.vwap_slippage_bps is not None]
        impl_bps = [m.implementation_shortfall_bps for m in relevant if m.implementation_shortfall_bps != 0]
        
        def stats(values):
            if not values:
                return {'count': 0, 'mean': 0, 'median': 0, 'p95': 0, 'p99': 0}
            sorted_vals = sorted(values)
            return {
                'count': len(values),
                'mean': statistics.mean(values),
                'median': statistics.median(values),
                'p95': sorted_vals[int(len(sorted_vals) * 0.95)] if len(sorted_vals) > 20 else max(values),
                'p99': sorted_vals[int(len(sorted_vals) * 0.99)] if len(sorted_vals) > 100 else max(values),
                'min': min(values),
                'max': max(values)
            }
        
        return {
            'symbol': symbol or 'all',
            'hours': hours,
            'order_count': len(relevant),
            'fill_rate_avg': statistics.mean([m.fill_rate for m in relevant if m.fill_rate > 0]) if relevant else 0,
            'arrival_slippage': stats(arrival_bps),
            'midpoint_slippage': stats(mid_bps),
            'vwap_slippage': stats(vwap_bps),
            'implementation_shortfall': stats(impl_bps),
            'total_volume': sum(m.filled_qty for m in relevant),
            'total_notional': sum(m.filled_qty * m.avg_fill_price for m in relevant)
        }
    
    def get_symbol_breakdown(self, hours: float = 24) -> Dict:
        """Get slippage breakdown by symbol"""
        cutoff = time.time() - hours * 3600
        relevant = [m for m in self.fill_quality if m.order_time >= cutoff]
        
        by_symbol = defaultdict(list)
        for m in relevant:
            by_symbol[m.symbol].append(m)
        
        result = {}
        for symbol, metrics in by_symbol.items():
            result[symbol] = self.get_slippage_stats(symbol, hours)
        
        return result
    
    def get_recent_poor_executions(self, threshold_bps: float = 50, 
                                   hours: float = 24) -> List[FillQualityMetrics]:
        """Get orders with high slippage"""
        cutoff = time.time() - hours * 3600
        return [
            m for m in self.fill_quality
            if m.order_time >= cutoff 
            and abs(m.arrival_slippage_bps) > threshold_bps
        ]
    
    def clear_old_data(self, max_age_hours: float = 168):  # 1 week
        """Clear old execution windows"""
        cutoff = time.time() - max_age_hours * 3600
        for symbol in list(self.execution_windows.keys()):
            window = self.execution_windows[symbol]
            window.trades = [t for t in window.trades if t['timestamp'] >= cutoff]
            if not window.trades:
                del self.execution_windows[symbol]


# Convenience functions for quick analysis
def analyze_execution_quality(fills: List[Dict], arrival_prices: Dict[str, float],
                              mid_prices: Dict[str, float]) -> List[Dict]:
    """
    Analyze execution quality from raw fills.
    
    Args:
        fills: List of {order_id, symbol, side, price, qty, timestamp}
        arrival_prices: symbol -> arrival price
        mid_prices: symbol -> mid price at order time
        
    Returns:
        List of execution quality metrics per order
    """
    from collections import defaultdict
    
    # Group fills by order
    by_order = defaultdict(list)
    for fill in fills:
        by_order[fill['order_id']].append(fill)
    
    results = []
    for order_id, order_fills in by_order.items():
        symbol = order_fills[0]['symbol']
        side = order_fills[0]['side']
        
        total_qty = sum(f['qty'] for f in order_fills)
        avg_price = sum(f['price'] * f['qty'] for f in order_fills) / total_qty
        
        arrival = arrival_prices.get(symbol, 0)
        mid = mid_prices.get(symbol, 0)
        
        side_mult = 1 if order_fills[0]['side'] == 'buy' else -1
        
        result = {
            'order_id': order_id,
            'symbol': symbol,
            'side': side,
            'total_qty': sum(f['qty'] for f in order_fills),
            'avg_fill_price': sum(f['price'] * f['qty'] for f in order_fills) / total_qty,
            'arrival_slippage_bps': side_mult * (avg_price - arrival_prices[symbol]) / arrival_prices[symbol] * 10000 if arrival else 0,
            'midpoint_slippage_bps': side_mult * (avg_price - mid_prices[symbol]) / mid_prices[symbol] * 10000 if mid_prices[symbol] else 0,
            'fill_count': len(order_fills),
            'first_fill': min(f['timestamp'] for f in order_fills),
            'last_fill': max(f['timestamp'] for f in order_fills)
        }
        results.append(result)
    
    return results