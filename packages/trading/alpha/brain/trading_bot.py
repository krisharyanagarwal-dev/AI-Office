"""
TradingBot - Orchestration, execution, and system management
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional

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
        
    async def initialize(self):
        logger.info("TradingBot initialized")
    
    async def on_bar(self, bar):
        """Handle incoming bar data"""
        await self.chart_brain.on_bar(bar)
        
        # Generate signals
        context = self.chart_brain.get_chart_context(bar.symbol)
        if context:
            signals = await self.decision_brain.generate_signals(context)
            # Process signals through risk manager
            # ... (would integrate with decision brain)
    
    async def on_orderbook(self, orderbook):
        await self.chart_brain.on_orderbook(orderbook)
    
    async def on_trade(self, trade):
        await self.chart_brain.on_trade(trade)
    
    async def start(self):
        """Start the TradingBot and its 24/7 execution loop."""
        if self.running:
            logger.warning("TradingBot already running")
            return
        
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
                
                # Persist state
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
    
    async def _persist_state(self):
        """Persist bot state to the state store."""
        if not self.state_store:
            return
        saver = getattr(self.state_store, "save", None)
        if saver:
            try:
                if asyncio.iscoroutinefunction(saver):
                    await saver({
                        "trading_bot": {
                            "running": self.running,
                            "heartbeat": self._last_heartbeat,
                            "errors": self._loop_error_count,
                            "timestamp": time.time(),
                        }
                    })
                else:
                    saver({
                        "trading_bot": {
                            "running": self.running,
                            "heartbeat": self._last_heartbeat,
                            "errors": self._loop_error_count,
                            "timestamp": time.time(),
                        }
                    })
            except Exception as e:
                logger.debug(f"state save: {e}")
