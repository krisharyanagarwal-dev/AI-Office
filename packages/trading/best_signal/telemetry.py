"""Paper-only execution telemetry: one JSONL line per symbol cycle.

Appends a small record per cycle capturing slippage, latency, partial-fill,
fees, and fill outcome so the execution realism built into the paper venue
is observable in artifacts. No exchange access, no live venue, no credentials.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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
    )
    sink.record(metrics)
