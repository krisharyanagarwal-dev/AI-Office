"""
Configuration Management
Centralized settings with environment override support
"""
import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class UniverseConfig:
    equities: list = field(default_factory=list)
    crypto: list = field(default_factory=list)
    futures: list = field(default_factory=list)
    
    @property
    def all(self) -> list:
        return self.equities + self.crypto + self.futures


@dataclass
class DataConfig:
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"
    frequency: str = "1d"
    adjust: bool = True
    cache_dir: str = "./data/cache"
    providers: Dict = field(default_factory=dict)
    alternative: Dict = field(default_factory=dict)


@dataclass
class FactorConfig:
    momentum: Dict = field(default_factory=dict)
    reversal: Dict = field(default_factory=dict)
    volatility: Dict = field(default_factory=dict)
    volume: Dict = field(default_factory=dict)
    technical: Dict = field(default_factory=dict)
    cross_sectional: Dict = field(default_factory=dict)
    alternative: Dict = field(default_factory=dict)


@dataclass
class RegimeConfig:
    method: str = "hmm"
    n_regimes: int = 4
    features: list = field(default_factory=list)
    lookback: int = 252
    min_duration: int = 10
    transition_penalty: float = 0.1


@dataclass
class ModelConfig:
    linear: Dict = field(default_factory=dict)
    tree: Dict = field(default_factory=dict)
    neural: Dict = field(default_factory=dict)
    ensemble: Dict = field(default_factory=dict)


@dataclass
class ValidationConfig:
    method: str = "walkforward"
    n_splits: int = 12
    train_window: int = 252
    test_window: int = 21
    gap: int = 5
    purged: bool = True
    embargo_pct: float = 0.01
    metrics: list = field(default_factory=list)


@dataclass
class RiskConfig:
    covariance: Dict = field(default_factory=dict)
    budgeting: Dict = field(default_factory=dict)
    tail: Dict = field(default_factory=dict)


@dataclass
class PortfolioConfig:
    objective: str = "mean_variance"
    solver: str = "ECOS"
    constraints: list = field(default_factory=list)
    transaction_costs: Dict = field(default_factory=dict)


@dataclass
class BacktestConfig:
    engine: str = "vectorized"
    initial_capital: float = 1_000_000
    benchmark: str = "SPY"
    execution: Dict = field(default_factory=dict)
    costs: Dict = field(default_factory=dict)
    reporting: Dict = field(default_factory=dict)


@dataclass
class ExecutionConfig:
    mode: str = "paper"
    broker: str = "interactive_brokers"
    account: str = ""
    sizing: Dict = field(default_factory=dict)
    orders: Dict = field(default_factory=dict)
    risk_checks: Dict = field(default_factory=dict)


@dataclass
class MonitoringConfig:
    logging: Dict = field(default_factory=dict)
    metrics: Dict = field(default_factory=dict)
    alerts: Dict = field(default_factory=dict)
    dashboard: Dict = field(default_factory=dict)


@dataclass
class Settings:
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    data: DataConfig = field(default_factory=DataConfig)
    factors: FactorConfig = field(default_factory=FactorConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    feature_store: Dict = field(default_factory=dict)
    model_registry: Dict = field(default_factory=dict)


def _load_yaml(path: Path) -> Dict:
    """Load YAML file with environment variable substitution"""
    with open(path, 'r') as f:
        content = f.read()
    
    # Substitute environment variables: ${VAR:-default}
    import re
    def replace_env(match):
        var = match.group(1)
        if ':-' in var:
            var, default = var.split(':-', 1)
            return os.getenv(var, default)
        return os.getenv(var, match.group(0))
    
    content = re.sub(r'\$\{([^}]+)\}', replace_env, content)
    return yaml.safe_load(content)


def _merge_dict(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _dict_to_dataclass(data: Dict, cls) -> Any:
    """Convert dict to dataclass recursively"""
    if not isinstance(data, dict):
        return data
    
    field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}
    kwargs = {}
    for key, value in data.items():
        if key in field_types:
            field_type = field_types[key]
            if hasattr(field_type, '__origin__') and field_type.__origin__ is list:
                kwargs[key] = [_dict_to_dataclass(v, field_type.__args__[0]) if isinstance(v, dict) else v for v in value]
            elif hasattr(field_type, '__dataclass_fields__'):
                kwargs[key] = _dict_to_dataclass(value, field_type)
            else:
                kwargs[key] = value
    return cls(**kwargs)


class ConfigManager:
    """Singleton configuration manager"""
    _instance: Optional['ConfigManager'] = None
    _settings: Optional[Settings] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._settings is None:
            self._settings = self._load_settings()
    
    def _load_settings(self) -> Settings:
        # Find config file
        config_paths = [
            Path("config/settings.yaml"),
            Path("../config/settings.yaml"),
            Path(__file__).parent.parent / "config" / "settings.yaml",
            Path(os.getenv("ALPHA_CONFIG", "config/settings.yaml")),
        ]
        
        config_data = {}
        for path in config_paths:
            if path.exists():
                config_data = _load_yaml(path)
                break
        
        if not config_data:
            raise FileNotFoundError("No config file found")
        
        # Apply environment overrides
        env_overrides = self._get_env_overrides()
        config_data = _merge_dict(config_data, env_overrides)
        
        # Convert to dataclasses
        return _dict_to_dataclass(config_data, Settings)
    
    def _get_env_overrides(self) -> Dict:
        """Get configuration overrides from environment variables"""
        overrides = {}
        prefix = "ALPHA_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                # Convert ALPHA_FACTORS_MOMENTUM_LOOKBACKS to nested dict
                path = key[len(prefix):].lower().split('_')
                d = overrides
                for p in path[:-1]:
                    d = d.setdefault(p, {})
                d[path[-1]] = self._parse_value(value)
        return overrides
    
    def _parse_value(self, value: str) -> Any:
        """Parse string value to appropriate type"""
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            return value
    
    @property
    def settings(self) -> Settings:
        return self._settings
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get nested config value by dot notation"""
        keys = key.split('.')
        value = self._settings
        for k in keys:
            if hasattr(value, k):
                value = getattr(value, k)
            elif isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def reload(self):
        """Reload configuration from file"""
        self._settings = self._load_settings()


# Global instance
config = ConfigManager()


@lru_cache(maxsize=1)
def get_config() -> Settings:
    """Get global configuration (cached)"""
    return config.settings


def reload_config() -> Settings:
    """Force reload configuration"""
    config.reload()
    get_config.cache_clear()
    return config.settings

def load_config(path: str) -> dict:
    """Load configuration from YAML file as dictionary"""
    path = Path(path)
    if not path.exists():
        return {}
    
    with open(path, 'r') as f:
        content = f.read()
    
    # Substitute environment variables
    import re
    def replace_env(match):
        var = match.group(1)
        if ':-' in var:
            var, default = var.split(':-', 1)
            return os.getenv(var, default)
        return os.getenv(var, match.group(0))
    
    content = re.sub(r'\$\{([^}]+)\}', replace_env, content)
    return yaml.safe_load(content)
