"""
Configuration validation with schema definitions.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, get_type_hints
import re


@dataclass
class ConfigSchema:
    """Defines a configuration schema with validation rules."""
    
    required: List[str] = field(default_factory=list)
    optional: Dict[str, Any] = field(default_factory=dict)
    types: Dict[str, type] = field(default_factory=dict)
    patterns: Dict[str, str] = field(default_factory=dict)
    validators: Dict[str, callable] = field(default_factory=dict)
    
    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate configuration against schema. Returns list of errors."""
        errors = []
        
        # Check required fields
        for field_name in self.required:
            if field_name not in config:
                errors.append(f"Required field missing: {field_name}")
        
        # Check types
        for field_name, expected_type in self.types.items():
            if field_name in config:
                value = config[field_name]
                if not isinstance(value, expected_type):
                    errors.append(
                        f"Field '{field_name}' has wrong type: "
                        f"expected {expected_type.__name__}, got {type(value).__name__}"
                    )
        
        # Check patterns
        for field_name, pattern in self.patterns.items():
            if field_name in config:
                value = config[field_name]
                if isinstance(value, str) and not re.match(pattern, value):
                    errors.append(f"Field '{field_name}' does not match pattern: {pattern}")
        
        # Run custom validators
        for field_name, validator in self.validators.items():
            if field_name in config:
                try:
                    if not validator(config[field_name]):
                        errors.append(f"Field '{field_name}' failed custom validation")
                except Exception as e:
                    errors.append(f"Field '{field_name}' validation error: {e}")
        
        return errors


def validate_config(config: Dict[str, Any], schema: ConfigSchema) -> bool:
    """Validate configuration and raise exception if invalid."""
    errors = schema.validate(config)
    if errors:
        raise ValueError(f"Configuration validation failed:\n" + "\n".join(errors))
    return True


# Common schema definitions
DATABASE_SCHEMA = ConfigSchema(
    required=["host", "port", "database"],
    optional={"username": "", "password": "", "pool_size": 5},
    types={
        "host": str,
        "port": int,
        "database": str,
        "username": str,
        "password": str,
        "pool_size": int,
    },
    patterns={
        "host": r"^[a-zA-Z0-9.-]+$",
    }
)


MODEL_ROUTER_SCHEMA = ConfigSchema(
    required=["endpoint"],
    optional={"timeout": 30, "retries": 3, "models": []},
    types={
        "endpoint": str,
        "timeout": int,
        "retries": int,
        "models": list,
    },
    patterns={
        "endpoint": r"^https?://",
    }
)


LAUNCHD_SCHEMA = ConfigSchema(
    required=["label", "program"],
    optional={
        "working_directory": None,
        "environment": {},
        "run_at_load": True,
        "keep_alive": True,
        "throttle_interval": 30,
        "process_type": "Background",
    },
    types={
        "label": str,
        "program": list,
        "working_directory": (str, type(None)),
        "environment": dict,
        "run_at_load": bool,
        "keep_alive": bool,
        "throttle_interval": int,
        "process_type": str,
    }
)