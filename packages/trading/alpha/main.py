"""
Alpha Trading System - Main Entry Point
Orchestrates the three-brain architecture: ChartBrain, DecisionBrain, LearningBrain
"""
import asyncio
import logging
import sys
import signal
import time
from pathlib import Path
from typing import Optional
import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha.config import load_config
from alpha.data.providers.ws_provider import MultiExchangeProvider, create_ws_provider
from alpha.execution.execution_engine import ExecutionEngine, PaperBroker, Order, OrderSide, OrderType
from alpha.risk.risk_manager import RiskManager, RiskLimits
from alpha.brain.chart_brain import ChartBrain
from alpha.brain.decision_brain import DecisionBrain
from alpha.brain.learning_brain import LearningBrain
from alpha.brain.trading_bot import TradingBot
from alpha.brain.state_store import StateStore
from alpha.validation.metrics import calculate_sharpe, calculate_sortino

logger = logging.getLogger(__name__)


class AlphaSystem:
    """Main system orchestrator"""
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config = load_config(config_path)
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        # Core components
        self.chart_brain: Optional[ChartBrain] = None
        self.decision_brain: Optional[DecisionBrain] = None
        self.learning_brain: Optional[LearningBrain] = None
        self.trading_bot: Optional[TradingBot] = None
        
        # Infrastructure
        self.ws_manager = None
        self.execution_engine = None
        self.risk_manager = None
        self.state_store = None
        
        # Tasks
        self._tasks = []
        
    async def initialize(self):
        """Initialize all system components"""
        logger.info("Initializing Alpha Trading System...")
        
        # Load configuration
        cfg = self.config
        
        # Initialize state store
        self.state_store = StateStore(self.config.get('state_store', {}))
        await self.state_store.initialize()
        
        # Initialize risk manager
        risk_cfg = self.config.get('risk', {})
        limits = RiskLimits(
            max_position_per_symbol=risk_cfg.get('max_position_per_symbol', 50000),
            max_total_notional=risk_cfg.get('max_total_notional', 500000),
            max_drawdown=risk_cfg.get('max_drawdown', 0.10),
            max_daily_loss=risk_cfg.get('max_daily_loss', 20000),
            max_var=risk_cfg.get('max_var', 50000),
            max_leverage=risk_cfg.get('max_leverage', 2.0)
        )
        self.risk_manager = RiskManager(limits)
        await self.risk_manager.start()
        
        # Initialize execution engine
        self.execution_engine = ExecutionEngine()
        paper_broker = PaperBroker(initial_balance=100000.0)
        self.execution_engine.add_broker("paper", paper_broker, is_default=True)
        
        # Add risk checks to execution engine
        from alpha.execution.execution_engine import (
            max_position_check, max_notional_check, daily_loss_limit_check
        )
        self.execution_engine.add_pre_trade_check(max_position_check(10000))
        self.execution_engine.add_pre_trade_check(max_notional_check(50000))
        self.execution_engine.add_pre_trade_check(
            daily_loss_limit_check(20000, lambda: self.risk_manager._daily_pnl)
        )
        
        # Initialize brains
        self.chart_brain = ChartBrain(self.config.get('chart_brain', {}))
        await self.chart_brain.initialize()
        
        self.decision_brain = DecisionBrain(self.config.get('decision_brain', {}))
        await self.decision_brain.initialize()
        
        self.learning_brain = LearningBrain(self.config.get('learning_brain', {}))
        await self.learning_brain.initialize()
        
        # Initialize trading bot
        self.trading_bot = TradingBot(
            chart_brain=self.chart_brain,
            decision_brain=self.decision_brain,
            learning_brain=self.learning_brain,
            execution_engine=self.execution_engine,
            risk_manager=self.risk_manager,
            state_store=self.state_store,
            config=self.config
        )
        await self.trading_bot.initialize()
        
        # Initialize WebSocket providers
        await self._initialize_ws_providers()
        
        logger.info("Alpha Trading System initialized successfully")
    
    async def _initialize_ws_providers(self):
        """Initialize WebSocket data providers"""
        from alpha.data.providers.ws_provider import MultiExchangeProvider, create_ws_provider
        
        self.ws_manager = MultiExchangeProvider()
        
        # Get symbols from config
        symbols = self.config.get('universe', {}).get('equities', []) + \
                  self.config.get('universe', {}).get('crypto', [])
        
        # For now, just use Binance
        binance = create_ws_provider(
            "binance", 
            symbols[:10],  # Limit for testing
            on_bar=self.trading_bot.on_bar,
            on_orderbook=self.trading_bot.on_orderbook,
            on_trade=self.trading_bot.on_trade
        )
        self.ws_manager.add_provider(binance)
        
        logger.info(f"WebSocket providers initialized for {len(symbols)} symbols")
    
    async def start(self):
        """Start the trading system"""
        if self.running:
            logger.warning("System already running")
            return
        
        self.running = True
        logger.info("Starting Alpha Trading System...")
        
        # Start WebSocket providers with indefinite auto-reconnect + health supervision (24/7)
        self._tasks.append(asyncio.create_task(self.ws_manager.start_all_supervised()))
        
        # Start trading bot
        await self.trading_bot.start()
        
        # Start monitoring loop
        self._tasks.append(asyncio.create_task(self._monitor_loop()))
        
        # Start supervisor loop: restarts crashed components, keeps system alive 24/7
        self._tasks.append(asyncio.create_task(self._supervisor_loop()))
        
        logger.info("Alpha Trading System started successfully")

    async def _supervisor_loop(self):
        """Supervisor loop (24/7): monitors component health and restarts anything that dies.

        Runs until self.running is False. Checks WebSocket provider connectivity
        and TradingBot liveness, restarting components that have stopped
        unexpectedly. Does NOT restart providers themselves — each provider's
        own supervise() task handles reconnection; this loop handles whole
        component crashes.
        """
        check_interval = self.config.get('supervisor', {}).get('check_interval', 30)
        while self.running:
            try:
                await asyncio.sleep(check_interval)
                if not self.running:
                    break

                # WebSocket providers: log health, let their own supervise() reconnect
                if self.ws_manager:
                    for p in self.ws_manager.providers:
                        status = p.get_status()
                        if not status.get("connected"):
                            logger.warning(
                                f"WS provider unhealthy: {status['provider']} "
                                f"(reconnects={status['reconnect_count']}, "
                                f"last_msg={status['last_message_age']:.0f}s ago)"
                            )

                # Trading bot: restart if it stopped unexpectedly
                if self.trading_bot and not self.trading_bot.running and self.running:
                    logger.warning("Trading bot not running, restarting...")
                    try:
                        await self.trading_bot.start()
                    except Exception as e:
                        logger.error(f"Failed to restart trading bot: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Supervisor loop error: {e}")
                await asyncio.sleep(5)
    
    async def stop(self):
        """Stop the trading system"""
        if not self.running:
            return
        
        logger.info("Stopping Alpha Trading System...")
        self.running = False
        self.shutdown_event.set()
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Stop components
        await self.trading_bot.stop()
        await self.ws_manager.stop_all()
        await self.risk_manager.stop()
        await self.state_store.close()
        
        logger.info("Alpha Trading System stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Health checks
                ws_health = self.ws_manager.get_health_status() if self.ws_manager else {}
                risk_summary = self.risk_manager.get_risk_summary() if self.risk_manager else {}
                
                logger.info(f"Health: WS={ws_health}, Risk={risk_summary}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(5)
    
    def get_status(self) -> dict:
        """Get system status"""
        return {
            "running": self.running,
            "ws_health": self.ws_manager.get_health_status() if self.ws_manager else {},
            "risk": self.risk_manager.get_risk_summary() if self.risk_manager else {},
            "positions": self.execution_engine.get_positions() if self.execution_engine else {},
        }


def load_config(path: str) -> dict:
    """Load configuration from YAML file"""
    path = Path(path)
    if not path.exists():
        logger.warning(f"Config file not found: {path}, using defaults")
        return {}
    
    with open(path, 'r') as f:
        return yaml.safe_load(f)


async def main():
    """Main entry point"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('logs/alpha.log')
        ]
    )
    
    # Create logs directory
    Path("logs").mkdir(exist_ok=True)
    
    # Create system
    system = AlphaSystem("config/settings.yaml")
    
    # Setup signal handlers
    shutdown_event = asyncio.Event()
    
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, initiating shutdown...")
        asyncio.create_task(system.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, signal_handler)
    
    try:
        # Initialize
        await system.initialize()
        
        # Start system
        await system.start()
        
        # Wait for shutdown
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
    finally:
        await system.stop()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
