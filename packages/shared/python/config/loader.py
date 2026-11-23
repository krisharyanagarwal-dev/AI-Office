"""
Configuration loader with support for multiple formats and environments.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union
import yaml


class ConfigLoader:
    """Loads configuration from files with environment variable overrides."""
    
    def __init__(self, config_dir: Optional[Union[str, Path]] = None):
        self.config_dir = Path(config_dir) if config_dir else Path.cwd() / "config"
        self._cache: Dict[str, Any] = {}
    
    def load(self, name: str, env_prefix: str = "OFFICE") -> Dict[str, Any]:
        """Load configuration from file with environment variable overrides."""
        cache_key = f"{name}:{env_prefix}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        config = {}
        
        # Try multiple file formats
        for ext in [".yaml", ".yml", ".json"]:
            config_path = self.config_dir / f"{name}{ext}"
            if config_path.exists():
                config = self._load_file(config_path)
                break
        
        # Apply environment variable overrides
        config = self._apply_env_overrides(config, env_prefix)
        
        self._cache[cache_key] = config
        return config
    
    def _load_file(self, path: Path) -> Dict[str, Any]:
        """Load configuration from a file."""
        with open(path) as f:
            if path.suffix in [".yaml", ".yml"]:
                return yaml.safe_load(f) or {}
            elif path.suffix == ".json":
                return json.load(f)
        return {}
    
    def _apply_env_overrides(self, config: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        """Apply environment variable overrides with prefix."""
        for key, value in os.environ.items():
            if key.startswith(f"{prefix}_"):
                # Convert OFFICE_DB_HOST -> db.host
                config_key = key[len(prefix) + 1:].lower().replace("_", ".")
                self._set_nested(config, config_key, self._parse_value(value))
        return config
    
    def _set_nested(self, d: Dict[str, Any], key: str, value: Any):
        """Set a nested dictionary value using dot notation."""
        parts = key.split(".")
        current = d
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    
    def _parse_value(self, value: str) -> Any:
        """Parse environment variable value to appropriate type."""
        # Try JSON first
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
        
        # Boolean
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        
        # Number
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
        
        return value
    
    def clear_cache(self):
        """Clear the configuration cache."""
        self._cache.clear()


# Global config loader instance
_default_loader = ConfigLoader()


def load_config(name: str, config_dir: Optional[Union[str, Path]] = None, 
                env_prefix: str = "OFFICE") -> Dict[str, Any]:
    """Load configuration using the default loader."""
    if config_dir:
        loader = ConfigLoader(config_dir)
        return loader.load(name, env_prefix)
    return _default_loader.load(name, env_prefix)


def get_config(name: str, key: str, default: Any = None, 
               config_dir: Optional[Union[str, Path]] = None,
               env_prefix: str = "OFFICE") -> Any:
    """Get a specific configuration value using dot notation."""
    config = load_config(name, config_dir, env_prefix)
    parts = key.split(".")
    current = config
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current