"""
TradingBot - Orchestration, execution, and system management
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from alpha.data.stock_metrics import load_stock_metrics, symbol_fundamentals

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(
        self,
        chart_brain,
        decision_brain,
        learning_brain,
        execution_engine,
        risk_manager,
        state_store,
        config: dict
    ):
        self.chart_brain = chart_brain
        self.decision_brain = decision_brain
        self.learning_brain = learning_brain
        self.execution_engine = execution_engine
        self.risk_manager = risk_manager
        self.state_store = state_store
        self.config = config
        self.running = False
        
        # Execution loop (24/7)
        self._exec_task: Optional[asyncio.Task] = None
        self._last_heartbeat: Optional[float] = None
        self._loop_error_count = 0
        exec_cfg = config.get('execution', {}) if isinstance(config, dict) else {}
        self._loop_interval = exec_cfg.get('loop_interval', 1.0)  # seconds between ticks
        self._stale_threshold = exec_cfg.get('stale_threshold', 30.0)  # seconds before considered dead

        # Latest market prices (symbol -> price) for mark-to-market
        self._market_prices: Dict[str, float] = {}

        # Latest fundamental context per symbol (from all_stocks_bot metrics).
        # Factual flags only (valuation, leverage, liquidity, profitability,
        # ROE, momentum) — context/metadata, never a directional signal.
        self._fundamentals: Dict[str, dict] = {}
        self._fundamentals_ts: float = 0.0
        
    async def initialize(self):
        logger.info("TradingBot initialized")
    
    async def on_bar(self, bar):
        """Handle incoming bar data"""
        # Track latest close price for mark-to-market
        try:
            self._market_prices[bar.symbol] = float(bar.close)
        except Exception:
            pass

        # Build decision context: price + fundamental context (metadata only,
        # never a directional signal). ChartBrain context is a stub today, so
        # we assemble what we have and let the decision brain consume it.
        context = self.chart_brain.get_chart_context(bar.symbol) or {}
        if not isinstance(context, dict):
            context = {}
        context["symbol"] = bar.symbol
        context["price"] = self._market_prices.get(bar.symbol)
        fundamentals = self.get_symbol_fundamentals(bar.symbol)
        if fundamentals:
            context["fundamentals"] = fundamentals
        await self.chart_brain.on_bar(bar)

        # Generate signals
        if context:
            signals = await self.decision_brain.generate_signals(context)
            # Process signals through risk manager
            # ... (would integrate with decision brain)
    
    async def on_orderbook(self, orderbook):
        await self.chart_brain.on_orderbook(orderbook)
    
    async def on_trade(self, trade):
        await self.chart_brain.on_trade(trade)
        # Track latest trade price for mark-to-market
        try:
            self._market_prices[trade.symbol] = float(trade.price)
        except Exception:
            pass
    
    async def start(self):
        """Start the TradingBot and its 24/7 execution loop."""
        if self.running:
            logger.warning("TradingBot already running")
            return
        
        # Restore persistent state (positions/orders/balances) before starting
        # so the bot resumes where it left off after a restart.
        await self._restore_execution_state()
        
        self.running = True
        self._last_heartbeat = time.time()
        self._loop_error_count = 0
        
        # Start the execution loop as a background task so it runs 24/7
        self._exec_task = asyncio.create_task(self._execution_loop())
        
        logger.info("TradingBot started (execution loop running)")
    
    async def stop(self):
        """Stop the TradingBot and its execution loop."""
        self.running = False
        
        if self._exec_task and not self._exec_task.done():
            self._exec_task.cancel()
            try:
                await self._exec_task
            except asyncio.CancelledError:
                pass
        self._exec_task = None
        
        logger.info("TradingBot stopped")
    
    def is_healthy(self) -> bool:
        """Return True if the execution loop is running and has a recent heartbeat."""
        if not self.running or self._exec_task is None or self._exec_task.done():
            return False
        if self._last_heartbeat is None:
            return False
        return (time.time() - self._last_heartbeat) < self._stale_threshold
    
    def get_status(self) -> dict:
        """Get execution loop status for monitoring/supervision."""
        return {
            "running": self.running,
            "healthy": self.is_healthy(),
            "loop_task_done": self._exec_task.done() if self._exec_task else None,
            "last_heartbeat_age": (time.time() - self._last_heartbeat) if self._last_heartbeat else None,
            "loop_error_count": self._loop_error_count,
            "loop_interval": self._loop_interval,
            "fundamentals": {
                "symbols": len(self._fundamentals),
                "loaded_at": self._fundamentals_ts,
            },
        }
    
    async def _execution_loop(self):
        """24/7 execution loop: processes orders, enforces risk, updates state.

        Runs until self.running is False. Any exception is logged and the loop
        continues (resilient). The supervisor in AlphaSystem restarts the whole
        TradingBot if this task dies.
        """
        while self.running:
            try:
                loop_start = time.time()
                
                # Process any pending orders through the execution engine
                await self._process_pending_orders()
                
                # Enforce risk checks on current positions
                await self._enforce_risk()
                
                # Mark-to-market open positions with latest prices
                await self._mark_to_market()
                
                # Refresh fundamental context from all_stocks_bot metrics
                self._refresh_fundamentals()
                
                # Persist execution state (positions/orders/balances) each tick
                await self._persist_state()
                
                self._last_heartbeat = time.time()
                
                # Sleep for the remainder of the interval
                elapsed = time.time() - loop_start
                sleep_for = max(0.0, self._loop_interval - elapsed)
                await asyncio.sleep(sleep_for)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._loop_error_count += 1
                logger.error(f"Execution loop error: {e}")
                # Stay alive: sleep briefly then continue (resilient 24/7)
                await asyncio.sleep(self._loop_interval)
    
    async def _process_pending_orders(self):
        """Process pending orders (paper broker fills, etc.)."""
        if not self.execution_engine:
            return
        processor = getattr(self.execution_engine, "process_pending_orders", None)
        if processor:
            try:
                if asyncio.iscoroutinefunction(processor):
                    await processor()
                else:
                    processor()
            except Exception as e:
                logger.debug(f"process_pending_orders: {e}")
    
    async def _enforce_risk(self):
        """Enforce risk limits on current positions."""
        if not self.risk_manager or not self.execution_engine:
            return
        try:
            positions = await self.execution_engine.get_positions()
            checker = getattr(self.risk_manager, "check_positions", None)
            if checker:
                try:
                    if asyncio.iscoroutinefunction(checker):
                        await checker(positions)
                    else:
                        checker(positions)
                except Exception as e:
                    logger.debug(f"risk check_positions: {e}")
        except Exception as e:
            logger.debug(f"risk get_positions: {e}")
    
    async def _restore_execution_state(self):
        """Restore positions/orders/balances from StateStore so they survive restarts."""
        if not self.execution_engine:
            return
        loader = getattr(self.execution_engine, "load_state", None)
        if loader:
            try:
                restored = await loader() if asyncio.iscoroutinefunction(loader) else loader()
                if restored:
                    logger.info("Execution state restored from StateStore")
            except Exception as e:
                logger.debug(f"restore execution state: {e}")

    async def _mark_to_market(self):
        """Update unrealized P&L for open positions using latest prices."""
        if not self.execution_engine:
            return
        updater = getattr(self.execution_engine, "update_mark_prices", None)
        if updater:
            try:
                await updater(dict(self._market_prices))
            except Exception as e:
                logger.debug(f"mark to market: {e}")

    def _refresh_fundamentals(self):
        """Load the latest all_stocks_bot metrics and index per-symbol fundamentals.

        Fails silently — a missing or unreadable metrics file leaves the
        previous (possibly empty) fundamentals in place and never blocks the
        execution loop. The flags are factual context only, not signals.

        Uses mtime caching to avoid re-parsing on every tick.
        """
        metrics_path = Path("/Users/aryanagarwal/.openclaw/stocks_metrics.json")
        try:
            current_mtime = metrics_path.stat().st_mtime if metrics_path.exists() else 0
        except OSError:
            current_mtime = 0

        # Skip if file hasn't changed
        if getattr(self, '_fundamentals_mtime', None) == current_mtime:
            return

        try:
            metrics = load_stock_metrics()
            if not metrics:
                return
            alias_map = metrics.get("fundamentals_by_symbol") or {}
            if isinstance(alias_map, dict) and alias_map:
                self._fundamentals = dict(alias_map)
            else:
                top = metrics.get("top_by_market_cap") or []
                if isinstance(top, list):
                    self._fundamentals = {
                        entry.get("symbol"): entry for entry in top if entry.get("symbol")
                    }
            self._fundamentals_ts = time.time()
            self._fundamentals_mtime = current_mtime
        except Exception:  # never crash the execution loop on metrics
            pass

    def get_symbol_fundamentals(self, symbol: str) -> Optional[dict]:
        """Return the latest fundamental facts for a symbol, or None."""
        if not symbol:
            return None
        entry = self._fundamentals.get(symbol)
        if entry is None:
            entry = self._fundamentals.get(symbol.strip().upper())
        if entry is None:
            entry = symbol_fundamentals(self._fundamentals, symbol)
        return entry

    async def _persist_execution_state(self):
        """Persist positions/orders/balances to StateStore each tick."""
        if not self.execution_engine:
            return
        saver = getattr(self.execution_engine, "save_state", None)
        if saver:
            try:
                await saver()
            except Exception as e:
                logger.debug(f"persist execution state: {e}")

    async def _persist_state(self):
        """Persist bot state + execution state to the state store each tick."""
        if not self.state_store:
            return
        # Trading bot meta
        saver = getattr(self.state_store, "save", None)
        if saver:
            try:
                payload = {
                    "trading_bot": {
                        "running": self.running,
                        "heartbeat": self._last_heartbeat,
                        "errors": self._loop_error_count,
                        "timestamp": time.time(),
                    }
                }
                if asyncio.iscoroutinefunction(saver):
                    await saver(payload)
                else:
                    saver(payload)
            except Exception as e:
                logger.debug(f"state save: {e}")
        # Execution engine: positions/orders/balances/drawdown
        await self._persist_execution_state()
