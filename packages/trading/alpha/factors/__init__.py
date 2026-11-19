"""
Factor Library
100+ alpha factors organized by category
"""
from .base import FactorBase, FactorPipeline
from .alternative import (
    FundingRateFactor,
    OpenInterestFactor,
    FearGreedFactor,
    WhaleAlertFactor,
    ExchangeFlowFactor,
)
from .volatility_breakout import (
    VolatilityBreakoutFactor,
    ChannelExpansionFactor,
)
from .session_momentum import (
    SessionMomentumFactor,
    SessionOverlapFactor,
)
from .momentum import (
    MomentumFactor,
    RSIFactor,
    MACDFactor,
    RateOfChangeFactor,
    StochasticFactor,
)
from .reversal import (
    ShortTermReversalFactor,
    MediumTermReversalFactor,
    LongTermReversalFactor,
    OverboughtOversoldFactor,
)
from .technical import (
    BollingerFactor,
    KeltnerFactor,
    ATRFactor,
    ADXFactor,
    CCIFactor,
    WilliamsRFactor,
    IchimokuFactor,
)
from .volatility import (
    RealizedVolFactor,
    ParkinsonVolFactor,
    GarmanKlassVolFactor,
    YangZhangVolFactor,
    GARCHVolFactor,
    VolatilityRiskPremium,
)
from .volume import (
    VolumeFactor,
    VWAPFactor,
    VolumeTrendFactor,
    DollarVolumeFactor,
    OBVFactor,
    MFI,
    VPIN,
)
from .cross_sectional_microstructure import (
    CrossSectionalRankFactor,
    CrossSectionalZScoreFactor,
    SectorNeutralizeFactor,
    MarketNeutralizeFactor,
    VPINFactor,
    OrderFlowToxicityFactor,
    LiquidityFactor,
)
# New factors (2026-11-16)
from .cross_asset_momentum import (
    CrossAssetConfig,
    CrossAssetMomentumFactor,
    MultiHorizonCrossAssetMomentum,
    create_cross_asset_momentum,
)
from .ml_alpha import (
    MLModelConfig,
    MLAlphaFactor,
    LightGBMModel,
    XGBoostModel,
    EnsembleModel,
    BaseMLModel,
    create_ml_alpha_factor,
)
from .pairs_arbitrage import (
    PairsConfig,
    PairsArbitrageFactor,
    KalmanFilterHedge,
    PairSignal,
    create_pairs_arbitrage,
)
from .option_greeks import (
    OptionConfig,
    OptionFactor,
    BSMEngine,
    SVIModel,
    create_option_factor,
)

__all__ = [
    'FactorBase',
    'FactorPipeline',
    # Momentum
    'MomentumFactor',
    'RSIFactor',
    'MACDFactor',
    'RateOfChangeFactor',
    'StochasticFactor',
    # Breakout
    'VolatilityBreakoutFactor',
    'ChannelExpansionFactor',
    # Session momentum
    'SessionMomentumFactor',
    'SessionOverlapFactor',
    # Reversal
    'ShortTermReversalFactor',
    'MediumTermReversalFactor',
    'LongTermReversalFactor',
    'OverboughtOversoldFactor',
    # Volatility
    'RealizedVolFactor',
    'ParkinsonVolFactor',
    'GarmanKlassVolFactor',
    'YangZhangVolFactor',
    'GARCHVolFactor',
    'VolatilityRiskPremium',
    # Volume
    'VolumeFactor',
    'VWAPFactor',
    'VolumeTrendFactor',
    'DollarVolumeFactor',
    'OBVFactor',
    'MFI',
    'VPIN',
    # Technical
    'BollingerFactor',
    'KeltnerFactor',
    'ATRFactor',
    'ADXFactor',
    'CCIFactor',
    'WilliamsRFactor',
    'IchimokuFactor',
    # Alternative
    'FundingRateFactor',
    'OpenInterestFactor',
    'FearGreedFactor',
    'WhaleAlertFactor',
    'ExchangeFlowFactor',
    # Cross-sectional and Microstructure
    'CrossSectionalRankFactor',
    'CrossSectionalZScoreFactor',
    'SectorNeutralizeFactor',
    'MarketNeutralizeFactor',
    'VPINFactor',
    'OrderFlowToxicityFactor',
    'LiquidityFactor',
    # New factors (2026-11-16)
    # Cross-Asset Momentum
    'CrossAssetConfig',
    'CrossAssetMomentumFactor',
    'MultiHorizonCrossAssetMomentum',
    'create_cross_asset_momentum',
    # ML Alpha
    'MLModelConfig',
    'MLAlphaFactor',
    'LightGBMModel',
    'XGBoostModel',
    'EnsembleModel',
    'BaseMLModel',
    'create_ml_alpha_factor',
    # Pairs Arbitrage
    'PairsConfig',
    'PairsArbitrageFactor',
    'KalmanFilterHedge',
    'PairSignal',
    'create_pairs_arbitrage',
    # Option Greeks
    'OptionConfig',
    'OptionFactor',
    'BSMEngine',
    'SVIModel',
    'create_option_factor',
]
