"""
Audit logging for THE CLAUDE COMPANY.

Each workspace stores an append-only audit log as JSONL files, one per day:
    ~/.openclaw/workspaces/{workspace_id}/audit/{YYYY-MM-DD}.jsonl

Each audit record:
    {
        "audit_id": "...",
        "workspace_id": "...",
        "user_email": "...",
        "action": "...",
        "resource_type": "...",
        "resource_id": "...",
        "timestamp": "YYYY-MM-DDTHH:MM:SSZ",
        "details": {...}
    }
"""

import json
import os
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
BASE_DIR.mkdir(parents=True, exist_ok=True)


def _audit_dir(workspace_id: str) -> Path:
    return BASE_DIR / workspace_id / "audit"


def _audit_file(workspace_id: str, date_str: str) -> Path:
    return _audit_dir(workspace_id) / f"{date_str}.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_jsonl_lines(path: Path) -> List[dict]:
    """Read all valid JSON objects from a JSONL file."""
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


def log_audit_event(
    workspace_id: str,
    user_email: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict = None,
) -> dict:
    """Log an audit event and append it to the workspace audit log.

    Returns the audit record that was stored.
    """
    audit_id = f"audit-{uuid.uuid4().hex[:12]}"
    timestamp = _now_iso()
    record = {
        "audit_id": audit_id,
        "workspace_id": workspace_id,
        "user_email": user_email,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "timestamp": timestamp,
        "details": details if details is not None else {},
    }

    audit_dir = _audit_dir(workspace_id)
    audit_dir.mkdir(parents=True, exist_ok=True)
    with open(_audit_file(workspace_id, _today()), "a") as f:
        f.write(json.dumps(record) + "\n")

    return record


def _all_audit_records(workspace_id: str) -> List[dict]:
    """Read every audit record for a workspace across all daily files."""
    audit_dir = _audit_dir(workspace_id)
    if not audit_dir.exists():
        return []
    records: List[dict] = []
    for path in sorted(audit_dir.glob("*.jsonl")):
        records.extend(_read_jsonl_lines(path))
    return records


def _in_date_range(timestamp: str, start_date: str = None, end_date: str = None) -> bool:
    """Check whether an ISO timestamp falls within [start_date, end_date] (inclusive)."""
    if not timestamp:
        return False
    try:
        record_date = timestamp[:10]
    except (TypeError, AttributeError):
        return False
    if start_date and record_date < start_date:
        return False
    if end_date and record_date > end_date:
        return False
    return True


def get_audit_logs(
    workspace_id: str,
    start_date: str = None,
    end_date: str = None,
    user_email: str = None,
    action: str = None,
) -> List[dict]:
    """Return audit logs for a workspace, newest first, with optional filters."""
    records = _all_audit_records(workspace_id)
    filtered = [
        r
        for r in records
        if _in_date_range(r.get("timestamp", ""), start_date, end_date)
        and (user_email is None or r.get("user_email") == user_email)
        and (action is None or r.get("action") == action)
    ]
    filtered.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return filtered


def export_audit_logs(
    workspace_id: str,
    start_date: str = None,
    end_date: str = None,
) -> str:
    """Export audit logs for a workspace as a JSONL string."""
    records = get_audit_logs(workspace_id, start_date=start_date, end_date=end_date)
    return "\n".join(json.dumps(r) for r in records)


def get_audit_summary(workspace_id: str, days: int = 30) -> dict:
    """Return an audit summary for the last ``days`` days."""
    today = date.today()
    start_date = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    records = get_audit_logs(workspace_id, start_date=start_date, end_date=end_date)

    by_action: Dict[str, int] = Counter()
    by_user: Dict[str, int] = Counter()
    by_day: Dict[str, int] = Counter()
    for r in records:
        by_action[r.get("action", "unknown")] += 1
        by_user[r.get("user_email", "unknown")] += 1
        by_day[(r.get("timestamp", "") or "")[:10]] += 1

    return {
        "total_events": len(records),
        "by_action": dict(by_action),
        "by_user": dict(by_user),
        "by_day": dict(by_day),
    }
