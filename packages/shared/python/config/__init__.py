"""
Shared configuration utilities for AI-Office packages.
"""
from .loader import ConfigLoader, load_config, get_config
from .validation import validate_config, ConfigSchema

__all__ = [
    "ConfigLoader",
    "load_config", 
    "get_config",
    "validate_config",
    "ConfigSchema",
]