"""Paper-only fill journal: append-only JSONL capture of every fill."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class FillRecord:
    """One fill captured from the paper venue."""

    ts: str
    symbol: str
    market: str
    side: str
    quantity: float
    price: float
    mid_price: float
    fees: float
    slippage_bps: float
    latency_ms: float
    partial_fill: bool
    order_id: str
    venue: str = "paper"
    mode: str = "PAPER"

    def to_dict(self) -> dict:
        return asdict(self)


class FillJournal:
    """Append-only JSONL fill journal for paper-mode fills."""

    def __init__(self, path: Path, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, fill_record: FillRecord) -> None:
        if not self.enabled:
            return
        line = json.dumps(fill_record.to_dict(), separators=(",", ":"))
        with self.path.open("a") as fh:
            fh.write(line + "\n")


def record_fill(journal: FillJournal, fill, order, broker) -> None:
    """Create FillRecord from venue Fill, Order, and broker realism, then journal it."""
    # Extract mid price from order (price at submission time)
    mid_price = getattr(order, "price", 0.0) or 0.0

    # Slippage: (fill_price - mid_price) / mid_price * 10000, signed by side
    slippage_bps = 0.0
    fill_side = getattr(fill, "side", "buy")
    if mid_price > 0:
        if fill_side == "buy" or (hasattr(fill_side, "value") and fill_side.value == "buy"):
            slippage_bps = round((fill.price - mid_price) / mid_price * 10_000, 1)
        else:
            slippage_bps = round((mid_price - fill.price) / mid_price * 10_000, 1)

    realism = getattr(broker, "realism", None)

    # Serialize side to string if it's an enum
    side_str = fill_side.value if hasattr(fill_side, "value") else str(fill_side)

    rec = FillRecord(
        ts=datetime.now(timezone.utc).isoformat(),
        symbol=fill.symbol,
        market="perp" if fill.symbol.endswith("_PERP") else "spot",
        side=side_str,
        quantity=fill.quantity,
        price=fill.price,
        mid_price=mid_price,
        fees=fill.commission,
        slippage_bps=slippage_bps,
        latency_ms=getattr(realism, "latency_ms", 0.0),
        partial_fill=getattr(fill, "partial_fill", False),
        order_id=fill.order_id,
    )
    journal.record(rec)