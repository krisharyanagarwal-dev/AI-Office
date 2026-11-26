"""Multi-day backtest state management for the best-signal bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BacktestState:
    """Mutable state carried across all backtest timestamps."""

    equity: float
    working: dict[str, dict] = field(default_factory=dict)
    day_state: dict[str, dict] = field(default_factory=dict)
    equity_curve: list[dict] = field(default_factory=list)

    @classmethod
    def initial(cls, equity: float) -> "BacktestState":
        return cls(
            equity=equity,
            working={},
            day_state={},
            equity_curve=[],
        )

    def get_day_key(self, ts_ms: int) -> str:
        """UTC date string for day bucketing."""
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()

    def ensure_day(self, ts_ms: int) -> dict:
        """Get or create day state bucket."""
        day_key = self.get_day_key(ts_ms)
        if day_key not in self.day_state:
            self.day_state[day_key] = {"funding": 0.0, "fees": 0.0, "pnl": 0.0}
        return self.day_state[day_key]

    def snapshot_venue(self, broker: Any, ts_ms: int) -> dict:
        """Capture venue state for equity curve point."""
        cash = broker.balances.get("USDT", 0.0)
        realized = sum(broker.realized_pnl.values())
        margin = sum(broker.margin_used.values())
        fees = broker.fees_total
        current_equity = self.equity + realized

        return {
            "ts_ms": ts_ms,
            "equity": round(current_equity, 8),
            "pnl": round(current_equity - self.equity, 8),
            "cash": round(cash, 8),
            "margin": round(margin, 8),
            "fees": round(fees, 8),
            "realized_pnl": round(realized, 8),
        }

    def record_equity_point(self, snapshot: dict) -> None:
        self.equity_curve.append(snapshot)