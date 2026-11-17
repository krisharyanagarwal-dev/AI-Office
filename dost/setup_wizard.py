"""
Setup wizard for THE CLAUDE COMPANY (dost).

Walks a first-time operator through provisioning a workspace:
  welcome -> check dependencies -> configure office.json
  -> create workspace -> create admin user -> configure provider keys
  -> test connection

All steps are safe to run non-interactively (defaults are used when
``interactive`` is False) and every step is recorded in the returned setup
record so progress can be resumed or audited later.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # workspace.py lives next to this module
    from workspace import add_user, create_workspace
except Exception:  # pragma: no cover - fallback when imported standalone
    add_user = None  # type: ignore[assignment]
    create_workspace = None  # type: ignore[assignment]

SETUP_DIR = Path(os.path.expanduser("~/.openclaw/setup"))
SETUP_DIR.mkdir(parents=True, exist_ok=True)

OFFICE_CONFIG_DEFAULT = Path(
    "/Users/aryanagarwal/AI-Office/packages/office-os/config/office.json"
)
DEFAULT_WORKSPACE_NAME = "Default Workspace"
DISPATCHER_METRICS_URL = "http://127.0.0.1:8083/metrics"

REQUIRED_TOOLS = ["python3", "curl"]
OPTIONAL_TOOLS = ["jq", "git"]

WELCOME_BANNER = """
=======================================================================
  Welcome to THE CLAUDE COMPANY setup wizard
=======================================================================

This wizard will provision your office workspace in a few steps:

  1. Welcome
  2. Check dependencies (python3, curl, jq, git)
  3. Configure office.json
  4. Create workspace
  5. Create admin user
  6. Configure provider keys
  7. Test connection to the dispatcher

Nothing is destructive. Re-running the wizard is safe.
"""


def check_dependencies() -> dict:
    """Check if the tools the office needs are installed.

    Required tools: python3, curl
    Optional tools: jq, git (flagged as missing but do not fail setup)

    Returns:
        {"all_installed": bool, "missing": [...]}
    """
    all_tools = list(REQUIRED_TOOLS) + list(OPTIONAL_TOOLS)
    missing = [tool for tool in all_tools if shutil.which(tool) is None]
    required_missing = [tool for tool in missing if tool in REQUIRED_TOOLS]
    return {
        "all_installed": len(required_missing) == 0,
        "missing": missing,
    }


def generate_config_file(
    path: str, workspace_id: str, owner_email: str
) -> str:
    """Generate an office.json config file for a workspace.

    Writes provider pools, agent tiers, autonomy rules and the workspace
    ownership into ``path`` and returns the path to the created file.
    """
    config: Dict[str, Any] = {
        "workspace_id": workspace_id,
        "owner_email": owner_email,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider_pools": {
            "groq": {
                "enabled": False,
                "api_key_env": "GROQ_API_KEY",
                "base_url": "https://api.groq.com/openai/v1",
                "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
                "tier": "fast",
            },
            "nvidia": {
                "enabled": False,
                "api_key_env": "NVIDIA_API_KEY",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "models": ["mistralai/mistral-large-4-1t-a52b"],
                "tier": "smart",
            },
            "ollama": {
                "enabled": False,
                "api_key_env": "OLLAMA_API_KEY",
                "base_url": "http://127.0.0.1:11434/v1",
                "models": [],
                "tier": "local",
            },
        },
        "agent_tiers": {
            "fast": ["researcher", "summarizer", "draft_writer"],
            "smart": ["architect", "reviewer", "planner"],
        },
        "autonomy": {
            "require_approval_for": ["delete", "deploy", "spend"],
            "forbidden_path_patterns": ["/etc/", "/root/", "~/.ssh/"],
        },
    }

    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return str(config_path)


def create_default_workspace(name: str, owner_email: str) -> dict:
    """Create the default workspace and make ``owner_email`` its admin.

    Delegates to ``workspace.create_workspace`` when available so the
    workspace lands in the same store the rest of dost uses
    (``~/.openclaw/workspaces``).

    Returns:
        {"workspace_id": ..., "workspace_name": ..., "owner_email": ...}
    """
    if create_workspace is not None:
        meta = create_workspace(name=name, owner_email=owner_email)
        return {
            "workspace_id": meta["id"],
            "workspace_name": meta["name"],
            "owner_email": meta["owner_email"],
        }

    # Standalone fallback: build the workspace directory directly.
    workspace_id = f"ws-{uuid.uuid4().hex[:8]}"
    ws_path = Path(os.path.expanduser("~/.openclaw/workspaces")) / workspace_id
    ws_path.mkdir(parents=True, exist_ok=True)
    for sub in ("tasks", "findings", "pnl", "briefings", "exports"):
        (ws_path / sub).mkdir(exist_ok=True)
    meta = {
        "id": workspace_id,
        "name": name,
        "owner_email": owner_email,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {},
        "active": True,
    }
    with open(ws_path / "workspace.json", "w") as f:
        json.dump(meta, f, indent=2)
    return {
        "workspace_id": workspace_id,
        "workspace_name": name,
        "owner_email": owner_email,
    }


def test_connection() -> dict:
    """Test connectivity to the dispatcher metrics endpoint.

    Tries ``http://127.0.0.1:8083/metrics`` and reports whether it is
    reachable, how long it took, and whether Prometheus-style metrics are
    available in the response.

    Returns:
        {"reachable": bool, "response_time_ms": int, "metrics_available": bool}
    """
    import time as _time

    start = _time.time()
    reachable = False
    metrics_available = False
    try:
        with urllib.request.urlopen(DISPATCHER_METRICS_URL, timeout=5) as response:
            reachable = response.status == 200
            body = response.read(4096).decode("utf-8", errors="replace")
            metrics_available = reachable and (
                "# HELP" in body or "# TYPE" in body or "promhttp" in body.lower()
            )
    except Exception:
        reachable = False
    response_time_ms = int((_time.time() - start) * 1000)
    return {
        "reachable": reachable,
        "response_time_ms": response_time_ms,
        "metrics_available": metrics_available,
    }


def _prompt(message: str, default: Optional[str] = None) -> str:
    """Prompt the user for input, returning ``default`` on empty input."""
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{message}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def run_setup_wizard(interactive: bool = True) -> dict:
    """Run the office setup wizard.

    Steps (each appended to ``steps_completed`` as it finishes):
      welcome, check_dependencies, configure_office_json,
      create_workspace, create_admin_user, configure_provider_keys,
      test_connection

    Returns:
        {
          "setup_id": str,
          "status": "completed",
          "steps_completed": [str, ...],
          "workspace_id": str,
          "user_email": str,
        }
    """
    setup_id = f"setup-{uuid.uuid4().hex[:8]}"
    steps_completed: List[str] = []

    # 1. Welcome
    if interactive:
        print(WELCOME_BANNER)
    steps_completed.append("welcome")

    # 2. Check dependencies
    deps = check_dependencies()
    steps_completed.append("check_dependencies")
    if not deps["all_installed"]:
        missing = ", ".join(deps["missing"])
        if interactive:
            print(
                f"[setup] Missing dependencies: {missing}\n"
                "[setup] Install them and re-run, or continue with limited features."
            )

    # 3. Configure office.json
    default_config_path = str(
        Path(os.path.expanduser("~/.openclaw/setup")) / "office.json"
    )
    config_path = default_config_path
    if interactive:
        config_path = _prompt("office.json config path", default_config_path)
    steps_completed.append("configure_office_json")

    # 4. Create workspace
    workspace_name = DEFAULT_WORKSPACE_NAME
    owner_email = "admin@default.local"
    if interactive:
        workspace_name = _prompt("Workspace name", DEFAULT_WORKSPACE_NAME)
        owner_email = _prompt("Owner (admin) email", "admin@default.local")
    workspace = create_default_workspace(workspace_name, owner_email)
    workspace_id = workspace["workspace_id"]
    steps_completed.append("create_workspace")

    # 5. Create admin user
    if add_user is not None:
        try:
            add_user(workspace_id, owner_email, role="admin")
        except Exception:
            pass  # workspace.create_workspace already added the owner as admin
    steps_completed.append("create_admin_user")

    # 6. Configure provider keys (non-destructive: only records intent)
    provider_keys: Dict[str, str] = {}
    if interactive:
        print("[setup] Provider keys (press Enter to skip each):")
        for provider in ("groq", "nvidia", "ollama"):
            key = _prompt(f"{provider.upper()} API key", "")
            if key:
                provider_keys[provider] = key
    steps_completed.append("configure_provider_keys")

    # 7. Generate office.json with the collected values
    generate_config_file(config_path, workspace_id, owner_email)

    # 7b / final. Test connection to the dispatcher
    connection = test_connection()
    steps_completed.append("test_connection")

    # Persist a setup record so the run can be audited/resumed.
    record = {
        "setup_id": setup_id,
        "status": "completed",
        "steps_completed": steps_completed,
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "user_email": owner_email,
        "config_path": config_path,
        "dependencies": deps,
        "connection": connection,
        "provider_keys_configured": list(provider_keys.keys()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    record_path = SETUP_DIR / f"{setup_id}.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")

    return {
        "setup_id": setup_id,
        "status": "completed",
        "steps_completed": steps_completed,
        "workspace_id": workspace_id,
        "user_email": owner_email,
    }


if __name__ == "__main__":  # pragma: no cover - manual execution
    result = run_setup_wizard(interactive=True)
    print(json.dumps(result, indent=2))
