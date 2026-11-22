"""
Proactive Fleet Monitor for THE CLAUDE COMPANY.

Monitors fleet health metrics and proactively alerts Dost when anomalies
are detected. Read-only monitoring — no live orders, no strategy hunting.

Notification: one iMessage per cycle (coalesced across alerts), deduped per
metric for 60 minutes so a repeating failure pings you once an hour, not
every cycle. History is appended to jarvis_memory/alerts.jsonl so no alert
is ever lost, even if iMessage delivery fails.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

DISPATCHER_METRICS_URL = "http://127.0.0.1:8083/metrics"
FINDINGS_STORE_PATH = str(Path.home() / "Documents" / "polymarket" / "research" / "findings.json")
OFFICE_PNL_PATH = str(Path.home() / ".openclaw" / "office_pnl.json")

# Thresholds for proactive alerts
ERROR_RATE_THRESHOLD = 5.0  # %
ERROR_RATE_CRITICAL = 10.0  # %
COOLING_THRESHOLD = 60  # seconds
HEADROOM_CRITICAL = 20  # %

# Notification tuning
DEDUP_TTL = 3600  # seconds — same metric notifies at most once per hour
IMSG_TO = "+918449447444"

# The runtime state directory is dost/jarvis_memory/ -- ONE directory for the
# whole package, not one per subpackage.
#
# This module used to live at dost/proactive_monitor.py, where
# `Path(__file__).resolve().parent / "jarvis_memory"` happened to land on the
# right place. The subpackage refactor moved the module to dost/ops/ without
# moving the state directory, so the same expression silently resolved to a
# NEW empty dost/ops/jarvis_memory/ and every alert was written where nobody
# reads it -- the reader (context_builder.alerts_section) still reads
# dost/jarvis_memory/alerts.jsonl.
#
# Two parents is the package root (dost/), which is where the state lives.
DOST_DIR = Path(__file__).resolve().parent.parent
JARVIS_DIR = DOST_DIR / "jarvis_memory"
JARVIS_DIR.mkdir(parents=True, exist_ok=True)
ALERTS_LOG = JARVIS_DIR / "alerts.jsonl"
DEDUP_STATE = JARVIS_DIR / "alerts_dedup.json"

IMSG_PATH = shutil.which("imsg") or "/opt/homebrew/bin/imsg"


def fetch_metrics() -> Optional[dict]:
    """Fetch live fleet metrics from dispatcher."""
    try:
        with urllib.request.urlopen(DISPATCHER_METRICS_URL, timeout=4) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def fetch_findings() -> Optional[dict]:
    """Fetch findings store."""
    try:
        p = Path(FINDINGS_STORE_PATH)
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return None


def fetch_pnl() -> Optional[dict]:
    """Fetch office P&L data."""
    try:
        p = Path(OFFICE_PNL_PATH)
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return None


def check_fleet_health() -> list[dict]:
    """Check fleet health and return list of alerts.

    Returns list of alert dicts with 'severity', 'message', 'metric'.
    """
    alerts: list[dict] = []
    metrics = fetch_metrics()

    if metrics is None:
        alerts.append({
            "severity": "critical",
            "message": "Dispatcher unreachable - :8083/metrics not responding",
            "metric": "dispatcher_reachability"
        })
        return alerts

    jev = metrics.get("jev", {})
    pools = metrics.get("provider_pools", {})
    free = metrics.get("free_ceiling", {})

    # Check error rate
    error_rate = jev.get("error_rate_total", 0)
    if error_rate >= ERROR_RATE_CRITICAL:
        alerts.append({
            "severity": "critical",
            "message": f"Error rate critically high: {error_rate:.1f}%",
            "metric": "error_rate_critical"
        })
    elif error_rate >= ERROR_RATE_THRESHOLD:
        alerts.append({
            "severity": "warning",
            "message": f"Error rate elevated: {error_rate:.1f}%",
            "metric": "error_rate_warning"
        })

    # Check provider pools
    for pool_name, pool_info in pools.items():
        cooldown = pool_info.get("cooldown_remaining", 0)
        available = pool_info.get("available", False)
        if not available and cooldown > COOLING_THRESHOLD:
            alerts.append({
                "severity": "warning",
                "message": f"Pool {pool_name} cooling down for {cooldown:.0f}s",
                "metric": f"pool_cooldown_{pool_name}"
            })
        elif not available:
            alerts.append({
                "severity": "critical",
                "message": f"Pool {pool_name} is down",
                "metric": f"pool_down_{pool_name}"
            })

    # Check headroom
    headroom_pct = free.get("headroom_pct", 100)
    if headroom_pct < HEADROOM_CRITICAL:
        alerts.append({
            "severity": "warning",
            "message": f"Free-tier headroom low: {headroom_pct:.0f}%",
            "metric": "headroom_low"
        })

    # Check findings pending
    findings = fetch_findings()
    if findings:
        findings_list = findings.get("findings", [])
        pending_count = sum(1 for f in findings_list if f.get("verification_status") == "pending")
        contested_count = sum(1 for f in findings_list if f.get("verification_status") == "contested")
        if pending_contested := pending_count + contested_count:
            if pending_contested > 5:
                alerts.append({
                    "severity": "warning",
                    "message": f"{pending_contested} findings need Tier C review",
                    "metric": "findings_pending"
                })

    return alerts


def format_alert(alert: dict) -> str:
    """Format an alert for spoken output."""
    severity = alert.get("severity", "unknown")
    message = alert.get("message", "Unknown alert")
    if severity == "critical":
        return f"Critical alert: {message}"
    elif severity == "warning":
        return f"Warning: {message}"
    return message


def _load_dedup() -> dict[str, float]:
    try:
        return json.loads(DEDUP_STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save_dedup(state: dict[str, float]) -> None:
    now = time.time()
    state = {k: v for k, v in state.items() if now - v < DEDUP_TTL}
    with open(DEDUP_STATE, "w") as f:
        json.dump(state, f, indent=2)


def _append_alerts(alerts: list[dict]) -> None:
    """Append alerts to the persistent JSONL history."""
    ts = time.time()
    with open(ALERTS_LOG, "a") as f:
        for a in alerts:
            entry = dict(a)
            entry["ts"] = ts
            f.write(json.dumps(entry) + "\n")


def _send_imsg(text: str) -> bool:
    """Send one iMessage. Returns True if the subprocess exited 0."""
    try:
        result = subprocess.run(
            [IMSG_PATH, "send", "--to", IMSG_TO, "--text", text],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def notify(alerts: list[dict]) -> tuple[int, int]:
    """Coalesce + dedupe + notify.

    Returns (sent_count, present_count) — present is every alert this cycle,
    sent is how many were actually pushed via iMessage. All alerts are
    appended to the JSONL history regardless of delivery.
    """
    if not alerts:
        return 0, 0
    state = _load_dedup()
    now = time.time()
    fresh = [a for a in alerts if now - state.get(a["metric"], 0) > DEDUP_TTL]
    for a in fresh:
        state[a["metric"]] = now
    _save_dedup(state)

    _append_alerts(alerts)

    if not fresh:
        return 0, len(alerts)

    # Coalesce every fresh alert into a single iMessage.
    lines = []
    for a in fresh:
        sev = a.get("severity", "unknown").upper()
        lines.append(f"[{sev}] {a['message']}")
    body = "Fleet alert(s):\n" + "\n".join(lines)

    if _send_imsg(body):
        return len(fresh), len(alerts)
    return 0, len(alerts)


def run_monitor_once() -> list[dict]:
    """Run one monitoring cycle. Returns the full list of alerts present."""
    alerts = check_fleet_health()
    sent, present = notify(alerts)
    if present == 0:
        print("All systems normal")
    elif sent == present:
        print(f"Notified {sent} alert(s) via iMessage")
    elif sent == 0:
        print(f"{present} alert(s) present but iMessage delivery failed — see {ALERTS_LOG}")
    else:
        print(f"Sent {sent}/{present} alert(s) via iMessage — rest already notified this hour")
    return alerts


def speak_alert(text: str) -> bool:
    """Speak an alert using system TTS (retained for compat, not used by monitor)."""
    try:
        import subprocess
        subprocess.run(
            ["say", text],
            capture_output=True,
            timeout=10
        )
        return True
    except Exception:
        return False


if __name__ == "__main__":
    run_monitor_once()
