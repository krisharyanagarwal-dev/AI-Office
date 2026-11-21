"""
Risk Management System
Portfolio risk controls, position limits, drawdown monitoring
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
import logging
import numpy as np
import pandas as pd

from alpha.data.stock_metrics import symbol_fundamentals

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(Enum):
    POSITION_LIMIT = "position_limit"
    NOTIONAL_LIMIT = "notional_limit"
    DRAWDOWN = "drawdown"
    DAILY_LOSS = "daily_loss"
    VAR_BREACH = "var_breach"
    CONCENTRATION = "concentration"
    LEVERAGE = "leverage"
    MARGIN = "margin"


@dataclass
class RiskAlert:
    """Risk alert"""
    alert_type: AlertType
    level: RiskLevel
    message: str
    symbol: Optional[str] = None
    value: float = 0.0
    limit: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)


@dataclass
class RiskLimits:
    """Risk limits configuration"""
    # Position limits
    max_position_per_symbol: float = 100000.0  # max notional per symbol
    max_total_notional: float = 1000000.0      # max total notional
    max_positions: int = 50                     # max number of positions
    
    # Drawdown limits
    max_daily_loss: float = 50000.0            # max daily loss
    max_drawdown: float = 0.15                 # max drawdown (15%)
    max_drawdown_lookback: int = 252           # lookback days for drawdown
    
    # VaR limits
    var_confidence: float = 0.99               # VaR confidence level
    var_horizon: int = 1                       # VaR horizon (days)
    max_var: float = 100000.0                  # max VaR
    
    # Concentration limits
    max_sector_exposure: float = 0.30          # max sector exposure (30%)
    max_single_factor_exposure: float = 0.40   # max single factor exposure
    max_correlation_exposure: float = 0.70     # max correlated exposure
    
    # Leverage limits
    max_leverage: float = 3.0                  # max portfolio leverage
    max_position_leverage: float = 5.0         # max single position leverage
    
    # Margin limits
    min_margin_ratio: float = 0.15             # minimum margin ratio (15%)
    liquidation_margin_ratio: float = 0.05     # liquidation margin ratio (5%)
    
    # Daily loss limits
    max_daily_trades: int = 1000               # max trades per day
    max_order_size: float = 100000.0           # max single order size
    
    # Volatility limits
    max_portfolio_vol: float = 0.50            # max portfolio volatility (50%)
    max_symbol_vol: float = 2.0                # max symbol volatility (200%)


@dataclass
class PortfolioMetrics:
    """Current portfolio metrics"""
    total_value: float = 0.0
    total_notional: float = 0.0
    cash: float = 0.0
    leverage: float = 1.0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    var_99: float = 0.0
    portfolio_vol: float = 0.0
    sharpe: float = 0.0
    positions_count: int = 0
    daily_trades: int = 0
    daily_pnl_pct: float = 0.0
    max_position_size: float = 0.0
    largest_position_pct: float = 0.0
    sector_exposures: Dict[str, float] = field(default_factory=dict)
    factor_exposures: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class RiskManager:
    """
    Comprehensive risk management system
    """
    
    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.alerts: List = []
        self.alert_callbacks: List[Callable[[RiskAlert], None]] = []
        
        # State tracking
        self._portfolio_metrics = PortfolioMetrics()
        self._daily_pnl_history: List[float] = []
        self._equity_curve: List[float] = []
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._daily_volume: float = 0.0
        self._peak_equity: float = 0.0
        self._equity_high_water: float = 0.0
        
        # Position tracking
        self._positions: Dict[str, Dict] = {}
        self._sector_map: Dict[str, str] = {}
        self._factor_exposures: Dict[str, float] = {}
        
        # Risk models
        self._covariance_matrix: Optional[np.ndarray] = None
        self._factor_covariance: Optional[np.ndarray] = None
        self._factor_loadings: Optional[pd.DataFrame] = None
        
        # Callbacks
        self.on_alert: Optional[Callable[[RiskAlert], None]] = None
        self.on_risk_update: Optional[Callable[[PortfolioMetrics], None]] = None
        
        # Background tasks
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start risk monitoring"""
        self._running = True
        self._monitoring_task = asyncio.create_task(self._monitor_loop())
        logger.info("Risk manager started")
    
    async def stop(self):
        """Stop risk monitoring"""
        self._running = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("Risk manager stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        while True:
            try:
                await self._check_all_limits()
                await asyncio.sleep(1.0)  # Check every second
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Risk monitor error: {e}")
                await asyncio.sleep(5.0)
    
    async def _check_all_limits(self):
        """Check all risk limits"""
        metrics = await self.get_portfolio_metrics()
        
        # Check drawdown
        if metrics.current_drawdown > self.limits.max_drawdown:
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.DRAWDOWN,
                level=RiskLevel.CRITICAL if metrics.current_drawdown > self.limits.max_drawdown * 1.5 else RiskLevel.HIGH,
                message=f"Portfolio drawdown {metrics.current_drawdown:.2%} exceeds limit {self.limits.max_drawdown:.2%}",
                value=metrics.current_drawdown,
                limit=self.limits.max_drawdown
            ))
        
        # Check daily loss
        if metrics.daily_pnl < -self.limits.max_daily_loss:
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.DAILY_LOSS,
                level=RiskLevel.CRITICAL,
                message=f"Daily loss {metrics.daily_pnl:.2f} exceeds limit {self.limits.max_daily_loss}",
                value=abs(metrics.daily_pnl),
                limit=self.limits.max_daily_loss
            ))
        
        # Check VaR
        if metrics.var_99 > self.limits.max_var:
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.VAR_BREACH,
                level=RiskLevel.HIGH,
                message=f"VaR {metrics.var_99:.2f} exceeds limit {self.limits.max_var}",
                value=metrics.var_99,
                limit=self.limits.max_var
            ))
        
        # Check leverage
        if metrics.leverage > self.limits.max_leverage:
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.LEVERAGE,
                level=RiskLevel.HIGH,
                message=f"Leverage {metrics.leverage:.2f}x exceeds limit {self.limits.max_leverage}x",
                value=metrics.leverage,
                limit=self.limits.max_leverage
            ))
        
        # Check position limits
        for symbol, pos in self._positions.items():
            notional = abs(pos.get('notional', 0))
            if notional > self.limits.max_position_per_symbol:
                await self._trigger_alert(RiskAlert(
                    alert_type=AlertType.POSITION_LIMIT,
                    level=RiskLevel.HIGH,
                    message=f"Position {symbol} notional {notional:.2f} exceeds limit {self.limits.max_position_per_symbol}",
                    symbol=symbol,
                    value=notional,
                    limit=self.limits.max_position_per_symbol
                ))
        
        # Check total notional
        if metrics.total_notional > self.limits.max_total_notional:
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.NOTIONAL_LIMIT,
                level=RiskLevel.HIGH,
                message=f"Total notional {metrics.total_notional:.2f} exceeds limit {self.limits.max_total_notional}",
                value=metrics.total_notional,
                limit=self.limits.max_total_notional
            ))
        
        # Check position count
        if metrics.positions_count > self.limits.max_positions:
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.POSITION_LIMIT,
                level=RiskLevel.MEDIUM,
                message=f"Position count {metrics.positions_count} exceeds limit {self.limits.max_positions}",
                value=metrics.positions_count,
                limit=self.limits.max_positions
            ))
        
        # Check portfolio volatility
        if metrics.portfolio_vol > self.limits.max_portfolio_vol:
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.VAR_BREACH,
                level=RiskLevel.MEDIUM,
                message=f"Portfolio volatility {metrics.portfolio_vol:.2%} exceeds limit {self.limits.max_portfolio_vol:.2%}",
                value=metrics.portfolio_vol,
                limit=self.limits.max_portfolio_vol
            ))
        
        # Check daily trades
        if self._daily_trades >= self.limits.max_daily_trades:
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.DAILY_LOSS,
                level=RiskLevel.MEDIUM,
                message=f"Daily trades {self._daily_trades} exceeds limit {self.limits.max_daily_trades}",
                value=self._daily_trades,
                limit=self.limits.max_daily_trades
            ))
        
        # Check concentration
        max_pos_pct = metrics.largest_position_pct
        if max_pos_pct > 0.5:  # >50% in single position
            await self._trigger_alert(RiskAlert(
                alert_type=AlertType.CONCENTRATION,
                level=RiskLevel.HIGH,
                message=f"Largest position {max_pos_pct:.1%} exceeds 50% concentration limit",
                value=max_pos_pct,
                limit=0.5
            ))
        
        # Update metrics timestamp
        metrics.timestamp = time.time()
        self._portfolio_metrics = metrics
        
        if self.on_risk_update:
            try:
                self.on_risk_update(metrics)
            except Exception as e:
                logger.error(f"Risk update callback error: {e}")
    
    async def _trigger_alert(self, alert: RiskAlert):
        """Trigger risk alert"""
        self.alerts.append(alert)
        logger.warning(f"RISK ALERT [{alert.level.value}]: {alert.message}")
        
        if self.on_alert:
            try:
                self.on_alert(alert)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")
    
    # Public API
    
    async def get_portfolio_metrics(self) -> PortfolioMetrics:
        """Get current portfolio metrics"""
        # This would integrate with actual position data
        # For now, return cached metrics with updated calculations
        metrics = self._portfolio_metrics
        
        # Update drawdown
        if self._equity_curve:
            current = self._equity_curve[-1]
            peak = max(self._equity_curve)
            metrics.current_drawdown = (peak - current) / peak if peak > 0 else 0
            metrics.max_drawdown = max(metrics.max_drawdown, metrics.current_drawdown)
        
        return metrics
    
    def record_fill(self, fill_data: Dict):
        """Record a fill for risk tracking"""
        self._daily_trades += 1
        self._daily_volume += fill_data.get('notional', 0)
        
        # Update daily P&L
        pnl = fill_data.get('realized_pnl', 0)
        self._daily_pnl += pnl
        
        # Update equity curve
        if self._equity_curve:
            self._equity_curve.append(self._equity_curve[-1] + pnl)
        else:
            self._equity_curve.append(pnl)
    
    def update_position(self, symbol: str, position_data: Dict):
        """Update position data"""
        self._positions[symbol.upper()] = position_data
    
    def update_balances(self, balances: Dict[str, float]):
        """Update account balances"""
        # This would update internal balance tracking
        pass
    
    def update_market_data(self, prices: Dict[str, float]):
        """Update market prices for mark-to-market"""
        pass
    
    def update_factor_exposures(self, exposures: Dict[str, float]):
        """Update factor exposures"""
        self._factor_exposures = exposures
    
    def update_sector_map(self, sector_map: Dict[str, str]):
        """Update sector mapping for concentration checks"""
        self._sector_map = sector_map
    
    def update_covariance(self, cov_matrix: np.ndarray, symbols: List[str]):
        """Update covariance matrix for VaR calculation"""
        self._covariance_matrix = cov_matrix
    
    def set_covariance_model(self, factor_cov: np.ndarray, factor_loadings: pd.DataFrame):
        """Set factor covariance model"""
        self._factor_covariance = factor_cov
        self._factor_loadings = factor_loadings
    
    def get_alerts(self, since: Optional[float] = None, level: Optional[RiskLevel] = None) -> List[RiskAlert]:
        """Get alerts with optional filtering"""
        alerts = self.alerts
        if since:
            alerts = [a for a in alerts if a.timestamp >= since]
        if level:
            alerts = [a for a in alerts if a.level == level]
        return alerts
    
    def get_recent_alerts(self, hours: float = 24) -> List[RiskAlert]:
        """Get alerts from last N hours"""
        since = time.time() - hours * 3600
        return self.get_alerts(since=since)
    
    def acknowledge_alert(self, alert: RiskAlert):
        """Acknowledge an alert"""
        if alert in self.alerts:
            alert.metadata['acknowledged'] = True
            alert.metadata['acknowledged_at'] = time.time()
    
    def clear_old_alerts(self, max_age_hours: float = 168):  # 1 week
        """Clear old acknowledged alerts"""
        cutoff = time.time() - max_age_hours * 3600
        self.alerts = [
            a for a in self.alerts
            if not a.metadata.get('acknowledged') or a.timestamp > cutoff
        ]
    
    def get_risk_summary(self) -> Dict:
        """Get risk summary for dashboard"""
        metrics = self._portfolio_metrics
        recent_alerts = self.get_recent_alerts(24)
        
        return {
            'portfolio_value': metrics.total_value,
            'leverage': metrics.leverage,
            'daily_pnl': metrics.daily_pnl,
            'daily_pnl_pct': metrics.daily_pnl_pct,
            'current_drawdown': metrics.current_drawdown,
            'max_drawdown': metrics.max_drawdown,
            'var_99': metrics.var_99,
            'portfolio_vol': metrics.portfolio_vol,
            'positions': metrics.positions_count,
            'daily_trades': metrics.daily_trades,
            'alerts_24h': len(self.get_recent_alerts(24)),
            'critical_alerts': len([a for a in self.get_recent_alerts(24) if a.level == RiskLevel.CRITICAL]),
            'high_alerts': len([a for a in self.get_recent_alerts(24) if a.level == RiskLevel.HIGH]),
        }
    
    # Pre-trade risk checks
    
    def pre_trade_check(self, order: Any) -> tuple:
        """
        Pre-trade risk check
        Returns: (allowed: bool, reason: str, risk_metrics: Dict)
        """
        # Check order size
        notional = order.quantity * (order.price or 0)
        if notional > self.limits.max_order_size:
            return False, f"Order notional {notional} exceeds max {self.limits.max_order_size}", {}
        
        # Check position limit
        pos = self._positions.get(order.symbol.upper(), {})
        current_notional = abs(pos.get('notional', 0))
        new_notional = notional
        if new_notional > self.limits.max_position_per_symbol:
            return False, f"Position would exceed limit {self.limits.max_position_per_symbol}", {}
        
        # Check daily loss
        metrics = self._portfolio_metrics
        if metrics.daily_pnl < -self.limits.max_daily_loss * 0.8:  # 80% warning
            return False, "Approaching daily loss limit", {}
        
        # Check daily trade limit
        if self._daily_trades >= self.limits.max_daily_trades * 0.9:
            return False, f"Approaching daily trade limit ({self._daily_trades}/{self.limits.max_daily_trades})", {}
        
        # Check position count
        if self._portfolio_metrics.positions_count >= self.limits.max_positions:
            # Allow if increasing existing position
            pass
        
        return True, "OK", {}
    
    def calculate_var(self, returns: pd.Series, confidence: float = 0.99) -> float:
        """Calculate VaR using historical simulation"""
        if len(returns) < 30:
            return 0.0
        
        var = -np.percentile(returns.dropna(), (1 - confidence) * 100)
        return max(0, var)
    
    def calculate_var_covariance(self, positions: Dict, covariance: np.ndarray, prices: Dict) -> float:
        """Calculate VaR using covariance matrix"""
        if not positions:
            return 0.0
        
        symbols = list(positions.keys())
        weights = np.array([positions[s] * prices.get(s, 1) for s in symbols])
        total_value = weights.sum()
        if total_value == 0:
            return 0.0
        
        weights = weights / total_value
        
        # Portfolio variance
        port_var = weights @ covariance @ weights
        port_vol = np.sqrt(max(0, port_var))
        
        # 99% VaR
        from scipy import stats
        var_99 = -stats.norm.ppf(0.01) * port_vol * total_value
        return max(0, var_99)


class PortfolioRiskAnalyzer:
    """Advanced portfolio risk analytics"""
    
    def __init__(self, risk_manager: RiskManager):
        self.rm = risk_manager
    
    def calculate_factor_var(self, factor_exposures: pd.DataFrame, 
                            factor_cov: np.ndarray, 
                            specific_risk: pd.Series) -> float:
        """Calculate factor model VaR"""
        # Factor VaR = sqrt(w' * B * F * B' * w) + specific risk
        pass
    
    def calculate_component_var(self, portfolio: pd.Series, 
                               covariance: np.ndarray) -> pd.Series:
        """Calculate component VaR for each position"""
        pass
    
    def calculate_marginal_var(self, portfolio: pd.Series,
                              covariance: np.ndarray) -> pd.Series:
        """Calculate marginal VaR for each position"""
        pass
    
    def calculate_risk_contribution(self, portfolio: pd.Series,
                                   covariance: np.ndarray) -> pd.Series:
        """Calculate risk contribution (RC) for each position"""
        w = portfolio.values
        sigma = covariance
        port_var = w @ sigma @ w
        mvar = sigma @ w  # Marginal VaR
        rc = w * mvar / np.sqrt(port_var) if port_var > 0 else np.zeros_like(w)
        return pd.Series(rc, index=portfolio.index)
    
    def calculate_diversification_ratio(self, portfolio: pd.Series, 
                                       covariance: np.ndarray) -> float:
        """Calculate diversification ratio"""
        w = portfolio.values
        sigma = covariance
        weighted_vol = np.sum(w * np.sqrt(np.diag(sigma)))
        port_vol = np.sqrt(w @ sigma @ w)
        return weighted_vol / port_vol if port_vol > 0 else 1.0
    
    def stress_test(self, portfolio: pd.Series, 
                   shocks: Dict[str, float]) -> float:
        """Apply stress scenarios to portfolio"""
        # shocks: {factor: shock_size}
        pass


# Integration with execution engine
class RiskAwareExecutionEngine:
    """Execution engine with integrated risk management"""
    
    def __init__(self, execution_engine, risk_manager: RiskManager):
        self.engine = execution_engine
        self.rm = risk_manager
        
        # Add pre-trade checks
        self.engine.add_pre_trade_check(self._risk_check)
    
    def _risk_check(self, order) -> bool:
        """Pre-trade risk check"""
        allowed, reason, _ = self.rm.pre_trade_check(order)
        if not allowed:
            logger.warning(f"Risk check failed for {order.symbol}: {reason}")
        return True  # Always allow, but log warnings
    
    def _attach_fundamentals(self, order) -> None:
        """Attach published fundamentals to order as context (read-only)."""
        if hasattr(order, 'symbol') and order.symbol:
            fundamentals = symbol_fundamentals(None, order.symbol)
            if fundamentals:
                order.fundamentals = fundamentals
    
    def _fundamentals_position_modifier(self, symbol: str) -> float:
        """Return position size multiplier based on fundamentals (0.5-1.5)."""
        facts = symbol_fundamentals(None, symbol)
        if not facts:
            return 1.0
        
        mod = 1.0
        if facts.get("valuation_flag") == "Expensive":
            mod *= 0.7
        if facts.get("leverage_flag") == "High":
            mod *= 0.8
        if facts.get("liquidity_flag") == "Tight":
            mod *= 0.7
        if facts.get("profitability_flag") == "Weak":
            mod *= 0.8
        
        return max(0.5, min(1.5, mod))  # clamp
    
    async def submit_order_with_risk(self, order) -> Any:
        """Submit order with risk checks"""
        # Attach fundamentals as context (read-only, never gates order)
        self._attach_fundamentals(order)
        
        # Apply fundamentals-based position sizing
        if hasattr(order, 'symbol') and order.symbol and hasattr(order, 'quantity'):
            modifier = self._fundamentals_position_modifier(order.symbol)
            if modifier != 1.0:
                order.quantity *= modifier
                logger.info(f"Position size adjusted for {order.symbol}: modifier={modifier:.2f}")
        
        # Run pre-trade checks
        allowed, reason, _ = self.rm.pre_trade_check(order)
        if not allowed:
            logger.warning(f"Order rejected by risk: {reason}")
            order.status = "REJECTED"
            return order
        
        return await self.engine.submit_order(order)


# Example usage
async def main():
    # Create risk manager
    limits = RiskLimits(
        max_position_per_symbol=50000,
        max_total_notional=500000,
        max_drawdown=0.10,
        max_daily_loss=20000,
        max_var=50000,
        max_leverage=2.0
    )
    
    rm = RiskManager(limits)
    await rm.start()
    
    # Simulate some fills
    for i in range(10):
        rm.record_fill({
            'symbol': 'BTCUSDT',
            'notional': 10000,
            'realized_pnl': np.random.normal(10, 100)
        })
    
    # Get metrics
    metrics = await rm.get_portfolio_metrics()
    print(f"Portfolio value: {metrics.total_value}")
    print(f"Daily P&L: {metrics.daily_pnl}")
    print(f"Drawdown: {metrics.current_drawdown:.2%}")
    
    # Check alerts
    alerts = rm.get_recent_alerts(24)
    print(f"Alerts (24h): {len(alerts)}")
    
    # Risk check
    from types import SimpleNamespace
    order = type('Order', (), {
        'symbol': 'BTCUSDT',
        'quantity': 2.0,
        'price': 50000,
        'side': 'buy'
    })()
    
    allowed, reason, _ = rm.pre_trade_check(type('Order', (), {
        'symbol': 'BTCUSDT',
        'quantity': 2.0,
        'price': 50000,
        'side': 'buy'
    })())
    
    print(f"Allowed: {allowed}, Reason: {reason}")
    
    await rm.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
