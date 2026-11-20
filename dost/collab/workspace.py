"""
Workspace multi-tenancy for THE CLAUDE COMPANY.

Each workspace is an isolated customer instance with:
- Own findings store, P&L ledger, task hive
- Own users with roles (admin/editor/viewer)
- Own cost tracking and billing
- Own provider pools and API keys
"""

import json
import uuid
import time
import os
from pathlib import Path
from typing import Optional, Dict, List, Any

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

WORKSPACE_META_FILE = "workspace.json"
WORKSPACE_USERS_FILE = "users.json"
WORKSPACE_SETTINGS_FILE = "settings.json"


def workspace_path(workspace_id: str) -> Path:
    return WORKSPACE_DIR / workspace_id


def workspace_exists(workspace_id: str) -> bool:
    return workspace_path(workspace_id).exists()


def create_workspace(
    name: str,
    owner_email: str,
    plan: str = "starter",
    metadata: Optional[dict] = None,
) -> dict:
    """Create a new workspace (tenant)."""
    workspace_id = f"ws-{uuid.uuid4().hex[:8]}"
    ws_path = workspace_path(workspace_id)
    ws_path.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (ws_path / "tasks").mkdir(exist_ok=True)
    (ws_path / "findings").mkdir(exist_ok=True)
    (ws_path / "pnl").mkdir(exist_ok=True)
    (ws_path / "briefings").mkdir(exist_ok=True)
    (ws_path / "exports").mkdir(exist_ok=True)

    # Write workspace metadata
    meta = {
        "id": workspace_id,
        "name": name,
        "plan": plan,
        "owner_email": owner_email,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": metadata or {},
        "active": True,
    }
    with open(ws_path / WORKSPACE_META_FILE, "w") as f:
        json.dump(meta, f, indent=2)

    # Create owner user as admin
    add_user(workspace_id, owner_email, role="admin")

    # Default settings
    save_workspace_settings(workspace_id, {
        "cost_alert_threshold": 100,
        "alert_webhook_url": None,
        "auto_archive_days": 30,
        "max_concurrent_tasks": 5,
    })

    return meta


def get_workspace(workspace_id: str) -> Optional[dict]:
    """Get workspace metadata."""
    meta_path = workspace_path(workspace_id) / WORKSPACE_META_FILE
    if not meta_path.exists():
        return None
    with open(meta_path) as f:
        return json.load(f)


def update_workspace(workspace_id: str, updates: dict) -> bool:
    """Update workspace metadata."""
    meta_path = workspace_path(workspace_id) / WORKSPACE_META_FILE
    if not meta_path.exists():
        return False
    meta = json.loads(meta_path.read_text())
    meta.update(updates)
    meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    return True


def delete_workspace(workspace_id: str) -> bool:
    """Delete a workspace and all its data."""
    ws_path = workspace_path(workspace_id)
    if not ws_path.exists():
        return False
    import shutil
    shutil.rmtree(ws_path)
    return True


def list_workspaces() -> List[dict]:
    """List all workspaces."""
    workspaces = []
    if not WORKSPACE_DIR.exists():
        return workspaces
    for ws_dir in WORKSPACE_DIR.iterdir():
        if ws_dir.is_dir():
            meta_path = ws_dir / WORKSPACE_META_FILE
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    workspaces.append(meta)
                except Exception:
                    pass
    return workspaces


# ============ USER MANAGEMENT ============

def add_user(workspace_id: str, email: str, role: str = "viewer") -> dict:
    """Add a user to a workspace."""
    users_path = workspace_path(workspace_id) / WORKSPACE_USERS_FILE
    users = {}
    if users_path.exists():
        users = json.loads(users_path.read_text())

    users[email] = {
        "email": email,
        "role": role,  # admin, editor, viewer
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active": True,
    }

    with open(users_path, "w") as f:
        json.dump(users, f, indent=2)

    return users[email]


def remove_user(workspace_id: str, email: str) -> bool:
    """Remove a user from a workspace."""
    users_path = workspace_path(workspace_id) / WORKSPACE_USERS_FILE
    if not users_path.exists():
        return False
    users = json.loads(users_path.read_text())
    if email in users:
        del users[email]
        with open(users_path, "w") as f:
            json.dump(users, f, indent=2)
        return True
    return False


def list_users(workspace_id: str) -> List[dict]:
    """List all users in a workspace."""
    users_path = workspace_path(workspace_id) / WORKSPACE_USERS_FILE
    if not users_path.exists():
        return []
    users = json.loads(users_path.read_text())
    return list(users.values())


def get_user_role(workspace_id: str, email: str) -> Optional[str]:
    """Get a user's role in a workspace."""
    users_path = workspace_path(workspace_id) / WORKSPACE_USERS_FILE
    if not users_path.exists():
        return None
    users = json.loads(users_path.read_text())
    if email in users:
        return users[email].get("role")
    return None


def can_access_workspace(workspace_id: str, email: str) -> bool:
    """Check if a user has access to a workspace."""
    return get_user_role(workspace_id, email) is not None


def can_edit_workspace(workspace_id: str, email: str) -> bool:
    """Check if a user can edit in a workspace (admin or editor)."""
    role = get_user_role(workspace_id, email)
    return role in ("admin", "editor")


def can_admin_workspace(workspace_id: str, email: str) -> bool:
    """Check if a user is admin of a workspace."""
    role = get_user_role(workspace_id, email)
    return role == "admin"


# ============ WORKSPACE SETTINGS ============

def get_workspace_settings(workspace_id: str) -> dict:
    """Get workspace settings."""
    settings_path = workspace_path(workspace_id) / WORKSPACE_SETTINGS_FILE
    if not settings_path.exists():
        return {}
    return json.loads(settings_path.read_text())


def save_workspace_settings(workspace_id: str, settings: dict) -> bool:
    """Save workspace settings."""
    settings_path = workspace_path(workspace_id) / WORKSPACE_SETTINGS_FILE
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
    return True


# ============ WORKSPACE-SCOPED PATHS ============

def workspace_tasks_dir(workspace_id: str) -> Path:
    return workspace_path(workspace_id) / "tasks"


def workspace_findings_dir(workspace_id: str) -> Path:
    return workspace_path(workspace_id) / "findings"


def workspace_pnl_dir(workspace_id: str) -> Path:
    return workspace_path(workspace_id) / "pnl"


def workspace_briefings_dir(workspace_id: str) -> Path:
    return workspace_path(workspace_id) / "briefings"


def workspace_exports_dir(workspace_id: str) -> Path:
    return workspace_path(workspace_id) / "exports"


# ============ DEFAULT WORKSPACE (backward compatibility) ============

DEFAULT_WORKSPACE_ID = "default"


def ensure_default_workspace() -> str:
    """Ensure a default workspace exists for backward compatibility.

    Creates the workspace with the stable id ``DEFAULT_WORKSPACE_ID`` ("default")
    so it is addressable by that id. (create_workspace() generates a random id,
    so we build the default workspace directly here.)
    """
    if not workspace_exists(DEFAULT_WORKSPACE_ID):
        ws_path = workspace_path(DEFAULT_WORKSPACE_ID)
        ws_path.mkdir(parents=True, exist_ok=True)
        (ws_path / "tasks").mkdir(exist_ok=True)
        (ws_path / "findings").mkdir(exist_ok=True)
        (ws_path / "pnl").mkdir(exist_ok=True)
        (ws_path / "briefings").mkdir(exist_ok=True)
        (ws_path / "exports").mkdir(exist_ok=True)

        meta = {
            "id": DEFAULT_WORKSPACE_ID,
            "name": "Default Workspace",
            "plan": "pro",
            "owner_email": "admin@default.local",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metadata": {},
            "active": True,
        }
        with open(ws_path / WORKSPACE_META_FILE, "w") as f:
            json.dump(meta, f, indent=2)

        add_user(DEFAULT_WORKSPACE_ID, "admin@default.local", role="admin")

        save_workspace_settings(DEFAULT_WORKSPACE_ID, {
            "cost_alert_threshold": 100,
            "alert_webhook_url": None,
            "auto_archive_days": 30,
            "max_concurrent_tasks": 5,
        })
    return DEFAULT_WORKSPACE_ID


def get_default_workspace() -> str:
    return DEFAULT_WORKSPACE_ID