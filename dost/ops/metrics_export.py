"""
Metrics export for THE CLAUDE COMPANY dispatcher.

Provides Prometheus-format metrics export and JSON metrics for
monitoring and observability.
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

from dost.collab.workspace import workspace_pnl_dir
from dost.billing.meter import get_usage_summary, get_current_month_cost


def export_metrics(workspace_id: str, format: str = "prometheus") -> str:
    """Export metrics in the specified format.

    Args:
        workspace_id: Workspace ID
        format: Export format ("json" or "prometheus")

    Returns:
        Exported metrics string
    """
    if format == "json":
        return json.dumps(get_metrics_summary(workspace_id), indent=2)
    elif format == "prometheus":
        return _export_prometheus(workspace_id)
    else:
        raise ValueError(f"Unknown format: {format}")


def _export_prometheus(workspace_id: str) -> str:
    """Export metrics in Prometheus exposition format."""
    metrics = get_metrics_summary(workspace_id)

    lines = [
        '# HELP dost_tasks_dispatched_total Total number of tasks dispatched',
        '# TYPE dost_tasks_dispatched_total counter',
        f'dost_tasks_dispatched_total{{workspace_id="{workspace_id}"}} {metrics["total_dispatches"]}',
        '',
        '# HELP dost_dispatch_errors_total Total number of dispatch errors',
        '# TYPE dost_dispatch_errors_total counter',
        f'dost_dispatch_errors_total{{workspace_id="{workspace_id}"}} {metrics["dispatch_errors"]}',
        '',
        '# HELP dost_dispatch_duration_seconds Dispatch duration in seconds',
        '# TYPE dost_dispatch_duration_seconds summary',
        f'# HELP dost_debate_rounds_total Total number of debate rounds',
        '# TYPE dost_debate_rounds_total counter',
        f'dost_debate_rounds_total{{workspace_id="{workspace_id}"}} {metrics["debate_rounds"]}',
        '',
        '# HELP dost_findings_confirmed_total Total number of confirmed findings',
        '# TYPE dost_findings_confirmed_total counter',
        f'dost_findings_confirmed_total{{workspace_id="{workspace_id}"}} {metrics["findings_confirmed"]}',
        '',
        '# HELP dost_findings_contested_total Total number of contested findings',
        '# TYPE dost_findings_contested_total counter',
        f'dost_findings_contested_total{{workspace_id="{workspace_id}"}} {metrics["findings_contested"]}',
        '',
        '# HELP dost_cost_units_total Total cost units consumed',
        '# TYPE dost_cost_units_total counter',
        f'dost_cost_units_total{{workspace_id="{workspace_id}"}} {metrics["cost_units_total"]}',
    ]

    return "\n".join(lines) + "\n"


def get_metrics_summary(workspace_id: str) -> dict:
    """Get metrics summary for a workspace.

    Args:
        workspace_id: Workspace ID

    Returns:
        Dict with total_dispatches, dispatch_errors, debate_rounds,
        findings_confirmed, findings_contested, total_cost_units,
        error_rate
    """
    from dost.billing.meter import get_usage_summary

    summary = get_usage_summary(workspace_id)

    return {
        "workspace_id": workspace_id,
        "total_dispatches": summary.get("by_type", {}).get("dispatch", 0),
        "dispatch_errors": summary.get("by_type", {}).get("dispatch_error", 0),
        "debate_rounds": summary.get("by_type", {}).get("debate", 0),
        "findings_confirmed": summary.get("by_type", {}).get("finding_confirmed", 0),
        "findings_contested": summary.get("by_type", {}).get("finding_contested", 0),
        "total_cost_units": summary.get("total_cost_units", 0),
        "error_rate": round(
            summary.get("by_type", {}).get("dispatch_error", 0) /
            max(summary.get("total_cost_units", 1), 1) * 100,
            2
        ),
    }