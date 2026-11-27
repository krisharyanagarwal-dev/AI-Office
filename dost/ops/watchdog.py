"""Launchd watchdog for the Dost proactive agent.

Periodically checks whether the proactive agent (com.aryan.dost-proactive-agent)
is running, and restarts it via launchctl if it has died. Intended to be run
as its own launchd LaunchAgent with a short ThrottleInterval, layered on top
of the proactive agent's own KeepAlive for extra resilience.

Paper/testnet-only: restarting a dost service never places live orders.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROACTIVE_LABEL = "com.aryan.dost-proactive-agent"
PROACTIVE_PROC_PATTERN = "ops/proactive_agent.py"
LOG_PATH = Path("/Users/aryanagarwal/.openclaw/dost-watchdog.log")


def _log(message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {message}\n"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line)
    except Exception:
        pass
    print(line, end="")


def _is_running() -> bool:
    """Return True if the proactive agent process is alive."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", PROACTIVE_PROC_PATTERN],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception as e:
        _log(f"[watchdog] pgrep failed: {e}")
        return False


def _restart() -> bool:
    """Restart the proactive agent via launchctl kickstart."""
    try:
        result = subprocess.run(
            ["launchctl", "kickstart", "-p", PROACTIVE_LABEL],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            _log(f"[watchdog] Restarted {PROACTIVE_LABEL} via kickstart")
            return True
        _log(
            f"[watchdog] kickstart failed rc={result.returncode} "
            f"stderr={result.stderr.strip()}"
        )
        return False
    except Exception as e:
        _log(f"[watchdog] kickstart exception: {e}")
        return False


def run_once() -> None:
    """Single watchdog check: restart the proactive agent if it is not running."""
    if _is_running():
        _log(f"[watchdog] {PROACTIVE_LABEL} is running")
        return
    _log(f"[watchdog] {PROACTIVE_LABEL} not running; attempting restart")
    if _restart():
        time.sleep(2)
        if _is_running():
            _log(f"[watchdog] {PROACTIVE_LABEL} confirmed running after restart")
        else:
            _log(f"[watchdog] {PROACTIVE_LABEL} still not running after restart")


def main() -> None:
    _log("[watchdog] Watchdog started")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"[watchdog] Loop error: {e}")
        time.sleep(30)


if __name__ == "__main__":
    main()
