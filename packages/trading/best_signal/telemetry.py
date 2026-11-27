"""Paper-only execution telemetry: one JSONL line per symbol cycle.

Appends a small record per cycle capturing slippage, latency, partial-fill,
fees, and fill outcome so the execution realism built into the paper venue
is observable in artifacts. No exchange access, no live venue, no credentials.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from best_signal.execution import ExecutionResult


@dataclass
class CycleMetrics:
    """One symbol cycle's execution telemetry."""

    cycle_ts: str
    symbol: str
    action: str
    side: int
    notional: float
    slippage_bps: float
    latency_ms: float
    partial_fill: bool
    filled: bool
    filled_qty: float
    fill_price: Optional[float]
    fees: float
    reason: str
    # NEW FIELDS
    actual_slippage_bps: float = 0.0
    bid_ask_spread_bps: float = 0.0
    fill_timeline: list[dict] = field(default_factory=list)


class TelemetrySink:
    """Append-only JSONL telemetry sink for paper-mode cycles."""

    def __init__(self, path: Path, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, metrics: CycleMetrics) -> None:
        if not self.enabled:
            return
        line = json.dumps(asdict(metrics), separators=(",", ":"))
        with self.path.open("a") as fh:
            fh.write(line + "\n")


def _filled_qty_and_price(result: ExecutionResult) -> tuple[float, Optional[float]]:
    """Aggregate filled quantity and price from the result's legs."""
    if not result.legs:
        return 0.0, None
    total_qty = sum(leg.quantity for leg in result.legs)
    price = result.legs[0].price if result.legs else None
    return total_qty, price


def _compute_actual_slippage_and_timeline(
    broker, symbol: str, side: int, mid_price: float
) -> tuple[float, float, list[dict]]:
    """Compute actual slippage, spread, and fill timeline from broker's fill journal."""
    journal = getattr(broker, "fill_journal", None)
    if journal is None or not getattr(journal, "enabled", False):
        return 0.0, 0.0, []

    # Read fills from journal for this symbol
    fills_data = []
    if journal.path.exists():
        try:
            with journal.path.open("r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    fill_data = json.loads(line)
                    if fill_data.get("symbol") == symbol:
                        fills_data.append(fill_data)
        except (json.JSONDecodeError, OSError):
            pass

    if not fills_data:
        return 0.0, 0.0, []

    # Compute actual slippage from fills
    # For a buy: (fill_price - mid_price) / mid_price * 10000
    # For a sell: (mid_price - fill_price) / mid_price * 10000
    total_slippage_bps = 0.0
    total_qty = 0.0
    timeline = []
    spread_bps = 0.0

    for fill in fills_data:
        fill_price = fill.get("price", 0.0)
        fill_qty = fill.get("quantity", 0.0)
        fill_mid = fill.get("mid_price", mid_price)

        if fill_mid > 0 and fill_qty > 0:
            if side >= 0:  # buy
                slippage = (fill_price - fill_mid) / fill_mid * 10000
            else:  # sell
                slippage = (fill_mid - fill_price) / fill_mid * 10000
            total_slippage_bps += slippage * fill_qty
            total_qty += fill_qty

        # Use the spread from the first fill (they should be similar)
        if spread_bps == 0.0 and "spread_bps" in fill:
            spread_bps = fill.get("spread_bps", 0.0)

        # Build timeline entry
        timeline.append({
            "ts": fill.get("ts"),
            "price": fill_price,
            "quantity": fill_qty,
            "side": fill.get("side"),
            "slippage_bps": fill.get("slippage_bps", 0.0),
            "spread_bps": fill.get("spread_bps", 0.0),
            "fill_fraction": fill.get("fill_fraction", 1.0),
            "leg_sequence": fill.get("leg_sequence", 0),
            "venue_latency_ms": fill.get("venue_latency_ms", 0.0),
        })

    actual_slippage_bps = total_slippage_bps / total_qty if total_qty > 0 else 0.0
    return round(actual_slippage_bps, 1), round(spread_bps, 1), timeline


def record_cycle(
    sink: TelemetrySink,
    symbol: str,
    side: int,
    notional: float,
    action: str,
    result: ExecutionResult,
    broker,
) -> None:
    """Record one symbol cycle's execution telemetry to the sink."""
    realism = getattr(broker, "realism", None)
    filled_qty, fill_price = _filled_qty_and_price(result)

    # Compute mid price from order/result for slippage calculation
    mid_price = fill_price if fill_price is not None else 0.0
    if mid_price == 0.0 and result.legs:
        mid_price = result.legs[0].price

    # Compute actual execution metrics from fill journal
    actual_slippage_bps, bid_ask_spread_bps, fill_timeline = _compute_actual_slippage_and_timeline(
        broker, symbol, side, mid_price
    )

    metrics = CycleMetrics(
        cycle_ts=datetime.now(timezone.utc).isoformat(),
        symbol=symbol,
        action=action,
        side=side,
        notional=notional,
        slippage_bps=getattr(realism, "slippage_bps", 0.0),
        latency_ms=getattr(realism, "latency_ms", 0.0),
        partial_fill=bool(result.partial),
        filled=bool(result.filled),
        filled_qty=filled_qty,
        fill_price=fill_price,
        fees=result.fees,
        reason=result.reason,
        actual_slippage_bps=actual_slippage_bps,
        bid_ask_spread_bps=bid_ask_spread_bps,
        fill_timeline=fill_timeline,
    )
    sink.record(metrics)
