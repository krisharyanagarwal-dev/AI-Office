"""
Usage metering for THE CLAUDE COMPANY workspaces.

Reads cost/usage ledger entries written to each workspace's pnl directory
(by the task dispatcher) and aggregates them into usage summaries.

Each ledger entry is expected to look like:
    {
        "task_id": "...",
        "agent_id": "...",
        "cost_units": 2,
        "metric_type": "task",          # optional; defaults to "task"
        "created_at": "2026-11-17T02:06:01Z",
        ...
    }
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))


def workspace_pnl_dir(workspace_id: str) -> Path:
    """Return the pnl ledger directory for a workspace."""
    return WORKSPACE_DIR / workspace_id / "pnl"


def _parse_ts(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; returns None if unparseable."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _read_ledger(workspace_id: str) -> List[dict]:
    """Read all ledger entries from a workspace's pnl directory."""
    pnl_dir = workspace_pnl_dir(workspace_id)
    entries: List[dict] = []
    if not pnl_dir.exists():
        return entries
    for f in sorted(pnl_dir.iterdir()):
        if f.suffix != ".json":
            continue
        try:
            data = json.loads(f.read_text())
            if isinstance(data, dict):
                entries.append(data)
            elif isinstance(data, list):
                entries.extend([e for e in data if isinstance(e, dict)])
        except Exception:
            continue
    return entries


def _in_range(entry: dict, start_date: Optional[str], end_date: Optional[str]) -> bool:
    """Check whether an entry's created_at falls within [start_date, end_date)."""
    created = entry.get("created_at", "")
    dt = _parse_ts(created)
    if dt is None:
        return False
    if start_date:
        start = _parse_ts(start_date)
        if start and dt < start:
            return False
    if end_date:
        end = _parse_ts(end_date)
        if end and dt >= end:
            return False
    return True


def get_usage(
    workspace_id: str,
    metric_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[dict]:
    """Return usage ledger entries for a workspace, optionally filtered.

    Filters:
        metric_type: only entries whose metric_type matches
        start_date:  only entries with created_at >= start_date (inclusive)
        end_date:    only entries with created_at < end_date (exclusive)
    """
    entries = _read_ledger(workspace_id)
    filtered: List[dict] = []
    for e in entries:
        if metric_type is not None and e.get("metric_type") != metric_type:
            continue
        if not _in_range(e, start_date, end_date):
            continue
        filtered.append(e)
    return filtered


def get_usage_summary(
    workspace_id: str,
    metric_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Return an aggregated usage summary for a workspace.

    Returns:
        {
            "workspace_id": ...,
            "period": "...",
            "total_cost_units": ...,
            "by_type": {...},
            "by_day": {...},
        }
    """
    entries = get_usage(
        workspace_id,
        metric_type=metric_type,
        start_date=start_date,
        end_date=end_date,
    )

    total_cost_units = sum(int(e.get("cost_units", 0) or 0) for e in entries)

    by_type: Dict[str, int] = {}
    by_day: Dict[str, int] = {}
    for e in entries:
        t = e.get("metric_type", "task")
        by_type[t] = by_type.get(t, 0) + int(e.get("cost_units", 0) or 0)
        created = e.get("created_at", "")
        day = created[:10] if created else "unknown"
        by_day[day] = by_day.get(day, 0) + int(e.get("cost_units", 0) or 0)

    if start_date and end_date:
        period = f"{start_date} to {end_date}"
    elif start_date:
        period = f"from {start_date}"
    elif end_date:
        period = f"until {end_date}"
    else:
        period = "current_month"

    return {
        "workspace_id": workspace_id,
        "period": period,
        "total_cost_units": total_cost_units,
        "by_type": by_type,
        "by_day": by_day,
    }


def get_current_month_cost(workspace_id: str) -> dict:
    """Return the cost incurred in the current calendar month for a workspace."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    summary = get_usage_summary(
        workspace_id,
        start_date=month_start.isoformat(),
        end_date=month_end.isoformat(),
    )

    return {
        "workspace_id": workspace_id,
        "month": month_start.strftime("%Y-%m"),
        "cost_units": summary["total_cost_units"],
        "by_type": summary["by_type"],
        "by_day": summary["by_day"],
    }
