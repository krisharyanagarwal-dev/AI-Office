"""
Task assignment for THE CLAUDE COMPANY.

Each task assignment is stored per workspace as a JSON file:

    ~/.openclaw/workspaces/{workspace_id}/task_assignments/{task_id}.json
"""

import json
import uuid
import os
import time
from pathlib import Path
from typing import Optional, Dict, List, Any

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

TASK_ASSIGNMENTS_DIR_NAME = "task_assignments"


def workspace_path(workspace_id: str) -> Path:
    return WORKSPACE_DIR / workspace_id


def task_assignments_dir(workspace_id: str) -> Path:
    return workspace_path(workspace_id) / TASK_ASSIGNMENTS_DIR_NAME


def assignment_path(workspace_id: str, task_id: str) -> Path:
    return task_assignments_dir(workspace_id) / f"{task_id}.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ")


def assign_task(
    task_id: str,
    workspace_id: str,
    user_email: str,
    assigned_by: str,
) -> dict:
    """Assign a task to a user in a workspace.

    Returns the assignment record:
        {"assignment_id", "task_id", "user_email", "assigned_by", "assigned_at"}
    """
    ta_dir = task_assignments_dir(workspace_id)
    ta_dir.mkdir(parents=True, exist_ok=True)

    assignment_id = f"ta-{uuid.uuid4().hex[:8]}"
    record: Dict[str, Any] = {
        "assignment_id": assignment_id,
        "task_id": task_id,
        "user_email": user_email,
        "assigned_by": assigned_by,
        "assigned_at": _now(),
    }

    with open(assignment_path(workspace_id, task_id), "w") as f:
        json.dump(record, f, indent=2)

    return record


def get_task_assignment(task_id: str, workspace_id: str) -> Optional[dict]:
    """Get the assignment record for a task, or None if unassigned."""
    path = assignment_path(workspace_id, task_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def list_user_tasks(workspace_id: str, user_email: str) -> list[dict]:
    """List all tasks assigned to a user in a workspace."""
    ta_dir = task_assignments_dir(workspace_id)
    if not ta_dir.exists():
        return []

    tasks: list[dict] = []
    for path in ta_dir.iterdir():
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            record = json.loads(path.read_text())
        except Exception:
            continue
        if record.get("user_email") == user_email:
            tasks.append(record)
    return tasks


def unassign_task(task_id: str, workspace_id: str) -> bool:
    """Remove the assignment for a task. Returns True if removed."""
    path = assignment_path(workspace_id, task_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def get_agent_workload(workspace_id: str) -> dict:
    """Get the count of assigned tasks per user in a workspace."""
    ta_dir = task_assignments_dir(workspace_id)
    if not ta_dir.exists():
        return {}

    workload: Dict[str, int] = {}
    for path in ta_dir.iterdir():
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            record = json.loads(path.read_text())
        except Exception:
            continue
        email = record.get("user_email")
        if email is None:
            continue
        workload[email] = workload.get(email, 0) + 1
    return workload
