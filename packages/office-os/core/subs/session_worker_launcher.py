#!/usr/bin/env python3
"""
Session Worker Launcher - spawns Qwen3.5-9B workers for specific opencode sessions.

Usage:
  python3 session_worker_launcher.py spawn <session_id> [worker_count]
  python3 session_worker_launcher.py assign <session_id> <worker_id>
  python3 session_worker_launcher.py release <session_id> <worker_id>
  python3 session_worker_launcher.py list
  python3 session_worker_launcher.py status

Each session can claim up to max_workers_per_session (default 1) workers.
Workers are llama-server instances on port 11434 running
hauhaucs/qwen3.5-9b-uncensored-aggressive.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

REGISTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_registry.json")
WORKER_POOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_pool.json")
LLAMA_SERVER = "/Users/aryanagarwal/.local/lib/ollama-dist/llama-server"
MODEL_BLOB = "/Users/aryanagarwal/.ollama/models/blobs/sha256-2ca636d9e81d3d23ca9b60c234fe185d30ec082eeba69ce770fdb0c76559a4f5"
LOG_DIR = "/Users/aryanagarwal/Library/Logs"

os.makedirs(LOG_DIR, exist_ok=True)


def load_registry():
    with open(REGISTRY) as f:
        return json.load(f)


def save_registry(reg):
    with open(REGISTRY, "w") as f:
        json.dump(reg, f, indent=2)


def check_port(url):
    try:
        req = urllib.request.Request(url + "/v1/models")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def spawn_llama_server(port):
    """Start a llama-server instance on the given port if not already running."""
    url = f"http://127.0.0.1:{port}"
    if check_port(url):
        print(f"  Port {port} already responding, skipping spawn")
        return True

    log_file = os.path.join(LOG_DIR, f"llama_session_{port}.log")
    cmd = [
        LLAMA_SERVER,
        "--model", MODEL_BLOB,
        "--port", str(port),
        "--host", "127.0.0.1",
        "--no-webui", "--offline",
        "-c", "2048", "-np", "1",
        "--log-verbosity", "1",
        "--no-log-prefix", "--no-log-timestamps",
        "--no-mmap", "--flash-attn", "auto",
        "-b", "512", "-ub", "512",
        "--context-shift", "--keep", "4",
    ]
    with open(log_file, "w") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=lf)
    # Wait for it to come up
    for _ in range(30):
        time.sleep(1)
        if check_port(url):
            print(f"  llama-server on port {port} is UP (PID {proc.pid})")
            return True
    print(f"  WARNING: port {port} not responding after 30s")
    return False


def cmd_spawn(session_id, worker_count=1):
    reg = load_registry()
    max_per = reg.get("max_workers_per_session", 1)

    if session_id in reg["sessions"]:
        existing = reg["sessions"][session_id]
        print(f"Session '{session_id}' already exists with workers: {existing.get('workers', [])}")
        return

    available = [
        (wid, w) for wid, w in reg["workers"].items()
        if w["session"] is None
    ]

    if len(available) < worker_count:
        print(f"ERROR: Only {len(available)} free workers, requested {worker_count}")
        for wid, w in available:
            print(f"  Free: {wid} -> {w['url']}")
        return

    # Spawn any llama-servers that aren't responding yet
    for wid, w in available[:worker_count]:
        spawn_llama_server(w["port"])

    # Assign workers to session
    assigned = []
    for wid, w in available[:worker_count]:
        w["session"] = session_id
        w["status"] = "assigned"
        assigned.append(wid)

    reg["sessions"][session_id] = {
        "id": session_id,
        "workers": assigned,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "active",
    }
    save_registry(reg)

    print(f"Session '{session_id}' spawned with {len(assigned)} worker(s):")
    for wid in assigned:
        w = reg["workers"][wid]
        print(f"  {wid}: {w['url']} (affinity: {w['affinity']})")


def cmd_assign(session_id, worker_id):
    reg = load_registry()
    if session_id not in reg["sessions"]:
        print(f"ERROR: Session '{session_id}' not found. Spawn it first.")
        return
    if worker_id not in reg["workers"]:
        print(f"ERROR: Worker '{worker_id}' not found.")
        return
    w = reg["workers"][worker_id]
    if w["session"] is not None and w["session"] != session_id:
        print(f"ERROR: Worker '{worker_id}' already assigned to session '{w['session']}'")
        return
    if worker_id in reg["sessions"][session_id]["workers"]:
        print(f"Worker '{worker_id}' already in session '{session_id}'")
        return

    # Check max per session
    if len(reg["sessions"][session_id]["workers"]) >= reg.get("max_workers_per_session", 1):
        print(f"ERROR: Session '{session_id}' already at max workers ({reg['max_workers_per_session']})")
        return

    w["session"] = session_id
    w["status"] = "assigned"
    reg["sessions"][session_id]["workers"].append(worker_id)
    save_registry(reg)
    print(f"Assigned {worker_id} ({w['url']}) to session '{session_id}'")


def cmd_release(session_id, worker_id):
    reg = load_registry()
    if session_id not in reg["sessions"]:
        print(f"ERROR: Session '{session_id}' not found.")
        return
    if worker_id not in reg["sessions"][session_id]["workers"]:
        print(f"Worker '{worker_id}' not in session '{session_id}'")
        return

    reg["sessions"][session_id]["workers"].remove(worker_id)
    reg["workers"][worker_id]["session"] = None
    reg["workers"][worker_id]["status"] = "idle"
    save_registry(reg)
    print(f"Released {worker_id} from session '{session_id}'")


def cmd_list():
    reg = load_registry()
    print("Active Sessions:")
    if not reg["sessions"]:
        print("  (none)")
    for sid, s in reg["sessions"].items():
        print(f"  {sid}: status={s['status']}, workers={s['workers']}, created={s['created_at']}")

    print("\nWorkers:")
    for wid, w in reg["workers"].items():
        sess = w["session"] or "free"
        print(f"  {wid}: {w['url']} -> session={sess} status={w['status']}")


def cmd_status():
    reg = load_registry()
    print("Qwen3.5-9B Worker Status:")
    for wid, w in reg["workers"].items():
        alive = check_port(w["url"])
        sess = w["session"] or "free"
        print(f"  {wid}: {w['url']} alive={alive} session={sess} status={w['status']}")

    print(f"\nSessions: {len(reg['sessions'])} active")
    total_assigned = sum(1 for w in reg["workers"].values() if w["session"])
    print(f"Workers assigned: {total_assigned}/{len(reg['workers'])}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "spawn":
        session_id = sys.argv[2] if len(sys.argv) > 2 else f"session-{int(time.time())}"
        worker_count = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        cmd_spawn(session_id, worker_count)
    elif cmd == "assign":
        cmd_assign(sys.argv[2], sys.argv[3])
    elif cmd == "release":
        cmd_release(sys.argv[2], sys.argv[3])
    elif cmd == "list":
        cmd_list()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()