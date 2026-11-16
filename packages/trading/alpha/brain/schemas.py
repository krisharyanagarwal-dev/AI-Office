"""
Data schemas for the trading brain
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import numpy as np
from enum import Enum


class RegimeState(Enum):
    UNKNOWN = "unknown"
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    CHOP = "chop"
    VOL_EXPANSION = "vol_expansion"


class VolRegime(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


class PatternType(Enum):
    HAMMER = "hammer"
    ENGULFING_BULL = "engulfing_bull"
    ENGULFING_BEAR = "engulfing_bear"
    SHOOTING_STAR = "shooting_star"
    DOJI = "doji"
    HANGING_MAN = "hanging_man"
    INVERTED_HAMMER = "inverted_hammer"
    MORNING_STAR = "morning_star"
    EVENING_STAR = "evening_star"
    THREE_WHITE_SOLDIERS = "three_white_soldiers"
    THREE_BLACK_CROWS = "three_black_crows"


@dataclass(frozen=True)
class Bar:
    """Immutable bar data"""
    timestamp: int  # Unix timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3
    
    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class PatternSignal:
    """Detected pattern signal"""
    pattern_type: PatternType
    direction: int  # 1 for bullish, -1 for bearish, 0 for neutral
    strength: float  # 0-1 confidence
    bars_left: int  # How many bars until pattern expires
    price_level: float  # Price level of pattern (e.g., neckline, support)


@dataclass
class SRLevel:
    """Support/Resistance level"""
    price: float
    strength: float  # 0-1 based on touches and volume
    touches: int
    age_bars: int  # How many bars since first touch
    is_support: bool  # True if support, False if resistance


@dataclass(frozen=True)
class ChartContext:
    """Immutable market context for decision making"""
    symbol: str
    price: float  # Current price
    timestamp: int
    regime: RegimeState
    regime_confidence: float  # 0-1
    active_patterns: List[PatternSignal]
    sr_levels: List[SRLevel]
    vol_regime: VolRegime
    atr: float
    trend_strength: float  # ADX value
    momentum: float  # ROC(20)
    rsi: float
    
    def __post_init__(self):
        # Validate invariants
        assert 0 <= self.regime_confidence <= 1
        assert 0 <= self.atr
        assert 0 <= self.trend_strength <= 100


@dataclass
class Order:
    """Order to be executed"""
    symbol: str
    side: int  # 1 for buy, -1 for sell
    quantity: float
    order_type: str  # "market", "limit", "stop"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    tag: str = ""  # For identification (e.g., "entry", "stop_loss")
    client_order_id: Optional[str] = None


@dataclass
class Fill:
    """Order fill"""
    order_id: str
    symbol: str
    side: int
    quantity: float
    price: float
    timestamp: int
    commission: float = 0.0


@dataclass
class Position:
    """Current position"""
    symbol: str
    quantity: float  # Positive for long, negative for short
    avg_price: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: int


@dataclass
class Positions:
    """Collection of positions"""
    positions: Dict[str, Position] = field(default_factory=dict)
    
    def get(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)
    
    def total_value(self) -> float:
        return sum(abs(pos.quantity * pos.avg_price) for pos in self.positions.values())
    
    def net_exposure(self) -> float:
        return sum(pos.quantity * pos.avg_price for pos in self.positions.values())


@dataclass
class Decision:
    """Trading decision"""
    orders: List[Order]
    rationale: str
    risk_metrics: Dict[str, float]
    meta: Dict[str, any] = field(default_factory=dict)
    
    @property
    def is_flat(self) -> bool:
        return len(self.orders) == 0
    
    @property
    def net_signal(self) -> int:
        """-1 for net short, 0 for flat, 1 for net long"""
        if not self.orders:
            return 0
        buy_vol = sum(o.quantity for o in self.orders if o.side > 0)
        sell_vol = sum(o.quantity for o in self.orders if o.side < 0)
        if buy_vol > sell_vol:
            return 1
        elif sell_vol > buy_vol:
            return -1
        return 0


@dataclass
class PnL:
    """Profit and loss"""
    realized: float
    unrealized: float
    timestamp: int
    
    @property
    def total(self) -> float:
        return self.realized + self.unrealized


@dataclass
class ModelWeights:
    """Model weights per regime"""
    weights: Dict[RegimeState, Dict[str, float]] = field(default_factory=dict)
    
    def get(self, regime: RegimeState, model: str) -> float:
        return self.weights.get(regime, {}).get(model, 0.0)
    
    def set(self, regime: RegimeState, model: str, weight: float):
        if regime not in self.weights:
            self.weights[regime] = {}
        self.weights[regime][model] = weight
    
    def normalize(self):
        """Normalize weights for each regime to sum to 1"""
        for regime in self.weights:
            total = sum(self.weights[regime].values())
            if total > 0:
                for model in self.weights[regime]:
                    self.weights[regime][model] /= total


@dataclass
class KellyEstimate:
    """Kelly criterion estimate per regime"""
    win_rate: float = 0.5
    avg_win: float = 0.0
    avg_loss: float = 0.0
    kelly_fraction: float = 0.0
    trades_count: int = 0
    
    def update(self, win: bool, profit: float):
        """Update with new trade outcome"""
        self.trades_count += 1
        if win:
            # Update win rate and avg win
            self.win_rate = ((self.win_rate * (self.trades_count - 1)) + 1.0) / self.trades_count
            self.avg_win = ((self.avg_win * (self.trades_count - 2)) + profit) / (self.trades_count - 1) if self.trades_count > 1 else profit
        else:
            # Update win rate and avg loss (positive value)
            self.win_rate = ((self.win_rate * (self.trades_count - 1)) + 0.0) / self.trades_count
            self.avg_loss = ((self.avg_loss * (self.trades_count - 2)) + abs(profit)) / (self.trades_count - 1) if self.trades_count > 1 else abs(profit)
        
        # Recalculate Kelly
        if self.avg_loss > 0 and self.win_rate > 0 and self.win_rate < 1:
            win_prob = self.win_rate
            loss_prob = 1 - self.win_rate
            win_loss_ratio = self.avg_win / self.avg_loss if self.avg_win > 0 else 0
            self.kelly_fraction = win_prob - (loss_prob / win_loss_ratio) if win_loss_ratio > 0 else 0
            self.kelly_fraction = max(0, self.kelly_fraction)  # Kelly can't be negative
        else:
            self.kelly_fraction = 0


@dataclass
class GraveyardEntry:
    """Failed pattern/trade setup"""
    pattern_type: PatternType
    regime: RegimeState
    outcome_r: float  # Outcome in R-multiples
    timestamp: int
    context_hash: str  # Hash of market context at entry
    failure_count: int = 1
    disabled: bool = False
    
    def increment_failure(self):
        self.failure_count += 1
        if self.failure_count >= 3:
            self.disabled = True


# Constants used throughout the brain modules
SURVIVAL_RULES = {
    "max_daily_dd": 0.05,      # 5% daily drawdown limit
    "max_weekly_dd": 0.15,     # 15% weekly drawdown limit
    "max_position_pct": 0.10,  # 10% max position size
    "max_leverage": 2.0,       # 2x max leverage
    "min_edge_bp": 0.5,        # Minimum edge 0.5 basis points
    "kelly_cap": 0.25,         # Never risk more than 25% Kelly
    "vol_extreme_threshold": 0.95,  # Volatility percentile for EXTREME regime
    "news_blackout_minutes": 30,  # No trading 30min around news
}

REGIME_SCALARS = {
    RegimeState.TREND_UP: 1.0,
    RegimeState.TREND_DOWN: 1.0,
    RegimeState.CHOP: 0.3,
    RegimeState.VOL_EXPANSION: 0.5,
}

LEARNING_RATES = {
    RegimeState.TREND_UP: 0.1,
    RegimeState.TREND_DOWN: 0.1,
    RegimeState.CHOP: 0.05,
    RegimeState.VOL_EXPANSION: 0.07,
}

MODEL_NAMES = [
    "ridge", "lasso", "elastic_net",
    "lightgbm", "xgboost", "catboost",
    "mlp", "lstm", "transformer",
    "voting", "stacking", "blending", "dynamic"
]