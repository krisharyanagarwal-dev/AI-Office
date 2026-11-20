"""
Data export for THE CLAUDE COMPANY.

Exports workspace and user data from
    ~/.openclaw/workspaces/{workspace_id}/exports/{export_id}.{format}

Supports JSON and JSONL export formats.
"""

import json
import uuid
import time
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

RESEARCH_DIR = Path("/Users/aryanagarwal/Documents/indian-paper-trading")
CALIBRATION_FILE = RESEARCH_DIR / "results" / "calibration_ledger.json"
OFFICE_PNL_FILE = Path("/Users/aryanagarwal/.openclaw/office_pnl.json")

EXPORT_STATUS_DIR = Path(os.path.expanduser("~/.openclaw/exports"))
EXPORT_STATUS_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ")


def _export_id() -> str:
    return f"exp-{uuid.uuid4().hex[:12]}"


def _read_json_file(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return None


def _read_jsonl_file(path: Path) -> List[dict]:
    records: List[dict] = []
    if not path.exists():
        return records
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return records


def _workspace_dir(workspace_id: str) -> Path:
    return WORKSPACE_DIR / workspace_id


def _workspace_exists(workspace_id: str) -> bool:
    return _workspace_dir(workspace_id).exists()


def _workspace_tasks(workspace_id: str) -> List[dict]:
    tasks_dir = _workspace_dir(workspace_id) / "tasks"
    tasks: List[dict] = []
    if tasks_dir.exists():
        for path in sorted(tasks_dir.glob("*.json")):
            data = _read_json_file(path)
            if data is not None:
                tasks.append(data)
    return tasks


def _workspace_findings(workspace_id: str) -> List[dict]:
    findings_dir = _workspace_dir(workspace_id) / "findings"
    findings: List[dict] = []
    if findings_dir.exists():
        for path in sorted(findings_dir.glob("*.json")):
            data = _read_json_file(path)
            if data is not None:
                findings.append(data)
    return findings


def _workspace_audit_logs(workspace_id: str) -> List[dict]:
    from dost.ops.audit_log import get_audit_logs
    return get_audit_logs(workspace_id)


def _workspace_calibration_ledger() -> Optional[dict]:
    return _read_json_file(CALIBRATION_FILE)


def _office_pnl() -> Optional[dict]:
    return _read_json_file(OFFICE_PNL_FILE)


def _write_export(payload: Any, file_path: Path, fmt: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jsonl":
        if isinstance(payload, list):
            with open(file_path, "w") as f:
                for item in payload:
                    f.write(json.dumps(item) + "\n")
        else:
            with open(file_path, "w") as f:
                f.write(json.dumps(payload) + "\n")
    else:
        with open(file_path, "w") as f:
            json.dump(payload, f, indent=2)


def _save_export_status(export_id: str, status: str, download_url: str, created_at: str) -> None:
    status_path = EXPORT_STATUS_DIR / f"{export_id}.json"
    with open(status_path, "w") as f:
        json.dump({
            "export_id": export_id,
            "status": status,
            "download_url": download_url,
            "created_at": created_at,
        }, f, indent=2)


def _load_export_status(export_id: str) -> Optional[dict]:
    status_path = EXPORT_STATUS_DIR / f"{export_id}.json"
    return _read_json_file(status_path)


def export_workspace_data(workspace_id: str, format: str = "json") -> dict:
    """Export all workspace data: tasks, findings, audit logs, calibration ledger, office P&L.

    Returns: {"export_id", "workspace_id", "format", "file_path", "created_at", "record_counts"}
    """
    if format not in ("json", "jsonl"):
        raise ValueError(f"Unsupported format: {format}. Use 'json' or 'jsonl'.")

    if not _workspace_exists(workspace_id):
        raise FileNotFoundError(f"Workspace not found: {workspace_id}")

    export_id = _export_id()
    created_at = _now_iso()

    tasks = _workspace_tasks(workspace_id)
    findings = _workspace_findings(workspace_id)
    audit_logs = _workspace_audit_logs(workspace_id)
    calibration_ledger = _workspace_calibration_ledger()
    office_pnl = _office_pnl()

    record_counts = {
        "tasks": len(tasks),
        "findings": len(findings),
        "audit_logs": len(audit_logs),
        "calibration_ledger": 1 if calibration_ledger is not None else 0,
        "office_pnl": 1 if office_pnl is not None else 0,
    }

    payload = {
        "export_id": export_id,
        "workspace_id": workspace_id,
        "format": format,
        "created_at": created_at,
        "record_counts": record_counts,
        "data": {
            "tasks": tasks,
            "findings": findings,
            "audit_logs": audit_logs,
            "calibration_ledger": calibration_ledger,
            "office_pnl": office_pnl,
        },
    }

    file_path = _workspace_dir(workspace_id) / "exports" / f"{export_id}.{format}"
    _write_export(payload, file_path, format)

    download_url = f"file://{file_path}"
    _save_export_status(export_id, "completed", download_url, created_at)

    return {
        "export_id": export_id,
        "workspace_id": workspace_id,
        "format": format,
        "file_path": str(file_path),
        "created_at": created_at,
        "record_counts": record_counts,
    }


def export_user_data(user_email: str, workspace_ids: List[str]) -> dict:
    """Export all data for a user across workspaces (GDPR).

    Returns: {"export_id", "user_email", "workspaces": [...], "file_path", "created_at"}
    """
    export_id = _export_id()
    created_at = _now_iso()

    workspaces = []
    for workspace_id in workspace_ids:
        if not _workspace_exists(workspace_id):
            workspaces.append({
                "workspace_id": workspace_id,
                "error": "workspace not found",
            })
            continue

        user_tasks = [
            t for t in _workspace_tasks(workspace_id)
            if t.get("user_email") == user_email or t.get("assigned_to") == user_email
            or t.get("owner") == user_email
        ]
        user_findings = [
            f for f in _workspace_findings(workspace_id)
            if f.get("user_email") == user_email or f.get("author") == user_email
        ]
        from dost.ops.audit_log import get_audit_logs
        user_audit_logs = [
            r for r in get_audit_logs(workspace_id)
            if r.get("user_email") == user_email
        ]

        workspaces.append({
            "workspace_id": workspace_id,
            "task_count": len(user_tasks),
            "finding_count": len(user_findings),
            "audit_log_count": len(user_audit_logs),
            "tasks": user_tasks,
            "findings": user_findings,
            "audit_logs": user_audit_logs,
        })

    file_path = EXPORT_STATUS_DIR / f"{export_id}.user.json"
    _write_export({
        "export_id": export_id,
        "user_email": user_email,
        "created_at": created_at,
        "workspaces": workspaces,
    }, file_path, "json")

    return {
        "export_id": export_id,
        "user_email": user_email,
        "workspaces": [w.get("workspace_id") for w in workspaces],
        "file_path": str(file_path),
        "created_at": created_at,
    }


def get_export_status(export_id: str) -> dict:
    """Get export status.

    Returns: {"export_id", "status", "download_url", "created_at"}
    """
    status = _load_export_status(export_id)
    if status is None:
        return {
            "export_id": export_id,
            "status": "failed",
            "download_url": None,
            "created_at": None,
        }
    return status


def list_exports(workspace_id: str) -> List[dict]:
    """List all exports for a workspace."""
    exports_dir = _workspace_dir(workspace_id) / "exports"
    exports: List[dict] = []
    if exports_dir.exists():
        for path in sorted(exports_dir.glob("*")):
            if not path.is_file():
                continue
            parts = path.name.rsplit(".", 1)
            if len(parts) != 2:
                continue
            export_id = parts[0]
            fmt = parts[1]
            status = _load_export_status(export_id)
            exports.append({
                "export_id": export_id,
                "format": fmt,
                "file_path": str(path),
                "status": status.get("status") if status else "unknown",
                "created_at": status.get("created_at") if status else None,
            })
    exports.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return exports
