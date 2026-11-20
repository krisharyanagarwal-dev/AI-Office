"""
Data deletion for THE CLAUDE COMPANY.

Implements GDPR-style data deletion (right to be forgotten) for workspaces
and users. Destructive operations require explicit confirmation, and every
deletion is recorded under ~/.openclaw/deletions/ so its status can be
queried later with get_deletion_status().

Data locations:
  - Workspaces:      ~/.openclaw/workspaces/{workspace_id}/
                     subdirs: tasks, findings, pnl, briefings, exports,
                     audit, templates, api_keys; files users.json,
                     workspace.json
  - Office P&L:      ~/.openclaw/office_pnl.json
  - Calibration ledger: ~/Documents/indian-paper-trading/results/
                     calibration_ledger.json
  - Deletion records:  ~/.openclaw/deletions/{delete_id}.json
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
OPENCLAW_DIR = Path(os.path.expanduser("~/.openclaw"))
OFFICE_PNL_FILE = OPENCLAW_DIR / "office_pnl.json"
RESEARCH_DIR = Path("/Users/aryanagarwal/Documents/indian-paper-trading")
CALIBRATION_FILE = RESEARCH_DIR / "results" / "calibration_ledger.json"
DELETIONS_DIR = OPENCLAW_DIR / "deletions"

# Deletable workspace subdirectories and top-level metadata files
WORKSPACE_SUBDIRS = ("tasks", "findings", "pnl", "briefings", "exports",
                     "audit", "templates", "api_keys")
WORKSPACE_FILES = ("users.json", "workspace.json")

# Categories reported in deleted_items
DELETION_CATEGORIES = (
    "tasks", "findings", "audit_logs", "calibration_ledger",
    "office_pnl", "briefings", "exports", "tasks_archive",
)

STATUS_NOT_DELETED = "not_deleted"
STATUS_DELETED = "deleted"
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_delete_id() -> str:
    return f"del-{uuid.uuid4().hex[:12]}"


def _empty_deleted_items() -> Dict[str, int]:
    return {category: 0 for category in DELETION_CATEGORIES}


def _record_deletion(delete_id: str, record: Dict) -> None:
    """Persist a deletion record so its status can be queried later."""
    DELETIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DELETIONS_DIR / f"{delete_id}.json", "w") as f:
        json.dump(record, f, indent=2)


def _load_deletion(delete_id: str) -> Optional[Dict]:
    path = DELETIONS_DIR / f"{delete_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _remove_path(path: Path) -> int:
    """Remove a file or directory tree. Returns the number of files removed."""
    removed = 0
    if path.is_dir():
        removed = sum(1 for p in path.rglob("*") if p.is_file())
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        removed = 1
        path.unlink(missing_ok=True)
    return removed


def _json_entry_count(path: Path) -> int:
    """Count entries in a JSON file (list length or dict size)."""
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data)
    return 0


def _user_owns(record: Dict, user_email: str) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        record.get("user_email") == user_email
        or record.get("email") == user_email
        or record.get("owner_email") == user_email
    )


def _strip_user_from_json_file(path: Path, user_email: str) -> int:
    """Remove user-owned records from a JSON file (list or dict). Returns count."""
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0

    removed = 0
    if isinstance(data, list):
        kept = [r for r in data if not _user_owns(r, user_email)]
        removed = len(data) - len(kept)
        if removed:
            path.write_text(json.dumps(kept, indent=2))
    elif isinstance(data, dict):
        kept = {k: v for k, v in data.items() if not _user_owns(v, user_email)}
        removed = len(data) - len(kept)
        if removed:
            path.write_text(json.dumps(kept, indent=2))
    return removed


def _strip_user_from_jsonl_file(path: Path, user_email: str) -> int:
    """Remove user-owned lines from a JSONL file. Returns count."""
    if not path.exists():
        return 0
    removed = 0
    kept_lines: List[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            kept_lines.append(line)
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            kept_lines.append(line)
            continue
        if _user_owns(record, user_email):
            removed += 1
        else:
            kept_lines.append(line)
    if removed:
        path.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""))
    return removed


def _delete_workspace_tree(workspace_id: str) -> Dict[str, int]:
    """Delete every file under a workspace directory. Returns counts per category."""
    deleted = _empty_deleted_items()
    ws_path = WORKSPACE_DIR / workspace_id
    if not ws_path.exists():
        return deleted

    # Remove each deletable subdirectory tree (files + the directory itself).
    # Track the nested tasks archive separately before the tasks tree is removed.
    deleted["tasks_archive"] = _remove_path(ws_path / "tasks" / "archive")

    subdir_category = {
        "tasks": "tasks",
        "findings": "findings",
        "audit": "audit_logs",
        "briefings": "briefings",
        "exports": "exports",
        "pnl": "office_pnl",
    }
    for subdir in WORKSPACE_SUBDIRS:
        count = _remove_path(ws_path / subdir)
        category = subdir_category.get(subdir)
        if category:
            deleted[category] += count

    # Global office P&L file.
    if OFFICE_PNL_FILE.exists():
        deleted["office_pnl"] += _json_entry_count(OFFICE_PNL_FILE)
        OFFICE_PNL_FILE.unlink(missing_ok=True)

    # Global calibration ledger.
    if CALIBRATION_FILE.exists():
        deleted["calibration_ledger"] += _json_entry_count(CALIBRATION_FILE)
        CALIBRATION_FILE.unlink(missing_ok=True)

    # Remove metadata files (not reported as a deletion category).
    for filename in WORKSPACE_FILES:
        _remove_path(ws_path / filename)

    # Remove the workspace directory itself if now empty.
    try:
        if ws_path.exists() and not any(ws_path.iterdir()):
            ws_path.rmdir()
    except OSError:
        pass

    return deleted


def _delete_user_files_in_workspace(workspace_id: str, user_email: str) -> Dict[str, int]:
    """Delete user-owned data inside a single workspace. Returns counts per category."""
    deleted = _empty_deleted_items()
    ws_path = WORKSPACE_DIR / workspace_id
    if not ws_path.exists():
        return deleted

    category_dirs = {
        "tasks": ws_path / "tasks",
        "tasks_archive": ws_path / "tasks" / "archive",
        "findings": ws_path / "findings",
        "briefings": ws_path / "briefings",
        "exports": ws_path / "exports",
    }
    for category, directory in category_dirs.items():
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            removed = 0
            if isinstance(data, dict) and _user_owns(data, user_email):
                removed = 1
                path.unlink(missing_ok=True)
            elif isinstance(data, list):
                kept = [r for r in data if not _user_owns(r, user_email)]
                removed = len(data) - len(kept)
                if removed:
                    path.write_text(json.dumps(kept, indent=2))
            deleted[category] += removed

    # Remove user-owned audit log records.
    audit_dir = ws_path / "audit"
    if audit_dir.is_dir():
        for path in sorted(audit_dir.glob("*.jsonl")):
            deleted["audit_logs"] += _strip_user_from_jsonl_file(path, user_email)

    # Remove the user from workspace membership.
    users_path = ws_path / "users.json"
    if users_path.exists():
        try:
            users = json.loads(users_path.read_text())
        except (json.JSONDecodeError, OSError):
            users = {}
        if isinstance(users, dict) and user_email in users:
            del users[user_email]
            users_path.write_text(json.dumps(users, indent=2))

    # Global ledgers: strip user-attributable entries (if any).
    if OFFICE_PNL_FILE.exists():
        deleted["office_pnl"] += _strip_user_from_json_file(OFFICE_PNL_FILE, user_email)
    if CALIBRATION_FILE.exists():
        deleted["calibration_ledger"] += _strip_user_from_json_file(CALIBRATION_FILE, user_email)

    return deleted


def _start_deletion(delete_id: str, extra: Dict) -> Dict:
    record = {
        "delete_id": delete_id,
        "status": STATUS_PENDING,
        "deleted_items": _empty_deleted_items(),
        "deleted_at": None,
    }
    record.update(extra)
    _record_deletion(delete_id, record)
    return record


def _finish_deletion(delete_id: str, status: str, deleted_items: Dict[str, int]) -> Dict:
    record = _load_deletion(delete_id) or {}
    record["status"] = status
    record["deleted_items"] = deleted_items
    record["deleted_at"] = _now()
    _record_deletion(delete_id, record)
    return record


def delete_workspace_data(workspace_id: str, confirm: bool = False) -> dict:
    """Delete all data for a workspace.

    Requires confirm=True to actually delete. Returns a dict with the
    workspace id, status, per-category deleted item counts, and timestamp.
    """
    delete_id = _new_delete_id()
    record = _start_deletion(delete_id, {"workspace_id": workspace_id})

    if not confirm:
        # Nothing was deleted and no deletion was initiated, so no record is
        # created and get_deletion_status() has nothing to look up.
        return {
            "workspace_id": workspace_id,
            "status": STATUS_NOT_DELETED,
            "deleted_items": _empty_deleted_items(),
            "deleted_at": _now(),
        }

    try:
        deleted_items = _delete_workspace_tree(workspace_id)
        finished = _finish_deletion(delete_id, STATUS_COMPLETED, deleted_items)
        return {
            "workspace_id": workspace_id,
            "status": STATUS_DELETED,
            "deleted_items": deleted_items,
            "deleted_at": finished["deleted_at"],
            "delete_id": delete_id,
        }
    except Exception as exc:  # noqa: BLE001 - surface failure via status record
        finished = _finish_deletion(delete_id, STATUS_FAILED, _empty_deleted_items())
        return {
            "workspace_id": workspace_id,
            "status": STATUS_FAILED,
            "deleted_items": {},
            "deleted_at": finished["deleted_at"],
            "delete_id": delete_id,
            "error": str(exc),
        }


def delete_user_data_from_workspace(workspace_id: str, user_email: str) -> dict:
    """Delete all user-owned data from a single workspace."""
    delete_id = _new_delete_id()
    record = _start_deletion(delete_id, {
        "workspace_id": workspace_id,
        "user_email": user_email,
    })

    try:
        deleted_items = _delete_user_files_in_workspace(workspace_id, user_email)
        finished = _finish_deletion(delete_id, STATUS_COMPLETED, deleted_items)
        return {
            "workspace_id": workspace_id,
            "user_email": user_email,
            "status": STATUS_DELETED,
            "deleted_items": deleted_items,
            "deleted_at": finished["deleted_at"],
            "delete_id": delete_id,
        }
    except Exception as exc:  # noqa: BLE001 - surface failure via status record
        finished = _finish_deletion(delete_id, STATUS_FAILED, _empty_deleted_items())
        return {
            "workspace_id": workspace_id,
            "user_email": user_email,
            "deleted_items": {},
            "deleted_at": finished["deleted_at"],
            "delete_id": delete_id,
            "error": str(exc),
        }


def delete_user_data(user_email: str, workspace_ids: List[str]) -> dict:
    """Delete all user data across multiple workspaces (right to be forgotten)."""
    delete_id = _new_delete_id()
    record = _start_deletion(delete_id, {
        "user_email": user_email,
        "workspaces": list(workspace_ids),
    })

    aggregated = _empty_deleted_items()
    completed_workspaces: List[str] = []

    try:
        for workspace_id in workspace_ids:
            result = delete_user_data_from_workspace(workspace_id, user_email)
            if result.get("status") != STATUS_FAILED:
                completed_workspaces.append(workspace_id)
                for category, count in result.get("deleted_items", {}).items():
                    aggregated[category] = aggregated.get(category, 0) + count

        finished = _finish_deletion(delete_id, STATUS_COMPLETED, aggregated)
        return {
            "user_email": user_email,
            "workspaces": completed_workspaces,
            "status": STATUS_DELETED,
            "deleted_items": aggregated,
            "deleted_at": finished["deleted_at"],
            "delete_id": delete_id,
        }
    except Exception as exc:  # noqa: BLE001 - surface failure via status record
        finished = _finish_deletion(delete_id, STATUS_FAILED, aggregated)
        return {
            "user_email": user_email,
            "workspaces": completed_workspaces,
            "deleted_items": aggregated,
            "deleted_at": finished["deleted_at"],
            "delete_id": delete_id,
            "error": str(exc),
        }


def get_deletion_status(delete_id: str) -> dict:
    """Get the status of a previously recorded deletion."""
    record = _load_deletion(delete_id)
    if record is None:
        return {
            "delete_id": delete_id,
            "status": STATUS_FAILED,
            "deleted_items": _empty_deleted_items(),
            "deleted_at": None,
        }
    return {
        "delete_id": record.get("delete_id", delete_id),
        "status": record.get("status", STATUS_FAILED),
        "deleted_items": record.get("deleted_items", _empty_deleted_items()),
        "deleted_at": record.get("deleted_at"),
    }
