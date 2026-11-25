"""
Unified paper-trading control plane orchestrator.

Runs multiple paper bots (best-signal first; fundamentals-driven execution
added later) in paper mode with kill-switch gating, persists a consolidated
state snapshot to the single SQLite StateStore (source of truth for the
unified API), and exposes start/stop control.

Paper-mode only: no live broker code path, no exchange credentials, and the
kill switch can stand every bot down at any time.
"""
from __future__ import annotations

import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup so the alpha package and the best_signal pipeline import cleanly,
# mirroring the convention in all_in_one_bot.py.
# ---------------------------------------------------------------------------
_TRADING_ROOT = Path(__file__).resolve().parents[2]          # .../packages/trading
_REPO_ROOT = _TRADING_ROOT.parent.parent                     # .../AI-Office
for _p in (str(_TRADING_ROOT), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from alpha.brain.state_store import StateStore

from best_signal.runner import BotConfig, run_bot
from best_signal.position import RiskLimits

DEFAULT_DB_PATH = "/Users/aryanagarwal/AI-Office/data/all_in_one_state.db"
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEFAULT_EQUITY = 10_000.0
DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports" / "best_signal"


@dataclass
class OrchestratorConfig:
    """Configuration shared by every bot the orchestrator runs."""

    db_path: str = DEFAULT_DB_PATH
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    equity: float = DEFAULT_EQUITY
    limits: RiskLimits = field(default_factory=RiskLimits)
    validate: bool = False
    data_dir: Optional[Path] = None
    out_dir: Optional[Path] = None
    kill_switch: bool = False


class Orchestrator:
    """Central control plane for paper-trading bots.

    A single SQLite StateStore is the source of truth. Each cycle runs every
    registered bot in paper mode, then writes a consolidated `last_run`
    record (including a unified-API-compatible portfolio snapshot) so the
    dashboard API can serve /api/portfolio, /api/risk and /api/performance
    without touching any live venue.
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()
        self.run_id = f"orch-{uuid.uuid4().hex[:8]}"
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Single SQLite StateStore, source of truth for the unified API.
        self.state_store = StateStore({"path": self.config.db_path})

        self.running = False
        self.kill_switch = bool(self.config.kill_switch)
        self.config.limits = replace(self.config.limits, kill_switch=self.kill_switch)

        # Run history (most recent first).
        self.sessions: List[Dict[str, Any]] = []

        # Latest consolidated portfolio snapshot.
        self.last_portfolio: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Control surface
    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self.running

    def set_kill_switch(self, enabled: bool) -> None:
        """Gate all bots on/off. When on, every bot stands down (NO_TRADE)."""
        self.kill_switch = bool(enabled)
        self.config.limits = replace(self.config.limits, kill_switch=self.kill_switch)

    def _control_action(self) -> Optional[str]:
        """Return the persisted bot_control action ('start' | 'stop'), or None."""
        bot_control = self.state_store.get("bot_control", category="all_in_one")
        if isinstance(bot_control, dict):
            action = bot_control.get("action")
            if action in ("start", "stop"):
                return action
        return None

    def _apply_control_state(self) -> None:
        """Apply control intent persisted by the unified API before any bot runs.

        Reads bot_control and risk_limits from the shared StateStore and applies
        the kill switch and risk limits to this cycle's config. A ``stop`` action
        triggers the stand-down handled by the caller via _control_action().
        """
        bot_control = self.state_store.get("bot_control", category="all_in_one")
        if isinstance(bot_control, dict) and bot_control.get("killSwitch") is not None:
            self.kill_switch = bool(bot_control["killSwitch"])
            self.config.limits = replace(self.config.limits, kill_switch=self.kill_switch)

        risk_limits = self.state_store.get("risk_limits", category="all_in_one")
        if isinstance(risk_limits, dict):
            updates = {
                key: risk_limits[key]
                for key in (
                    "max_symbol_notional",
                    "max_gross_notional",
                    "max_position_weight",
                    "max_symbols",
                    "max_daily_loss_pct",
                    "kill_switch",
                )
                if key in risk_limits
            }
            if updates:
                if "kill_switch" in updates:
                    self.kill_switch = bool(updates["kill_switch"])
                self.config.limits = replace(self.config.limits, **updates)

    def start(self) -> Dict[str, Any]:
        """Run one paper-trading cycle. Returns the session snapshot."""
        if self.running:
            return {"status": "already_running", "run_id": self.run_id}
        self.running = True
        try:
            return self.run_cycle()
        finally:
            self.running = False

    def stop(self) -> Dict[str, Any]:
        """Stand the orchestrator down; no new cycles will start."""
        self.running = False
        return {"status": "stopped", "run_id": self.run_id}

    # ------------------------------------------------------------------
    # Execution cycle
    # ------------------------------------------------------------------
    def run_cycle(self) -> Dict[str, Any]:
        """Run all configured bots in paper mode and persist consolidated state.

        Control intent persisted by the unified API (bot_control / risk_limits in
        the shared StateStore) is honored before any bot runs: risk limits and the
        kill switch are applied, and a ``stop`` action stands every symbol down.
        """
        self._apply_control_state()

        session: Dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "paper_only": True,
            "kill_switch": self.kill_switch,
            "symbols": {},
            "bots": {},
        }

        stopped = self._control_action() == "stop"
        if stopped:
            best_signal_result = {
                "status": "ok",
                "mode": "paper",
                "execution_enabled": False,
                "live": False,
                "positions": {},
                "signals": [],
                "paths": {},
                "symbols": {
                    symbol: {"action": "NO_TRADE", "side": 0, "notional": 0.0, "reason": "stopped"}
                    for symbol in self.config.symbols
                },
            }
        else:
            best_signal_result = self._run_best_signal()
        session["bots"]["best_signal"] = best_signal_result
        session["symbols"].update(best_signal_result.get("symbols", {}))

        # Consolidated portfolio snapshot, persisted as `last_run` so the
        # unified API can serve /api/portfolio from this StateStore.
        portfolio = self._build_portfolio(best_signal_result)
        self.last_portfolio = portfolio
        self._persist_last_run(portfolio, session)

        session["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        session["portfolio"] = portfolio
        self.sessions.insert(0, dict(session))
        return session

    def _run_best_signal(self) -> Dict[str, Any]:
        """Run the best-signal bot in paper mode."""
        out_dir = self.config.out_dir or DEFAULT_REPORTS_DIR
        config = BotConfig(
            symbols=self.config.symbols,
            data_dir=self.config.data_dir,
            out_dir=out_dir,
            state_path=None,
            equity=self.config.equity,
            limits=self.config.limits,
            validate=self.config.validate,
            daily_loss_pct=0.0,
        )
        try:
            result = run_bot(config)
        except FileNotFoundError as exc:
            return {"status": "error", "error": f"data unavailable: {exc}", "symbols": {}}
        except (ValueError, OSError) as exc:
            return {"status": "error", "error": f"run failed: {exc}", "symbols": {}}

        positions = result.get("positions", [])
        by_symbol: Dict[str, Any] = {}
        for position in positions:
            entry = position.to_dict() if hasattr(position, "to_dict") else dict(position)
            by_symbol[str(entry.get("symbol"))] = entry

        return {
            "status": "ok",
            "mode": "paper",
            "execution_enabled": False,
            "live": False,
            "positions": by_symbol,
            "signals": (result.get("report") or {}).get("signals", []),
            "paths": result.get("paths", {}),
            "symbols": {
                symbol: {
                    "action": entry.get("action"),
                    "side": entry.get("side"),
                    "notional": entry.get("notional"),
                    "reason": entry.get("reason"),
                }
                for symbol, entry in by_symbol.items()
            },
        }

    def _build_portfolio(self, best_signal_result: Dict[str, Any]) -> Dict[str, Any]:
        """Build a unified-API-compatible portfolio snapshot.

        The unified API's portfolioFromRecord expects:
          broker, currency, cash, market_value, equity, realized_pnl,
          unrealized_pnl, total_pnl, peak_equity, max_drawdown/drawdown,
          positions[{symbol: {quantity, avg_entry_price, mark_price,
          unrealized_pnl, realized_pnl]}], timestamp
        """
        positions = best_signal_result.get("positions", {})
        position_summaries: Dict[str, Any] = {}
        cash = float(self.config.equity)
        market_value = 0.0
        total_realized = 0.0
        total_unrealized = 0.0

        for symbol, pos in positions.items():
            qty = float(pos.get("quantity", 0.0) or 0.0)
            avg = float(pos.get("avg_entry_price", 0.0) or 0.0)
            realized = float(pos.get("realized_pnl", 0.0) or 0.0)
            unrealized = float(pos.get("unrealized_pnl", 0.0) or 0.0)
            mark = float(pos.get("mark_price", avg) or avg)
            total_realized += realized
            total_unrealized += unrealized
            if qty != 0:
                market_value += qty * mark
            position_summaries[symbol] = {
                "quantity": qty,
                "avg_entry_price": avg,
                "unrealized_pnl": unrealized,
                "realized_pnl": realized,
                "mark_price": mark,
            }

        equity = cash + market_value
        total_pnl = total_realized + total_unrealized

        return {
            "broker": "paper",
            "currency": "USDT",
            "cash": cash,
            "market_value": market_value,
            "equity": equity,
            "realized_pnl": total_realized,
            "unrealized_pnl": total_unrealized,
            "total_pnl": total_pnl,
            "peak_equity": equity,
            "max_drawdown": 0.0,
            "drawdown": 0.0,
            "positions": position_summaries,
            "timestamp": time.time(),
        }

    # ------------------------------------------------------------------
    # Persistence: single SQLite StateStore (source of truth)
    # ------------------------------------------------------------------
    @staticmethod
    def _jsonable(value: Any) -> Any:
        """Recursively convert non-JSON-serializable values (e.g. pathlib.Path)
        so the consolidated payload round-trips through json.dumps in StateStore."""
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {key: Orchestrator._jsonable(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [Orchestrator._jsonable(val) for val in value]
        return value

    def _persist_last_run(self, portfolio: Dict[str, Any], session: Dict[str, Any]) -> None:
        payload = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "paper",
            "execution_enabled": False,
            "live_trading": False,
            "live": False,
            "status": "ok",
            "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "portfolio": portfolio,
            "session": session,
        }
        try:
            self.state_store.set("last_run", self._jsonable(payload), category="all_in_one")
        except Exception:
            # Persistence must never kill a session.
            pass

    def get_consolidated_state(self) -> Dict[str, Any]:
        """Read the consolidated state from the StateStore (source of truth)."""
        try:
            return self.state_store.get("last_run", default={}, category="all_in_one") or {}
        except Exception:
            return {}

    def close(self) -> None:
        try:
            self.state_store.close()
        except Exception:
            pass
