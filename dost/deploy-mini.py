#!/usr/bin/env python3
"""
Deploy the Dost mini server + shared page from the laptop's single source of truth.

Run on the laptop:
    python3 dost/deploy-mini.sh

Copies (single source -> mini):
  - dost/pet_page.html        -> mini: /Users/a/dost-mini/pet_page.html
  - dost/chat_core.py         -> mini: /Users/a/dost-mini/chat_core.py
  - dost/mini/dost_mini_server.py -> mini: /Users/a/dost-mini/dost_mini_server.py

Then restarts the mini's launchd job (com.aryan.dost-pet).

Stdlib only. Requires SSH access to a@macmini (SCP is unreliable on this link,
so files are streamed over interactive SSH stdin).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DOST_DIR = Path(__file__).resolve().parent
MINI_SERVER = DOST_DIR / "mini" / "dost_mini_server.py"
CHAT_CORE = DOST_DIR / "chat_core.py"
PAGE = DOST_DIR / "pet_page.html"

MINI_HOST = "a@macmini"
MINI_DIR = "/Users/a/dost-mini"

FILES = [
    (PAGE, f"{MINI_DIR}/pet_page.html"),
    (CHAT_CORE, f"{MINI_DIR}/chat_core.py"),
    (MINI_SERVER, f"{MINI_DIR}/dost_mini_server.py"),
]


def ssh(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    full = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", MINI_HOST, cmd]
    return subprocess.run(full, capture_output=True, text=True, check=check)


def put_file(local: Path, remote: str) -> subprocess.CompletedProcess:
    """Stream local file contents to remote path via SSH stdin (scp replacement)."""
    full = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", MINI_HOST,
            f"cat > {remote}"]
    with open(local, "rb") as f:
        return subprocess.run(full, stdin=f, capture_output=True, text=True)


def main() -> int:
    # 1. Reachability
    r = ssh("echo SSH_OK")
    if r.returncode != 0:
        print("FATAL: cannot SSH to macmini:", r.stderr.strip())
        return 1
    print("SSH to macmini: OK")

    # 2. Copy each file (single source -> mini)
    for local, remote in FILES:
        if not local.exists():
            print(f"FATAL: source missing: {local}")
            return 1
        r = put_file(local, remote)
        if r.returncode != 0:
            print(f"FATAL: put {local} -> {remote}: {r.stderr.strip()}")
            return 1
        print(f"deployed {local.name} -> {MINI_HOST}:{remote}")

    # 3. Restart the mini's launchd job (KeepAlive respawns)
    ssh("launchctl stop gui/$(id -u)/com.aryan.dost-pet 2>/dev/null; true")
    r = ssh("launchctl start gui/$(id -u)/com.aryan.dost-pet 2>/dev/null; "
            "sleep 4; lsof -nP -iTCP:8787 -sTCP:LISTEN -t 2>/dev/null || echo NOT_LISTENING")
    print("mini launchd restart output:", r.stdout.strip() or r.stderr.strip())

    # 4. Smoke test
    r = ssh("curl -s --max-time 10 http://127.0.0.1:8787/api/voice-status")
    print("mini voice-status:", r.stdout.strip())
    r = ssh("curl -s --max-time 10 -X POST http://127.0.0.1:8787/api/chat "
            "-H 'Content-Type: application/json' -d '{\"text\":\"deploy smoke test\",\"backend\":\"dost\"}'")
    print("mini chat:", r.stdout.strip()[:120])

    print("\nDeploy complete. Mini Dost is serving the shared page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
