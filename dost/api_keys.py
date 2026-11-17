"""API key management for THE CLAUDE COMPANY."""

import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path.home() / ".openclaw" / "workspaces"


def _workspace_dir(workspace_id: str) -> Path:
    return BASE_DIR / workspace_id / "api_keys"


def _key_path(workspace_id: str, key_id: str) -> Path:
    return _workspace_dir(workspace_id) / f"{key_id}.json"


def _find_key_file(key_id: str):
    """Locate the (workspace_id, file path) for a given key_id, or None."""
    if not BASE_DIR.exists():
        return None
    for workspace_dir in BASE_DIR.iterdir():
        api_keys_dir = workspace_dir / "api_keys"
        if not api_keys_dir.is_dir():
            continue
        key_file = api_keys_dir / f"{key_id}.json"
        if key_file.is_file():
            return workspace_dir.name, key_file
    return None


def create_api_key(workspace_id: str, name: str, rate_limit_rpm: int = 60) -> dict:
    """Create a new API key for a workspace and persist it to disk."""
    key_id = str(uuid.uuid4())
    key = f"claw_{secrets.token_urlsafe(32)}"
    created_at = datetime.now(timezone.utc).isoformat()

    data = {
        "key_id": key_id,
        "key": key,
        "name": name,
        "rate_limit_rpm": rate_limit_rpm,
        "created_at": created_at,
        "usage_count": 0,
    }

    key_dir = _workspace_dir(workspace_id)
    key_dir.mkdir(parents=True, exist_ok=True)
    _key_path(workspace_id, key_id).write_text(json.dumps(data, indent=2))

    return {
        "key_id": key_id,
        "key": key,
        "name": name,
        "rate_limit_rpm": rate_limit_rpm,
        "created_at": created_at,
    }


def get_api_key(key_id: str):
    """Get an API key record by ID. Returns the stored dict or None."""
    found = _find_key_file(key_id)
    if found is None:
        return None
    _, key_file = found
    return json.loads(key_file.read_text())


def validate_api_key(api_key: str):
    """Validate an API key string and return workspace info, or None."""
    if not BASE_DIR.exists():
        return None
    for workspace_dir in BASE_DIR.iterdir():
        api_keys_dir = workspace_dir / "api_keys"
        if not api_keys_dir.is_dir():
            continue
        for key_file in api_keys_dir.glob("*.json"):
            try:
                data = json.loads(key_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("key") == api_key:
                return {
                    "workspace_id": workspace_dir.name,
                    "key_id": data.get("key_id"),
                    "name": data.get("name"),
                }
    return None


def list_api_keys(workspace_id: str) -> list:
    """List all API keys for a workspace (secret key value omitted)."""
    key_dir = _workspace_dir(workspace_id)
    if not key_dir.is_dir():
        return []
    keys = []
    for key_file in sorted(key_dir.glob("*.json")):
        try:
            data = json.loads(key_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        keys.append({
            "key_id": data.get("key_id"),
            "name": data.get("name"),
            "rate_limit_rpm": data.get("rate_limit_rpm"),
            "created_at": data.get("created_at"),
            "usage_count": data.get("usage_count", 0),
        })
    return keys


def delete_api_key(key_id: str) -> bool:
    """Delete an API key by ID. Returns True if a file was removed."""
    found = _find_key_file(key_id)
    if found is None:
        return False
    _, key_file = found
    key_file.unlink()
    return True


def increment_key_usage(key_id: str):
    """Increment the usage counter for rate limiting. Returns new count or None."""
    found = _find_key_file(key_id)
    if found is None:
        return None
    _, key_file = found
    data = json.loads(key_file.read_text())
    data["usage_count"] = data.get("usage_count", 0) + 1
    key_file.write_text(json.dumps(data, indent=2))
    return data["usage_count"]
