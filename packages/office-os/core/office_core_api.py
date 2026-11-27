#!/usr/bin/env python3
"""
Office core API - the small read-only status API the office HUD expects on :8080.

Serves (all GET, JSON, 127.0.0.1 only):
  /health    service status
  /agents    agents from config/office.json (agent_tiers + department leads)
  /models    provider routes from config/office.json (provider_pools)
  /launchd   com.aryan.* launchd jobs and whether each is loaded
  /tasks     task files from office-os tasks/

Rules:
  * Read-only. Nothing is written, started, stopped or sent anywhere.
  * Stdlib only. Every read is wrapped: a bad file shows as an error field, never a crash.
  * Binds to localhost only.
"""
import json
import os
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("OFFICE_OS_ROOT", str(Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))))))
CONFIG = ROOT / "config" / "office.json"
TASKS = ROOT / "tasks"
HOST = "127.0.0.1"
PORT = int(os.environ.get("OFFICE_CORE_PORT", "8080"))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _config():
    try:
        return json.loads(CONFIG.read_text()), None
    except (OSError, ValueError) as e:
        return {}, f"{type(e).__name__}: {str(e)[:120]}"


def health():
    cfg, err = _config()
    return {"status": "ok" if not err else "degraded", "checked_at": _now(),
            "config_error": err, "root": str(ROOT)}


def agents():
    cfg, err = _config()
    ids = []
    for tier_ids in (cfg.get("agent_tiers") or {}).values():
        if isinstance(tier_ids, list):
            ids.extend(tier_ids)
    for dept in cfg.get("departments") or []:
        if isinstance(dept, dict):
            ids.extend(dept.get("leads") or [])
    seen, out = set(), []
    for a in ids:
        if isinstance(a, str) and a not in seen:
            seen.add(a)
            out.append({"id": a, "enabled": True})
    return {"agents": out, "error": err}


def models():
    cfg, err = _config()
    routes = []
    for pool, spec in (cfg.get("provider_pools") or {}).items():
        if not isinstance(spec, dict):
            continue
        for m in spec.get("models") or []:
            routes.append({"pool": pool, "model": m, "provider": spec.get("provider"),
                           "enabled": True})
    return {"routes": routes, "error": err}


def launchd():
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"jobs": [], "error": f"launchctl: {type(e).__name__}"}
    jobs = []
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3 or not parts[2].startswith("com.aryan."):
            continue
        jobs.append({"label": parts[2], "pid": None if parts[0].strip() == "-" else parts[0].strip(),
                     "last_exit": parts[1].strip(), "enabled": True})
    return {"jobs": jobs, "error": None}


def tasks():
    out, errors = [], []
    try:
        files = sorted(TASKS.glob("*.json"))
    except OSError as e:
        return {"tasks": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}
    for f in files:
        try:
            t = json.loads(f.read_text())
            out.append({"id": t.get("id", f.stem), "status": t.get("status", "unknown"),
                        "title": t.get("title"), "agent_id": t.get("agent_id")})
        except (OSError, ValueError) as e:
            errors.append(f"{f.name}: {type(e).__name__}")
    return {"tasks": out, "errors": errors[:20], "error": None}


ROUTES = {"/health": health, "/agents": agents, "/models": models,
          "/launchd": launchd, "/tasks": tasks}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        fn = ROUTES.get(path)
        if fn is None:
            body, code = {"error": "not found"}, 404
        else:
            try:
                body, code = fn(), 200
            except Exception as e:  # never leak a traceback to the HUD
                body, code = {"error": f"{type(e).__name__}"}, 500
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):  # noqa: A002 - matches base class signature
        return


def main():
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
