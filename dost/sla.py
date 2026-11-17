"""SLA tracking for THE CLAUDE COMPANY.

Records SLA events per workspace as JSONL files under
``~/.openclaw/workspaces/{workspace_id}/sla/{date}.jsonl`` and exposes
aggregation helpers for metrics, overall status, and alerts.
"""

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

BASE_DIR = Path.home() / ".openclaw" / "workspaces"

VALID_EVENT_TYPES = {"response_time", "availability", "error_rate"}

# Metrics where a higher value than the threshold is a violation.
HIGHER_IS_WORSE = {"response_time", "error_rate"}


def _sla_dir(workspace_id: str) -> Path:
    return BASE_DIR / workspace_id / "sla"


def _event_file(workspace_id: str, d: date) -> Path:
    return _sla_dir(workspace_id) / f"{d.isoformat()}.jsonl"


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _read_events(workspace_id: str, start_date: str = None, end_date: str = None) -> list:
    """Read all SLA events for a workspace within an optional date range."""
    events = []
    sla_dir = _sla_dir(workspace_id)
    if not sla_dir.is_dir():
        return events

    start = _parse_date(start_date) if start_date else None
    end = _parse_date(end_date) if end_date else None

    for file_path in sorted(sla_dir.glob("*.jsonl")):
        try:
            file_date = date.fromisoformat(file_path.stem)
        except ValueError:
            continue
        if start is not None and file_date < start:
            continue
        if end is not None and file_date > end:
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return events


def record_sla_event(workspace_id: str, event_type: str, metric_name: str, value: float, threshold: float) -> dict:
    """Record an SLA event and append it to the workspace's daily JSONL file.

    Returns the recorded event dict.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(
            f"Invalid event_type: {event_type!r}. Must be one of {sorted(VALID_EVENT_TYPES)}"
        )

    event_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    met_sla = is_sla_met(workspace_id, metric_name, value, threshold)

    event = {
        "event_id": event_id,
        "workspace_id": workspace_id,
        "event_type": event_type,
        "metric_name": metric_name,
        "value": float(value),
        "threshold": float(threshold),
        "met_sla": bool(met_sla),
        "timestamp": timestamp,
    }

    sla_dir = _sla_dir(workspace_id)
    sla_dir.mkdir(parents=True, exist_ok=True)
    with open(_event_file(workspace_id, date.today()), "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    return event


def get_sla_metrics(workspace_id: str, metric_name: str, start_date: str = None, end_date: str = None) -> dict:
    """Get aggregated SLA metrics for a specific metric over an optional date range."""
    events = _read_events(workspace_id, start_date, end_date)
    metric_events = [e for e in events if e.get("metric_name") == metric_name]

    total_events = len(metric_events)
    met_sla_count = sum(1 for e in metric_events if e.get("met_sla"))
    violated_count = total_events - met_sla_count
    sla_percentage = (met_sla_count / total_events * 100) if total_events else 0.0

    values = [e.get("value") for e in metric_events if e.get("value") is not None]
    avg_value = sum(values) / len(values) if values else 0.0
    max_value = max(values) if values else 0.0
    min_value = min(values) if values else 0.0

    return {
        "workspace_id": workspace_id,
        "metric_name": metric_name,
        "total_events": total_events,
        "met_sla_count": met_sla_count,
        "violated_count": violated_count,
        "sla_percentage": round(sla_percentage, 2),
        "avg_value": round(avg_value, 4),
        "max_value": round(max_value, 4),
        "min_value": round(min_value, 4),
    }


def get_sla_status(workspace_id: str) -> dict:
    """Get overall SLA status for a workspace: percentage, per-metric summary, alerts."""
    events = _read_events(workspace_id)
    total_events = len(events)
    met_sla_count = sum(1 for e in events if e.get("met_sla"))
    overall_sla_percentage = (met_sla_count / total_events * 100) if total_events else 0.0

    by_metric = {}
    for e in events:
        by_metric.setdefault(e.get("metric_name"), []).append(e)

    metrics = {}
    for metric_name, evs in by_metric.items():
        total = len(evs)
        met = sum(1 for e in evs if e.get("met_sla"))
        pct = (met / total * 100) if total else 0.0
        values = [e.get("value") for e in evs if e.get("value") is not None]
        thresholds = [e.get("threshold") for e in evs if e.get("threshold") is not None]
        metrics[metric_name] = {
            "total_events": total,
            "met_sla_count": met,
            "violated_count": total - met,
            "sla_percentage": round(pct, 2),
            "avg_value": round(sum(values) / len(values), 4) if values else 0.0,
            "threshold": thresholds[-1] if thresholds else None,
        }

    return {
        "workspace_id": workspace_id,
        "overall_sla_percentage": round(overall_sla_percentage, 2),
        "metrics": metrics,
        "alerts": get_sla_alerts(workspace_id),
    }


def get_sla_alerts(workspace_id: str) -> list:
    """Get SLA alerts for metrics currently violating their threshold.

    Returns a list of dicts with metric_name, current_value, threshold, and
    severity ("warning" or "critical").
    """
    events = _read_events(workspace_id)

    # Latest event per metric.
    latest_by_metric = {}
    for e in events:
        mn = e.get("metric_name")
        ts = e.get("timestamp", "")
        if mn not in latest_by_metric or ts > latest_by_metric[mn].get("timestamp", ""):
            latest_by_metric[mn] = e

    alerts = []
    for metric_name, e in latest_by_metric.items():
        value = e.get("value")
        threshold = e.get("threshold")
        event_type = e.get("event_type")
        if value is None or threshold is None:
            continue

        if event_type in HIGHER_IS_WORSE:
            violated = value > threshold
            ratio = value / threshold if threshold else 0
        else:  # availability: lower than threshold is a violation
            violated = value < threshold
            ratio = threshold / value if value else 0

        if not violated:
            continue

        severity = "critical" if ratio >= 1.5 else "warning"
        alerts.append({
            "metric_name": metric_name,
            "current_value": value,
            "threshold": threshold,
            "severity": severity,
        })

    return alerts


def is_sla_met(workspace_id: str, metric_name: str, value: float, threshold: float) -> bool:
    """Check whether a metric value meets its SLA threshold."""
    return float(value) <= float(threshold)
