"""Launchd watchdog for Dost services.

Periodically checks whether each configured dost service is running via
`launchctl list <label>`, and restarts any that have died via
`launchctl kickstart -k -p gui/<uid>/<label>`. Intended to be run as its
own launchd LaunchAgent with a short ThrottleInterval, layered on top of
each service's own KeepAlive for extra resilience.

Paper/testnet-only: restarting a dost service never places live orders.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dost/  (for `import ops`)

from ops.self_healing import SERVICE_LABELS  # noqa: E402  (path inserted above)

LOG_PATH = (Path.home() / ".openclaw" / "dost-watchdog.log")


def _domain_target(label: str) -> str:
    """Return the launchd domain target for the current user session.

    macOS requires `gui/<uid>/<label>` for kickstart to resolve the service;
    a bare label yields "Unrecognized target specifier".
    """
    return f"gui/{os.getuid()}/{label}"


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


def _is_running(label: str) -> bool:
    """Return True if the dost service process is running.

    Uses ``pgrep -f`` to detect the live process rather than ``launchctl list``,
    which only reports whether launchd knows the label. A service can be known
    to launchd but have a dead process, so pgrep is the correct health signal
    for a watchdog.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", label],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        _log(f"[watchdog] pgrep {label} failed: {e}")
        return False


def _restart(label: str) -> bool:
    """Restart the launchd service with the given label via kickstart."""
    try:
        result = subprocess.run(
            ["launchctl", "kickstart", "-k", "-p", _domain_target(label)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            _log(f"[watchdog] Restarted {label} via kickstart")
            return True
        _log(
            f"[watchdog] kickstart failed for {label} "
            f"rc={result.returncode} stderr={result.stderr.strip()}"
        )
        return False
    except Exception as e:
        _log(f"[watchdog] kickstart exception for {label}: {e}")
        return False


def run_once() -> None:
    """Single watchdog cycle: restart any dost service that is not running."""
    for service_name, label in SERVICE_LABELS.items():
        if _is_running(label):
            _log(f"[watchdog] {service_name} ({label}) is running")
            continue
        _log(f"[watchdog] {service_name} ({label}) not running; attempting restart")
        if _restart(label):
            time.sleep(2)
            if _is_running(label):
                _log(f"[watchdog] {service_name} ({label}) confirmed running after restart")
            else:
                _log(f"[watchdog] {service_name} ({label}) still not running after restart")


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
