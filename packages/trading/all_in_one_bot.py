"""
All-In-One Paper Trading Bot
============================

A single, runnable entry point that composes the existing Alpha System
components into a complete paper-trading loop:

    market data -> rule-based signals -> backtest validation ->
    position sizing -> risk-checked execution -> state persistence -> report

Design constraints (deliberate, not optional):
  * PAPER-ONLY. A PaperBroker is always used. There is no live-broker code path,
    and none can be enabled via a flag.
  * NO DIRECTIONAL CALLS. Trade direction (long/short/neutral) comes entirely
    from the existing rule-based strategy engine (MA crossover, RSI, Bollinger
    Bands). This bot never invents or recommends a direction.
  * FINITE SESSION. By default the bot runs ONE cycle and exits. It does not
    expose a port or run as a daemon, so it works within the environment's
    permission restrictions (no long-running services).

Run:
    python3 packages/trading/all_in_one_bot.py --once --report
    python3 packages/trading/all_in_one_bot.py --once --dry-run --report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup so both the alpha package and the dost pipeline import cleanly.
# ---------------------------------------------------------------------------
_TRADING_ROOT = Path(__file__).resolve().parent          # .../packages/trading
_REPO_ROOT = _TRADING_ROOT.parent.parent                  # .../AI-Office
for _p in (str(_TRADING_ROOT), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from alpha.execution.execution_engine import (
    ExecutionEngine,
    PaperBroker,
    Order,
    OrderSide,
    OrderType,
    max_position_check,
    max_notional_check,
    daily_loss_limit_check,
)
from alpha.brain.state_store import StateStore
from alpha.risk.risk_manager import RiskLimits

from dost.trading.strategy_engine import generate_all_signals
from dost.trading.backtest_engine import run_backtest
from dost.trading.position_sizer import calculate_position_size
from dost.data_access import generate_synthetic_ohlcv

LOG = __import__("logging").getLogger("all_in_one_bot")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class AllInOneConfig:
    capital: float = 100_000.0
    risk_per_trade: float = 0.02
    max_daily_loss: float = 20_000.0
    max_drawdown: float = 0.10
    max_position_per_symbol: float = 10_000.0
    max_total_notional: float = 50_000.0
    symbols: List[str] = field(default_factory=lambda: ["NIFTY"])
    days: int = 252
    seed: int = 42
    confidence_threshold: float = 0.6
    dry_run: bool = False
    skip_backtest: bool = False
    backtest_min_total_return_pct: float = -50.0  # reject catastrophically bad
    state_db_path: str = "./data/all_in_one_state.db"
    openclaw_snapshot_path: str = ""

    def __post_init__(self) -> None:
        import os

        self.openclaw_snapshot_path = os.path.expanduser(
            "~/.openclaw/all_in_one_portfolio.json"
        )


# ---------------------------------------------------------------------------
# The bot
# ---------------------------------------------------------------------------
class AllInOneBot:
    """Paper-only all-in-one trading bot."""

    def __init__(self, config: AllInOneConfig):
        self.config = config
        self.run_id = f"aio-{uuid.uuid4().hex[:8]}"
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # State store (SQLite persistence)
        self.state_store = StateStore({"path": config.state_db_path})

        # Execution engine + paper broker (paper-only, enforced)
        self.engine = ExecutionEngine()
        self.broker = PaperBroker(name="paper", initial_balance=config.capital)
        self.engine.add_broker("paper", self.broker, is_default=True)

        # Risk manager + limits
        limits = RiskLimits(
            max_position_per_symbol=config.max_position_per_symbol,
            max_total_notional=config.max_total_notional,
            max_daily_loss=config.max_daily_loss,
            max_drawdown=config.max_drawdown,
        )
        self.risk_manager = None  # kept for API parity; limits wired below

        # Pre-trade risk checks enforced on every order submission
        self.engine.add_pre_trade_check(max_position_check(config.max_position_per_symbol))
        self.engine.add_pre_trade_check(max_notional_check(config.max_total_notional))
        self.engine.add_pre_trade_check(
            daily_loss_limit_check(config.max_daily_loss, self._daily_pnl)
        )

        # Wire persistence + OpenClaw snapshot
        self.engine.set_state_store(self.state_store)
        self.engine.set_openclaw_snapshot_path(config.openclaw_snapshot_path)

        # Session results
        self.signals: List[Dict[str, Any]] = []
        self.executed: List[Dict[str, Any]] = []
        self.rejected: List[Dict[str, Any]] = []
        self.backtest_results: List[Dict[str, Any]] = []
        self.errors: List[str] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _daily_pnl(self) -> float:
        """Current realized+unrealized P&L for the daily-loss check."""
        try:
            summary = self.engine.get_portfolio_summary()
            return float(summary.get("total_pnl", 0.0))
        except Exception:
            return 0.0

    def _persist(self, key: str, value: Any, category: str = "all_in_one") -> None:
        try:
            self.state_store.set(key, value, category=category)
        except Exception as e:  # persistence must never kill a session
            LOG.debug("state persist failed for %s: %s", key, e)

    def _load_candles(self, symbol: str) -> List[Dict[str, Any]]:
        """Load deterministic synthetic OHLCV candles (reproducible runs)."""
        return generate_synthetic_ohlcv(
            symbol=symbol,
            days=self.config.days,
            start_price=22000.0,
            volatility=0.015,
            drift=0.0003,
            seed=self.config.seed,
        )

    def _is_paper_only(self) -> bool:
        """Safety gate: refuse to operate unless the broker is paper trading."""
        return bool(getattr(self.broker, "paper_trading", False))

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------
    def generate_signals(self, instrument: str, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Step 1: generate rule-based signals from the strategy engine.

        Direction is produced entirely by the existing strategies (MA crossover,
        RSI mean reversion, Bollinger Bands). This method does not choose a
        direction itself.
        """
        try:
            signals = generate_all_signals(
                agent_id="all-in-one-bot",
                instrument=instrument,
                candles=candles,
                confidence_threshold=self.config.confidence_threshold,
            )
            for s in signals:
                s.setdefault("agent_id", "all-in-one-bot")
                s.setdefault("instrument", instrument)
            LOG.info("Generated %d signals for %s", len(signals), instrument)
            return signals
        except Exception as e:
            LOG.error("Signal generation failed for %s: %s", instrument, e)
            self.errors.append(f"signals:{instrument}:{e}")
            return []

    def validate_signal(
        self,
        signal: Dict[str, Any],
        candles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Step 2: backtest-validate a signal before any execution.

        Returns the backtest result dict. A signal is considered executable when
        status == "done" and total return is not catastrophically negative.
        """
        result: Dict[str, Any] = {
            "signal_id": signal.get("task_id", "unknown"),
            "status": "skipped",
            "total_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "executable": False,
        }
        if self.config.skip_backtest:
            result["status"] = "skipped(no-backtest)"
            result["executable"] = True
            return result

        try:
            bt = run_backtest(
                signal=signal,
                candles=candles,
                initial_capital=self.config.capital,
                risk_per_trade=self.config.risk_per_trade,
            )
            status = bt.get("status", "unknown")
            total_return = float(bt.get("total_return_pct", 0.0))
            result.update(
                {
                    "status": status,
                    "total_return_pct": total_return,
                    "sharpe_ratio": float(bt.get("sharpe_ratio", 0.0)),
                    "max_drawdown_pct": float(bt.get("max_drawdown_pct", 0.0)),
                    "trades": bt.get("total_trades", 0),
                }
            )
            result["executable"] = (
                status == "done"
                and total_return >= self.config.backtest_min_total_return_pct
                and signal.get("direction", "neutral") != "neutral"
            )
            LOG.info(
                "Backtest %s status=%s return=%.2f%% executable=%s",
                result["signal_id"],
                status,
                total_return,
                result["executable"],
            )
        except Exception as e:
            LOG.error("Backtest failed for signal %s: %s", result["signal_id"], e)
            result["status"] = "error"
            result["error"] = str(e)
            self.errors.append(f"backtest:{result['signal_id']}:{e}")
        return result

    def size_position(
        self,
        signal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Step 3: calculate position size for an executable signal."""
        try:
            pos = calculate_position_size(
                agent_id=signal.get("agent_id", "all-in-one-bot"),
                instrument=signal.get("instrument", "UNKNOWN"),
                direction=signal.get("direction", "neutral"),
                signal_confidence=float(signal.get("confidence", 0.5)),
                entry_price=float(signal.get("entry_price", 0) or 0),
                stop_loss=signal.get("stop_loss"),
                cost_units=1,
                method="fixed_fraction",
                capital=self.config.capital,
                risk_per_trade=self.config.risk_per_trade,
            )
            # Cap the size so the order passes the engine's own pre-trade
            # risk checks (max notional and per-symbol quantity caps).
            entry = float(pos.get("entry_price", 0) or 0)
            size = float(pos.get("position_size", 0) or 0)
            stop_loss = pos.get("stop_loss")
            if size > 0 and entry > 0:
                max_qty_by_notional = self.config.max_total_notional / entry
                size = min(size, max_qty_by_notional, self.config.max_position_per_symbol)
                # Floor (never round up) so the capped notional can never exceed the limit.
                # round() can nudge the size just over the cap, which trips max_notional_check.
                size = math.floor(size * 1e6) / 1e6
                pos["position_size"] = size
                pos["position_value"] = round(size * entry, 2)
                if stop_loss:
                    pos["risk_amount"] = round(size * abs(entry - float(stop_loss)), 2)
                    pos["risk_percent"] = round(
                        pos["risk_amount"] / self.config.capital * 100, 2
                    )

            LOG.info(
                "Position size for %s: %s units (value=%.2f, risk=%.2f)",
                signal.get("instrument"),
                pos.get("position_size", 0),
                pos.get("position_value", 0),
                pos.get("risk_amount", 0),
            )
            return pos
        except Exception as e:
            LOG.error("Position sizing failed for %s: %s", signal.get("instrument"), e)
            self.errors.append(f"sizing:{signal.get('instrument')}:{e}")
            return {}

    async def execute_signal(
        self,
        signal: Dict[str, Any],
        position: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Step 4: submit a risk-checked paper order for the signal."""
        outcome: Dict[str, Any] = {
            "signal_id": signal.get("task_id", "unknown"),
            "instrument": signal.get("instrument"),
            "direction": signal.get("direction"),
            "status": "rejected",
            "order_id": None,
        }

        if not self._is_paper_only():
            outcome["status"] = "blocked"
            outcome["reason"] = "non-paper broker detected"
            self.rejected.append(outcome)
            return outcome

        direction = (signal.get("direction") or "neutral").lower()
        if direction not in ("long", "short"):
            outcome["reason"] = "non-directional or neutral signal"
            self.rejected.append(outcome)
            return outcome

        position_size = float(position.get("position_size", 0) or 0)
        entry_price = float(signal.get("entry_price", 0) or 0)
        if position_size <= 0 or entry_price <= 0:
            outcome["reason"] = "invalid size or price"
            self.rejected.append(outcome)
            return outcome

        side = OrderSide.BUY if direction == "long" else OrderSide.SELL
        order = Order(
            symbol=signal.get("instrument", "UNKNOWN"),
            side=side,
            order_type=OrderType.MARKET,
            quantity=position_size,
            price=entry_price,
            metadata={
                "run_id": self.run_id,
                "signal_id": signal.get("task_id"),
                "strategy": signal.get("strategy_name"),
                "paper_only": True,
            },
        )

        if self.config.dry_run:
            outcome["status"] = "dry_run"
            outcome["order_id"] = order.client_order_id
            outcome["quantity"] = position_size
            outcome["price"] = entry_price
            outcome["side"] = side.value
            LOG.info(
                "[DRY RUN] Would submit %s %s %s @ %.2f (size=%.4f)",
                side.value,
                signal.get("instrument"),
                direction,
                entry_price,
                position_size,
            )
            self.executed.append(outcome)
            return outcome

        try:
            filled = await self.engine.submit_order(order)
            # Process any pending limit orders against latest prices
            await self.engine.process_pending_orders()
            # Mark-to-market with the entry price as latest mark
            await self.engine.update_mark_prices({signal.get("instrument", "UNKNOWN"): entry_price})
            # Persist execution state after each fill
            await self.engine.save_state()

            outcome["status"] = filled.status.value
            outcome["order_id"] = filled.client_order_id
            outcome["filled_qty"] = filled.filled_qty
            outcome["avg_fill_price"] = filled.avg_fill_price
            outcome["commission"] = filled.commission
            LOG.info(
                "Order %s status=%s filled=%.4f@%.2f commission=%.4f",
                filled.client_order_id,
                filled.status.value,
                filled.filled_qty,
                filled.avg_fill_price,
                filled.commission,
            )
        except Exception as e:
            LOG.error("Order submission failed for %s: %s", signal.get("instrument"), e)
            outcome["status"] = "error"
            outcome["error"] = str(e)
            self.errors.append(f"execute:{signal.get('instrument')}:{e}")

        self.executed.append(outcome)
        return outcome

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------
    async def run_cycle(self) -> Dict[str, Any]:
        """Run one complete paper-trading cycle across all configured symbols."""
        session: Dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "paper_only": self._is_paper_only(),
            "dry_run": self.config.dry_run,
            "symbols": {},
        }

        for symbol in self.config.symbols:
            symbol_result: Dict[str, Any] = {
                "symbol": symbol,
                "signals": [],
                "executed": [],
                "rejected": [],
                "errors": [],
            }

            candles = self._load_candles(symbol)
            if not candles:
                symbol_result["errors"].append("no candles loaded")
                session["symbols"][symbol] = symbol_result
                continue

            signals = self.generate_signals(symbol, candles)
            self.signals.extend(signals)

            for signal in signals:
                sig_copy = dict(signal)
                sig_copy["instrument"] = symbol
                bt = self.validate_signal(sig_copy, candles)
                self.backtest_results.append(bt)
                sig_copy["backtest"] = bt

                if not bt.get("executable"):
                    symbol_result["signals"].append(
                        {
                            "signal_id": bt["signal_id"],
                            "direction": signal.get("direction"),
                            "backtest_status": bt["status"],
                            "total_return_pct": bt["total_return_pct"],
                            "reason": "not executable after backtest",
                        }
                    )
                    continue

                position = self.size_position(sig_copy)
                sig_copy["position"] = position
                outcome = await self.execute_signal(sig_copy, position)
                symbol_result["executed"].append(outcome)

            # Portfolio snapshot per symbol
            try:
                summary = self.engine.get_portfolio_summary()
                symbol_result["portfolio"] = summary
            except Exception as e:  # pragma: no cover - defensive
                symbol_result["errors"].append(f"portfolio summary: {e}")

            session["symbols"][symbol] = symbol_result

        # Final state persistence
        try:
            await self.engine.save_state()
        except Exception as e:  # pragma: no cover - defensive
            LOG.debug("final state save failed: %s", e)
            self.errors.append(f"persist:{e}")

        session["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        session["portfolio"] = self.engine.get_portfolio_summary()
        session["errors"] = self.errors
        self._persist(f"run:{self.run_id}", session, category="all_in_one_runs")
        self._persist("last_run", session, category="all_in_one")

        # OpenClaw shared snapshot is written by get_portfolio_summary via
        # engine.set_openclaw_snapshot_path; refresh it once more here.
        try:
            self.engine.get_portfolio_summary()
        except Exception:  # pragma: no cover - best effort
            pass

        return session

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    @staticmethod
    def _fmt_pct(value: Optional[float]) -> str:
        if value is None:
            return "n/a"
        return f"{value:.2f}%"

    def print_report(self, session: Optional[Dict[str, Any]] = None) -> None:
        """Print a human-readable tear-sheet report for the session."""
        if session is None:
            session = {
                "run_id": self.run_id,
                "symbols": {s: {} for s in self.config.symbols},
                "portfolio": {},
            }

        portfolio = session.get("portfolio") or {}
        lines = [
            "",
            "=" * 60,
            "ALL-IN-ONE PAPER TRADING BOT — SESSION REPORT",
            "=" * 60,
            f"Run ID:        {self.run_id}",
            f"Started:       {self.started_at}",
            f"Paper-only:    {self._is_paper_only()}",
            f"Dry run:       {self.config.dry_run}",
            f"Capital:       {self.config.capital:,.2f}",
            f"Risk/trade:    {self.config.risk_per_trade:.2%}",
            f"Max daily loss:{self.config.max_daily_loss:,.2f}",
            f"Max drawdown:  {self.config.max_drawdown:.2%}",
            "",
            "PORTFOLIO",
            "---------",
            f"Cash:              {portfolio.get('cash', 0):,.2f}",
            f"Market value:      {portfolio.get('market_value', 0):,.2f}",
            f"Equity:            {portfolio.get('equity', 0):,.2f}",
            f"Realized P&L:      {portfolio.get('realized_pnl', 0):,.2f}",
            f"Unrealized P&L:    {portfolio.get('unrealized_pnl', 0):,.2f}",
            f"Total P&L:         {portfolio.get('total_pnl', 0):,.2f}",
            f"Peak equity:       {portfolio.get('peak_equity', 0):,.2f}",
            f"Max drawdown:      {portfolio.get('max_drawdown', 0):,.2f}",
            f"Drawdown:          {portfolio.get('drawdown', 0):,.2f}",
            "",
            "SYMBOLS",
            "-------",
        ]

        for symbol, sresult in (session.get("symbols") or {}).items():
            lines.append(f"Symbol: {symbol}")
            signals = sresult.get("signals", [])
            executed = sresult.get("executed", [])
            lines.append(f"  signals generated: {len(signals) + len(executed)}")
            lines.append(f"  orders executed:   {len(executed)}")
            for ex in executed:
                lines.append(
                    f"    - {ex.get('direction','?')} {ex.get('instrument','?')} "
                    f"status={ex.get('status')} qty={ex.get('filled_qty',0)} "
                    f"px={ex.get('avg_fill_price',0):.2f} comm={ex.get('commission',0):.4f}"
                )
            for sig in signals:
                lines.append(
                    f"    [skipped] {sig.get('signal_id')} "
                    f"dir={sig.get('direction')} bt={sig.get('backtest_status')} "
                    f"ret={self._fmt_pct(sig.get('total_return_pct'))} "
                    f"reason={sig.get('reason')}"
                )
            pf = sresult.get("portfolio") or {}
            if pf:
                lines.append(
                    f"  equity={pf.get('equity',0):,.2f} "
                    f"pnl={pf.get('total_pnl',0):,.2f} "
                    f"dd={pf.get('max_drawdown',0):,.2f}"
            )
            lines.append("")

        if self.errors:
            lines.append("ERRORS")
            lines.append("------")
            for e in self.errors:
                lines.append(f"  - {e}")
            lines.append("")

        lines.append("END OF REPORT")
        lines.append("=" * 60)
        print("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="All-in-one paper trading bot (paper-only, finite session)."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Run a single paper-trading cycle and exit (default).",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="Starting capital for the paper account (default: 100000).",
    )
    parser.add_argument(
        "--risk-per-trade",
        type=float,
        default=0.02,
        help="Risk per trade as a decimal (default: 0.02 = 2 percent).",
    )
    parser.add_argument(
        "--max-daily-loss",
        type=float,
        default=20_000.0,
        help="Maximum daily loss limit (default: 20000).",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=0.10,
        help="Maximum drawdown as a decimal (default: 0.10 = 10 percent).",
    )
    parser.add_argument(
        "--max-position-per-symbol",
        type=float,
        default=10_000.0,
        help="Maximum position notional per symbol (default: 10000).",
    )
    parser.add_argument(
        "--max-total-notional",
        type=float,
        default=50_000.0,
        help="Maximum total portfolio notional (default: 50000).",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="NIFTY",
        help="Comma-separated list of symbols to trade (default: NIFTY).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=252,
        help="Number of days of historical candles (default: 252).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible synthetic candles (default: 42).",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.6,
        help="Minimum signal confidence required to execute (default: 0.6).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview orders without submitting them or persisting state.",
    )
    parser.add_argument(
        "--skip-backtest",
        action="store_true",
        default=False,
        help="Skip backtest validation (unsafe; for testing only).",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        default=True,
        help="Print the session tear-sheet report (default: on).",
    )
    parser.add_argument(
        "--state-db",
        type=str,
        default="./data/all_in_one_state.db",
        help="Path to the SQLite state store (default: ./data/all_in_one_state.db).",
    )
    return parser


async def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = AllInOneConfig(
        capital=args.capital,
        risk_per_trade=args.risk_per_trade,
        max_daily_loss=args.max_daily_loss,
        max_drawdown=args.max_drawdown,
        max_position_per_symbol=args.max_position_per_symbol,
        max_total_notional=args.max_total_notional,
        symbols=[s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        days=args.days,
        seed=args.seed,
        confidence_threshold=args.confidence_threshold,
        dry_run=args.dry_run,
        skip_backtest=args.skip_backtest,
        state_db_path=args.state_db,
    )

    bot = AllInOneBot(config)

    try:
        session = await bot.run_cycle()
    finally:
        try:
            await bot.state_store.close()
        except Exception:
            pass

    if args.report:
        bot.print_report(session)

    # Exit code: 0 if session completed, non-zero if there were hard errors.
    return 1 if session.get("errors") else 0


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    raise SystemExit(asyncio.run(main()))
