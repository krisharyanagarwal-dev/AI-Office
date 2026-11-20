#!/usr/bin/env python3
"""
Seed office-core database with current active agents, model routes, and launchd jobs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import (
    upsert_agent, upsert_model_route, upsert_launchd_job,
    init_db
)

def seed_agents():
    """Seed agent registry from current active launchd jobs."""
    agents = [
        {
            "name": "audit",
            "type": "script",
            "model": "none",
            "tools": ["bash", "git", "curl"],
            "policy": {"timeout": 300, "max_memory_mb": 512},
            "launchd_label": "com.aryan.audit",
            "schedule": "@hourly",
            "enabled": True
        },
        {
            "name": "ollama-tunnel",
            "type": "bridge",
            "model": "none",
            "tools": ["ssh"],
            "policy": {"timeout": 0, "restart": "always"},
            "launchd_label": "com.aryan.ollama-tunnel",
            "enabled": True
        },
        {
            "name": "ai-office-fwd",
            "type": "bridge",
            "model": "none",
            "tools": ["ssh"],
            "policy": {"timeout": 0, "restart": "always"},
            "launchd_label": "com.aryan.ai-office-fwd",
            "enabled": True
        },
        {
            "name": "mini-dash-fwd",
            "type": "bridge",
            "model": "none",
            "tools": ["ssh"],
            "policy": {"timeout": 0, "restart": "always"},
            "launchd_label": "com.aryan.mini-dash-fwd",
            "enabled": True
        },
        {
            "name": "mini-services-fwd",
            "type": "bridge",
            "model": "none",
            "tools": ["ssh"],
            "policy": {"timeout": 0, "restart": "always"},
            "launchd_label": "com.aryan.mini-services-fwd",
            "enabled": True
        },
        {
            "name": "uacc-fwd8601",
            "type": "bridge",
            "model": "none",
            "tools": ["python", "ssh"],
            "policy": {"timeout": 0, "restart": "always"},
            "launchd_label": "com.aryan.uacc-fwd8601",
            "enabled": True
        },
        {
            "name": "algo-reference-health",
            "type": "monitor",
            "model": "none",
            "tools": ["python", "http"],
            "policy": {"timeout": 60},
            "launchd_label": "com.aryan.algo-reference-health",
            "schedule": "@hourly",
            "enabled": True
        },
        {
            "name": "codex-model-health",
            "type": "monitor",
            "model": "none",
            "tools": ["python", "http"],
            "policy": {"timeout": 120},
            "launchd_label": "com.aryan.codex-model-health",
            "schedule": "@hourly",
            "enabled": True
        },
        {
            "name": "codex-model-matrix",
            "type": "monitor",
            "model": "none",
            "tools": ["python", "http"],
            "policy": {"timeout": 3600},
            "launchd_label": "com.aryan.codex-model-matrix",
            "schedule": "0 5 * * 0",  # Weekly Sunday 5:17
            "enabled": True
        },
        {
            "name": "fleet-console-server",
            "type": "daemon",
            "model": "none",
            "tools": ["node", "http"],
            "policy": {"timeout": 0, "restart": "always"},
            "launchd_label": "com.aryan.fleet-console-server",
            "enabled": True
        },
        {
            "name": "fleet-console-snapshot",
            "type": "script",
            "model": "none",
            "tools": ["node"],
            "policy": {"timeout": 300},
            "launchd_label": "com.aryan.fleet-console-snapshot",
            "enabled": True
        },
        {
            "name": "opencode-caffeinate",
            "type": "daemon",
            "model": "none",
            "tools": ["caffeinate"],
            "policy": {"timeout": 0},
            "launchd_label": "com.aryan.opencode-caffeinate",
            "enabled": True
        },
    ]
    
    for agent in agents:
        upsert_agent(**agent)
        print(f"Seeded agent: {agent['name']}")

def seed_model_routes():
    """Seed model router from model-router.yaml."""
    import yaml
    
    config_path = Path.home() / "AI-Office" / "packages" / "office-core" / "model-router.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    for backend in config.get("backends", []):
        upsert_model_route(
            name=backend["name"],
            backend=backend["type"],
            endpoint=backend["endpoint"],
            models=backend.get("models", []),
            priority=backend.get("priority", 0),
            enabled=backend.get("enabled", True),
            config=backend.get("config", {})
        )
        print(f"Seeded model route: {backend['name']}")

def seed_launchd_jobs():
    """Seed launchd jobs from current active plists."""
    jobs = [
        {
            "label": "com.aryan.audit",
            "agent_name": "audit",
            "program": ["/bin/bash", "/Users/aryanagarwal/AI-Office/audit/audit.sh"],
            "working_directory": "/Users/aryanagarwal/AI-Office/audit",
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/com.aryan.audit.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/com.aryan.audit.err.log",
            "start_calendar_interval": {"Minute": 0},
            "run_at_load": True,
            "keep_alive": False,
            "throttle_interval": 10,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.ollama-tunnel",
            "agent_name": "ollama-tunnel",
            "program": [
                "/usr/bin/ssh", "-N",
                "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-L", "11434:127.0.0.1:11434",
                "a@macmini"
            ],
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/ollama-tunnel.out.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/ollama-tunnel.err.log",
            "run_at_load": True,
            "keep_alive": True,
            "throttle_interval": 15,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.ai-office-fwd",
            "agent_name": "ai-office-fwd",
            "program": [
                "/usr/bin/ssh", "-N",
                "-o", "BatchMode=yes",
                "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-L", "8000:127.0.0.1:8003",
                "-L", "8001:127.0.0.1:8001",
                "a@macmini"
            ],
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/ai-office-fwd.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/ai-office-fwd.log",
            "run_at_load": True,
            "keep_alive": True,
            "throttle_interval": 30,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.mini-dash-fwd",
            "agent_name": "mini-dash-fwd",
            "program": [
                "/usr/bin/ssh", "-N",
                "-o", "BatchMode=yes",
                "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-L", "14096:127.0.0.1:4096",
                "-L", "14766:127.0.0.1:4766",
                "-L", "18099:127.0.0.1:8099",
                "-L", "18600:127.0.0.1:8600",
                "-L", "8765:127.0.0.1:8765",
                "a@macmini"
            ],
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/mini-dash-fwd.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/mini-dash-fwd.log",
            "run_at_load": True,
            "keep_alive": True,
            "throttle_interval": 30,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.mini-services-fwd",
            "agent_name": "mini-services-fwd",
            "program": [
                "/usr/bin/ssh", "-N",
                "-o", "BatchMode=yes",
                "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-L", "4750:127.0.0.1:4750",
                "-L", "3003:127.0.0.1:3003",
                "-L", "4748:127.0.0.1:4747",
                "-L", "19593:127.0.0.1:19593",
                "-L", "4950:127.0.0.1:4950",
                "-R", "14747:127.0.0.1:4747",
                "a@macmini"
            ],
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/mini-services-fwd.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/mini-services-fwd.log",
            "run_at_load": True,
            "keep_alive": True,
            "throttle_interval": 30,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.uacc-fwd8601",
            "agent_name": "uacc-fwd8601",
            "program": ["/usr/local/bin/python3", "/Users/aryanagarwal/.local/bin/uacc-fwd8601.py"],
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/uacc-fwd8601.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/uacc-fwd8601.log",
            "run_at_load": True,
            "keep_alive": True,
            "throttle_interval": 30,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.algo-reference-health",
            "agent_name": "algo-reference-health",
            "program": [
                "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
                "/Users/aryanagarwal/.claude/skills/algo-reference/guardian.py"
            ],
            "working_directory": "/Users/aryanagarwal/.claude/skills/algo-reference",
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/algo-reference-health.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/algo-reference-health.log",
            "start_calendar_interval": {"Minute": 0},
            "run_at_load": True,
            "keep_alive": False,
            "throttle_interval": 10,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.codex-model-health",
            "agent_name": "codex-model-health",
            "program": [
                "/Users/aryanagarwal/.venvs/openalice/bin/python",
                "-u",
                "/Users/aryanagarwal/.codex/local-harness/health_probe.py"
            ],
            "working_directory": "/Users/aryanagarwal/.codex/local-harness",
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/codex-model-health.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/codex-model-health.log",
            "start_calendar_interval": {"Minute": 0},
            "run_at_load": True,
            "keep_alive": False,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.codex-model-matrix",
            "agent_name": "codex-model-matrix",
            "program": ["/Users/aryanagarwal/.codex/local-harness/run-weekly-reverify.sh"],
            "working_directory": "/Users/aryanagarwal/.codex/local-harness",
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/codex-model-matrix.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/codex-model-matrix.log",
            "start_calendar_interval": {"Weekday": 0, "Hour": 5, "Minute": 17},
            "run_at_load": False,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.fleet-console-server",
            "agent_name": "fleet-console-server",
            "program": [
                "/Users/aryanagarwal/.nvm/versions/node/v22.22.3/bin/node",
                "/Users/aryanagarwal/Documents/Qoder/2026-10-17/d3d68c94/dev/serve-local.mjs"
            ],
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/fleet-console-server.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/fleet-console-server.err.log",
            "run_at_load": True,
            "keep_alive": True,
            "throttle_interval": 30,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.fleet-console-snapshot",
            "agent_name": "fleet-console-snapshot",
            "program": [
                "/Users/aryanagarwal/.nvm/versions/node/v22.22.3/bin/node",
                "/Users/aryanagarwal/Documents/Qoder/2026-10-17/d3d68c94/scripts/collect-snapshot.mjs"
            ],
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/fleet-console-snapshot.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/fleet-console-snapshot.err.log",
            "run_at_load": True,
            "keep_alive": True,
            "throttle_interval": 30,
            "process_type": "Background",
            "enabled": True
        },
        {
            "label": "com.aryan.opencode-caffeinate",
            "agent_name": "opencode-caffeinate",
            "program": ["/usr/bin/caffeinate", "-i"],
            "standard_out_path": "/Users/aryanagarwal/Library/Logs/opencode-caffeinate.log",
            "standard_error_path": "/Users/aryanagarwal/Library/Logs/opencode-caffeinate.err.log",
            "run_at_load": True,
            "keep_alive": True,
            "throttle_interval": 30,
            "process_type": "Background",
            "enabled": True
        },
    ]
    
    for job in jobs:
        upsert_launchd_job(**job)
        print(f"Seeded launchd job: {job['label']}")

if __name__ == "__main__":
    init_db()
    print("=== Seeding agents ===")
    seed_agents()
    print("\n=== Seeding model routes ===")
    seed_model_routes()
    print("\n=== Seeding launchd jobs ===")
    seed_launchd_jobs()
    print("\n=== Done ===")