"""
Shared task template library for THE CLAUDE COMPANY.

Task templates are stored per-workspace as JSON files at:
    ~/.openclaw/workspaces/{workspace_id}/templates/{template_id}.json
"""

import json
import uuid
import time
import os
from pathlib import Path
from typing import Optional, Dict, List, Any

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
TEMPLATE_ID_PREFIX = "tmpl"


def _templates_dir(workspace_id: str) -> Path:
    return WORKSPACE_DIR / workspace_id / "templates"


def _template_path(template_id: str, workspace_id: str) -> Path:
    return _templates_dir(workspace_id) / f"{template_id}.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_template_id() -> str:
    return f"{TEMPLATE_ID_PREFIX}-{uuid.uuid4().hex[:8]}"


def save_template(
    name: str,
    prompt: str,
    agent_id: str,
    priority: str,
    description: str,
    workspace_id: str,
) -> dict:
    """Save a task template for a workspace."""
    templates_dir = _templates_dir(workspace_id)
    templates_dir.mkdir(parents=True, exist_ok=True)

    template_id = _new_template_id()
    template = {
        "template_id": template_id,
        "name": name,
        "prompt": prompt,
        "agent_id": agent_id,
        "priority": priority,
        "description": description,
        "workspace_id": workspace_id,
        "created_at": _now(),
    }
    with open(_template_path(template_id, workspace_id), "w") as f:
        json.dump(template, f, indent=2)
    return template


def get_template(template_id: str) -> Optional[dict]:
    """Get a template by ID across all workspaces."""
    if not WORKSPACE_DIR.exists():
        return None
    for ws_dir in WORKSPACE_DIR.iterdir():
        if not ws_dir.is_dir():
            continue
        template_path = ws_dir / "templates" / f"{template_id}.json"
        if template_path.exists():
            try:
                return json.loads(template_path.read_text())
            except Exception:
                return None
    return None


def list_templates(workspace_id: str) -> List[dict]:
    """List all templates for a workspace, newest first."""
    templates_dir = _templates_dir(workspace_id)
    if not templates_dir.exists():
        return []
    templates = []
    for path in templates_dir.glob("*.json"):
        try:
            templates.append(json.loads(path.read_text()))
        except Exception:
            pass
    templates.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return templates


def delete_template(template_id: str) -> bool:
    """Delete a template by ID across all workspaces. Returns True if deleted."""
    if not WORKSPACE_DIR.exists():
        return False
    for ws_dir in WORKSPACE_DIR.iterdir():
        if not ws_dir.is_dir():
            continue
        template_path = ws_dir / "templates" / f"{template_id}.json"
        if template_path.exists():
            template_path.unlink()
            return True
    return False


def use_template(template_id: str) -> dict:
    """Get template data ready for dispatch.

    Returns: {"prompt": ..., "agent_id": ..., "priority": ..., "description": ...}
    """
    template = get_template(template_id)
    if template is None:
        raise ValueError(f"Template not found: {template_id}")
    return {
        "prompt": template["prompt"],
        "agent_id": template["agent_id"],
        "priority": template["priority"],
        "description": template["description"],
    }
