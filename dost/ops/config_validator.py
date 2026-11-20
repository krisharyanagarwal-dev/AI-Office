"""Config validation for THE CLAUDE COMPANY.

Validates office.json configuration and required environment variables,
and can auto-fix common config issues.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "packages" / "office-os" / "config" / "office.json"

# Top-level fields that must be present in office.json
REQUIRED_TOP_LEVEL_FIELDS: List[str] = ["provider_pools", "agent_tiers", "office"]

# Server settings live under the "office" key
SERVER_SETTING_FIELDS: List[str] = [
    "heartbeat_interval_sec",
    "max_concurrent_workers",
    "task_poll_interval_sec",
    "task_timeout_sec",
]

# Every provider pool must declare these fields
POOL_REQUIRED_FIELDS: List[str] = ["models", "tier", "rate_limit_rpm", "cooldown_sec"]

# Defaults used when auto-fixing a pool
POOL_DEFAULTS: Dict[str, Any] = {
    "provider": "unknown",
    "models": [],
    "tier": "general",
    "rate_limit_rpm": 60,
    "cooldown_sec": 60,
}

# Env vars checked by validate_env. Missing keys are warnings, not errors,
# because free tiers are available for all of them.
ENV_KEYS: List[str] = [
    "STRIPE_API_KEY",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY",
    "NVIDIA_API_KEY",
]


def _default_config_path() -> Path:
    """Resolve the default office.json path, falling back to the project root."""
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    fallback = PROJECT_ROOT / "office.json"
    return fallback if fallback.exists() else DEFAULT_CONFIG_PATH


def _load_config(config_path: Optional[str]) -> Dict[str, Any]:
    """Load and return the office config dict, or {} if the file is missing."""
    path = Path(config_path) if config_path else _default_config_path()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _empty_result() -> Dict[str, Any]:
    return {"valid": True, "errors": [], "warnings": []}


def validate_office_config(config_path: Optional[str] = None) -> dict:
    """Validate office.json config.

    Returns {"valid": bool, "errors": [...], "warnings": [...]}

    Checks required top-level fields (provider_pools, agent_tiers, server
    settings), validates every provider pool has models/tier/rate_limit_rpm/
    cooldown_sec, and checks every agent tier has at least one agent.
    """
    result = _empty_result()
    path = Path(config_path) if config_path else _default_config_path()

    if not path.exists():
        result["errors"].append(f"Config file not found: {path}")
        result["valid"] = False
        return result

    try:
        with open(path, "r", encoding="utf-8") as fh:
            config = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        result["errors"].append(f"Failed to parse config {path}: {exc}")
        result["valid"] = False
        return result

    if not isinstance(config, dict):
        result["errors"].append("Config top level must be a JSON object")
        result["valid"] = False
        return result

    # Required top-level fields
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in config:
            result["errors"].append(f"Missing required top-level field: {field}")
            result["valid"] = False

    # Server settings (under the "office" key)
    office = config.get("office")
    if not isinstance(office, dict):
        result["errors"].append("Server settings 'office' must be an object")
        result["valid"] = False
    else:
        for field in SERVER_SETTING_FIELDS:
            if field not in office:
                result["warnings"].append(
                    f"Server setting 'office.{field}' is missing"
                )

    # Provider pools
    pools = config.get("provider_pools")
    if not isinstance(pools, dict):
        result["errors"].append("'provider_pools' must be an object")
        result["valid"] = False
        pools = {}
    else:
        for pool_name, pool in pools.items():
            if not isinstance(pool, dict):
                result["errors"].append(
                    f"Provider pool '{pool_name}' must be an object"
                )
                result["valid"] = False
                continue
            for field in POOL_REQUIRED_FIELDS:
                if field not in pool:
                    result["errors"].append(
                        f"Provider pool '{pool_name}' missing required field: {field}"
                    )
                    result["valid"] = False
            # Type sanity checks (warnings so a usable config stays valid)
            models = pool.get("models")
            if not isinstance(models, list):
                result["errors"].append(
                    f"Provider pool '{pool_name}' 'models' must be a list"
                )
                result["valid"] = False
            elif len(models) == 0:
                result["warnings"].append(
                    f"Provider pool '{pool_name}' has no models"
                )
            tier = pool.get("tier")
            if not isinstance(tier, str):
                result["warnings"].append(
                    f"Provider pool '{pool_name}' 'tier' should be a string"
                )
            rate_limit = pool.get("rate_limit_rpm")
            if not isinstance(rate_limit, (int, float)) or rate_limit <= 0:
                result["errors"].append(
                    f"Provider pool '{pool_name}' 'rate_limit_rpm' must be a positive number"
                )
                result["valid"] = False
            cooldown = pool.get("cooldown_sec")
            if not isinstance(cooldown, (int, float)) or cooldown < 0:
                result["errors"].append(
                    f"Provider pool '{pool_name}' 'cooldown_sec' must be a non-negative number"
                )
                result["valid"] = False

    # Agent tiers
    tiers = config.get("agent_tiers")
    if not isinstance(tiers, dict):
        result["errors"].append("'agent_tiers' must be an object")
        result["valid"] = False
        tiers = {}
    else:
        for tier_name, agents in tiers.items():
            if not isinstance(agents, list) or len(agents) == 0:
                result["errors"].append(
                    f"Agent tier '{tier_name}' must have at least one agent"
                )
                result["valid"] = False

    return result


def validate_env() -> dict:
    """Validate required environment variables.

    Returns {"valid": bool, "errors": [...], "warnings": [...]}

    Missing keys are warnings, not errors, because free tiers are available
    for all of them.
    """
    result = _empty_result()
    for key in ENV_KEYS:
        value = os.environ.get(key)
        if not value:
            result["warnings"].append(
                f"Environment variable '{key}' is not set (free tier available)"
            )
    result["valid"] = len(result["errors"]) == 0
    return result


def validate_all() -> dict:
    """Run all validations (office config + env).

    Returns {"valid": bool, "errors": [...], "warnings": [...]}
    """
    config_result = validate_office_config()
    env_result = validate_env()

    errors = list(config_result["errors"]) + list(env_result["errors"])
    warnings = list(config_result["warnings"]) + list(env_result["warnings"])

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def fix_config(config_path: Optional[str] = None) -> dict:
    """Auto-fix common config issues.

    Adds missing fields with defaults and removes invalid entries.
    Writes the fixed config back to disk.

    Returns {"fixed": [...], "remaining_errors": [...]}
    """
    path = Path(config_path) if config_path else _default_config_path()
    fixed: List[str] = []
    remaining_errors: List[str] = []

    if not path.exists():
        # Create a minimal valid config from scratch
        path.parent.mkdir(parents=True, exist_ok=True)
        config = {
            "office": {},
            "provider_pools": {},
            "agent_tiers": {},
        }
        fixed.append("Created missing config file with default structure")
        _write_config(path, config)
        return {"fixed": fixed, "remaining_errors": remaining_errors}

    try:
        with open(path, "r", encoding="utf-8") as fh:
            config = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        remaining_errors.append(f"Cannot parse config {path}: {exc}")
        return {"fixed": fixed, "remaining_errors": remaining_errors}

    if not isinstance(config, dict):
        remaining_errors.append("Config top level is not a JSON object; cannot fix")
        return {"fixed": fixed, "remaining_errors": remaining_errors}

    # Ensure top-level required fields exist
    office_defaults = {
        "name": "Office OS",
        "version": "1.0.0",
        "heartbeat_interval_sec": 120,
        "max_concurrent_workers": 4,
        "task_poll_interval_sec": 5,
        "task_timeout_sec": 300,
    }
    for field, default_value in office_defaults.items():
        office = config.setdefault("office", {})
        if field not in office:
            office[field] = default_value
            fixed.append(f"Added office.{field} = {default_value!r}")

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in config:
            if field == "provider_pools":
                config[field] = {}
            elif field == "agent_tiers":
                config[field] = {}
            else:  # "office"
                config[field] = {}
            fixed.append(f"Added missing top-level field: {field}")

    # Fix provider pools
    pools = config.get("provider_pools")
    if not isinstance(pools, dict):
        config["provider_pools"] = {}
        pools = {}
        fixed.append("Replaced invalid provider_pools with empty object")

    pools_to_remove: List[str] = []
    for pool_name, pool in list(pools.items()):
        if not isinstance(pool, dict):
            pools_to_remove.append(pool_name)
            fixed.append(f"Removed invalid provider pool '{pool_name}' (not an object)")
            continue
        for field, default_value in POOL_DEFAULTS.items():
            if field not in pool:
                pool[field] = default_value
                fixed.append(
                    f"Added provider pool '{pool_name}'.{field} = {default_value!r}"
                )
        # Coerce obvious type problems where safe
        models = pool.get("models")
        if not isinstance(models, list):
            pool["models"] = []
            fixed.append(
                f"Reset provider pool '{pool_name}'.models to empty list"
            )

    for pool_name in pools_to_remove:
        del pools[pool_name]

    # Fix agent tiers
    tiers = config.get("agent_tiers")
    if not isinstance(tiers, dict):
        config["agent_tiers"] = {}
        tiers = {}
        fixed.append("Replaced invalid agent_tiers with empty object")

    tiers_to_remove: List[str] = []
    for tier_name, agents in list(tiers.items()):
        if not isinstance(agents, list) or len(agents) == 0:
            tiers_to_remove.append(tier_name)
            fixed.append(
                f"Removed agent tier '{tier_name}' (no agents)"
            )

    for tier_name in tiers_to_remove:
        del tiers[tier_name]

    _write_config(path, config)

    return {"fixed": fixed, "remaining_errors": remaining_errors}


def _write_config(path: Path, config: Dict[str, Any]) -> None:
    """Persist config to disk, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")
