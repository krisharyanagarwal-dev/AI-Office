"""
LearningBrain - Online adaptation and meta-learning
"""
import logging
from typing import Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ModelWeights:
    weights: Dict[str, float] = field(default_factory=dict)
    regime: str = "unknown"
    updated_at: float = 0.0


@dataclass
class KellyEstimate:
    win_rate: float = 0.5
    avg_win: float = 0.0
    avg_loss: float = 0.0
    kelly_fraction: float = 0.0
    updated_at: float = 0.0


@dataclass
class GraveyardEntry:
    pattern_name: str
    regime: str
    failure_count: int
    last_failure: float
    disabled: bool = False


class LearningBrain:
    def __init__(self, config: dict):
        self.config = config
        self.model_weights = ModelWeights()
        self.kelly_estimates: Dict[str, KellyEstimate] = {}
        self.graveyard: Dict[str, GraveyardEntry] = {}
        self.pnl_history: list = []

    async def initialize(self):
        logger.info("LearningBrain initialized")

    def record_outcome(self, decision_id: str, pnl: float, regime: str):
        self.pnl_history.append({
            'decision_id': decision_id,
            'pnl': pnl,
            'regime': regime,
            'timestamp': 0.0
        })

    def update_kelly(self,
                     model_name: str,
                     win_rate: float,
                     avg_win: float,
                     avg_loss: float):
        if model_name not in self.kelly_estimates:
            self.kelly_estimates[model_name] = KellyEstimate()
        k = self.kelly_estimates[model_name]
        k.win_rate = win_rate
        k.avg_win = avg_win
        k.avg_loss = avg_loss
        if avg_loss > 0:
            numerator = win_rate * avg_win - (1 - win_rate) * avg_loss
            k.kelly_fraction = numerator / avg_loss
        else:
            k.kelly_fraction = 0.0

    def record_pattern_failure(self, pattern_name: str, regime: str):
        key = f"{pattern_name}_{regime}"
        if key not in self.graveyard:
            self.graveyard[key] = GraveyardEntry(
                pattern_name=pattern_name,
                regime=regime,
                failure_count=0,
                last_failure=0
            )
        self.graveyard[key].failure_count += 1
        self.graveyard[key].last_failure = 0.0
        if self.graveyard[key].failure_count > 3:
            self.graveyard[key].disabled = True

    async def stop(self):
        pass
