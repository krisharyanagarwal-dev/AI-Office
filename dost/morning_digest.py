#!/usr/bin/env python3
"""THE CLAUDE COMPANY — Dost Local Morning Digest.

Writes a daily digest markdown file to dost/briefings/digest-YYYY-MM-DD.md.

Content:
  - fleet status (from :8083/metrics)
  - P&L summary (from ~/.openclaw/office_pnl.json)
  - anomalies (error rate > 5%, pools down, headroom < 50%, pending findings)
  - pending findings count

Paper-only, read-only. No live orders ever.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COMPANY_DIR = Path(__file__).resolve().parent.parent
DOST_DIR = Path(__file__).resolve().parent
DOST_BRIEFINGS = DOST_DIR / "briefings"

DISPATCHER_METRICS_URL = "http://127.0.0.1:8083/metrics"
PNL_FILE = (Path.home() / ".openclaw" / "office_pnl.json")
FINDINGS_STORE = (Path.home() / "Documents" / "polymarket" / "research" / "findings.json")

ANOMALY_ERROR_RATE_PCT = 5.0
ANOMALY_HEADROOM_PCT = 50.0

# Findings that are confirmed or contested have been verified; anything else
# (pending or never statused) still awaits verification.
_UNVERIFIED_STATUSES = (None, "pending")


def _fetch_dispatcher_status() -> dict:
    """Read live fleet status from the dispatcher metrics endpoint. Read-only."""
    try:
        with urllib.request.urlopen(DISPATCHER_METRICS_URL, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        jev = data.get("jev", {})
        pools = data.get("provider_pools", {})
        available = sum(1 for p in pools.values() if p.get("available"))
        total = len(pools)
        return {
            "reachable": True,
            "tasks_created": jev.get("tasks_created", 0),
            "tasks_done": jev.get("tasks_done", 0),
            "completion_rate": jev.get("completion_rate", 0),
            "error_rate": jev.get("error_rate", 0),
            "error_rate_total": jev.get("error_rate_total", 0),
            "calls_today": jev.get("calls_today", 0),
            "headroom_pct": data.get("free_ceiling", {}).get("headroom_pct", 0),
            "pools_available": f"{available}/{total}",
            "pools": pools,
        }
    except Exception:
        return {"reachable": False}


def _pnl_summary() -> dict | None:
    """Summarize the office P&L task ledger."""
    try:
        tasks = json.loads(PNL_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(tasks, list):
        return None
    total_cost = sum(int(t.get("cost_units", 0) or 0) for t in tasks)
    total_value = sum(int(t.get("outcome_value", 0) or 0) for t in tasks)
    done = sum(1 for t in tasks if t.get("status") == "done")
    error = sum(1 for t in tasks if t.get("status") == "error")
    return {
        "count": len(tasks),
        "done": done,
        "error": error,
        "cost_units": total_cost,
        "outcome_value": total_value,
        "net_value": total_value - total_cost,
    }


def _pending_findings_count() -> int | None:
    """Count findings in the findings store that still await verification."""
    try:
        store = json.loads(FINDINGS_STORE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    findings = store.get("findings", []) if isinstance(store, dict) else []
    if not isinstance(findings, list):
        return None
    return sum(
        1 for f in findings if isinstance(f, dict) and f.get("verification_status") in _UNVERIFIED_STATUSES
    )


def build_digest() -> str:
    """Build the full digest markdown text."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fleet = _fetch_dispatcher_status()
    pnl = _pnl_summary()
    pending = _pending_findings_count()

    lines = [
        f"# Dost Morning Digest — {today}",
        "",
        "_Generated automatically. Paper-only. Kill switch locked. No live orders._",
        "",
    ]

    # --- Fleet status ---
    lines.append("## Fleet status")
    if fleet.get("reachable"):
        lines.append(
            f"- Dispatcher: reachable "
            f"({fleet['tasks_done']}/{fleet['tasks_created']} tasks done, "
            f"{fleet['completion_rate']:.0f}% complete)"
        )
        lines.append(f"- Error rate (total): {fleet['error_rate_total']:.1f}%")
        lines.append(f"- Calls today: {fleet['calls_today']}")
        lines.append(f"- Provider pools: {fleet['pools_available']} available")
        lines.append(f"- Free-tier headroom: {fleet['headroom_pct']:.0f}%")
    else:
        lines.append("- Dispatcher: UNREACHABLE (is jev-dispatcher running?)")
    lines.append("")

    # --- P&L summary ---
    lines.append("## P&L summary (office_pnl.json)")
    if pnl:
        lines.append(f"- Tasks: {pnl['count']} ({pnl['done']} done, {pnl['error']} error)")
        lines.append(f"- Cost units: {pnl['cost_units']}")
        lines.append(f"- Outcome value: {pnl['outcome_value']}")
        lines.append(f"- Net value: {pnl['net_value']}")
    else:
        lines.append("- No P&L data available.")
    lines.append("")

    # --- Anomalies ---
    lines.append("## Anomalies")
    anomalies: list[str] = []
    if not fleet.get("reachable"):
        anomalies.append("- Dispatcher unreachable")
    else:
        if fleet["error_rate_total"] > ANOMALY_ERROR_RATE_PCT:
            anomalies.append(
                f"- High error rate: {fleet['error_rate_total']:.1f}% "
                f"(> {ANOMALY_ERROR_RATE_PCT}%)"
            )
        try:
            avail_s, total_s = str(fleet["pools_available"]).split("/")
            if int(avail_s) < int(total_s):
                anomalies.append(f"- Pools down: {fleet['pools_available']} available")
        except (ValueError, AttributeError):
            pass
        if fleet["headroom_pct"] < ANOMALY_HEADROOM_PCT:
            anomalies.append(
                f"- Low free-tier headroom: {fleet['headroom_pct']:.0f}% "
                f"(< {ANOMALY_HEADROOM_PCT}%)"
            )
    if pnl and pnl["error"] > 0 and pnl["error"] > pnl["done"]:
        anomalies.append(
            f"- More P&L errors than done: {pnl['error']} error vs {pnl['done']} done"
        )
    if pending is not None and pending > 0:
        anomalies.append(f"- Pending findings awaiting verification: {pending}")
    if not anomalies:
        anomalies.append("- None detected. All systems nominal.")
    lines.extend(anomalies)
    lines.append("")

    # --- Pending findings count ---
    lines.append("## Pending findings")
    if pending is None:
        lines.append("- Findings store unavailable.")
    else:
        lines.append(f"- {pending} finding(s) awaiting verification.")
    lines.append("")
    lines.append("---")
    lines.append("_Dost — THE CLAUDE COMPANY. Paper-only, kill switch locked._")
    return "\n".join(lines)


def main() -> None:
    DOST_BRIEFINGS.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = DOST_BRIEFINGS / f"digest-{today}.md"
    out_path.write_text(build_digest())
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
