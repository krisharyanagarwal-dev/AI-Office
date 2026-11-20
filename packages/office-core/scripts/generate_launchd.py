#!/usr/bin/env python3
"""
office-core Launchd Generator
Generates launchd plists from agent registry in database.
"""

import os
import sys
import json
import plistlib
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import list_agents, list_launchd_jobs, get_launchd_job

LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"
CORE_LAUNCHD_DIR = Path.home() / "AI-Office" / "office-core" / "launchd"

def ensure_dirs():
    LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)
    CORE_LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)

def generate_plist(job: dict) -> dict:
    """Generate plist dict from job definition."""
    plist = {
        "Label": job["label"],
        "ProgramArguments": json.loads(job["program"]),
        "RunAtLoad": job.get("run_at_load", 1) == 1,
        "KeepAlive": job.get("keep_alive", 1) == 1,
        "ThrottleInterval": job.get("throttle_interval", 30),
        "ProcessType": job.get("process_type", "Background"),
    }
    
    if job.get("working_directory"):
        plist["WorkingDirectory"] = job["working_directory"]
    
    if job.get("environment"):
        plist["EnvironmentVariables"] = json.loads(job["environment"])
    
    if job.get("standard_out_path"):
        plist["StandardOutPath"] = job["standard_out_path"]
    else:
        # Default to Library/Logs
        plist["StandardOutPath"] = str(Path.home() / "Library" / "Logs" / f"{job['label']}.log")
    
    if job.get("standard_error_path"):
        plist["StandardErrorPath"] = job["standard_error_path"]
    else:
        plist["StandardErrorPath"] = str(Path.home() / "Library" / "Logs" / f"{job['label']}.err.log")
    
    if job.get("start_calendar_interval"):
        plist["StartCalendarInterval"] = json.loads(job["start_calendar_interval"])
    
    return plist

def write_plist(label: str, plist: dict, target_dir: Path):
    """Write plist to target directory."""
    file_path = target_dir / f"{label}.plist"
    with open(file_path, "wb") as f:
        plistlib.dump(plist, f)
    return file_path

def deploy_plist(label: str, plist: dict) -> bool:
    """Deploy plist to ~/Library/LaunchAgents and load it."""
    file_path = write_plist(label, plist, LAUNCHD_DIR)
    
    # Unload existing if loaded
    subprocess.run(["launchctl", "unload", "-w", str(file_path)], capture_output=True)
    
    # Load new
    result = subprocess.run(["launchctl", "load", "-w", str(file_path)], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to load {label}: {result.stderr}")
        return False
    return True

def generate_all(deploy: bool = False):
    """Generate all plists from database."""
    ensure_dirs()
    
    jobs = list_launchd_jobs(enabled_only=True)
    print(f"Found {len(jobs)} enabled launchd jobs")
    
    for job in jobs:
        plist = generate_plist(job)
        label = job["label"]
        
        # Write to core directory (version controlled)
        core_path = write_plist(label, plist, CORE_LAUNCHD_DIR)
        print(f"  Generated: {core_path}")
        
        if deploy:
            if deploy_plist(label, plist):
                print(f"  Deployed: {label}")
            else:
                print(f"  Deploy FAILED: {label}")
    
    print(f"\nGenerated {len(jobs)} plists to {CORE_LAUNCHD_DIR}")
    if deploy:
        print("Deployed to ~/Library/LaunchAgents")

def sync_from_agents():
    """Create launchd jobs from agent registry (for agents with launchd_label)."""
    from db import list_agents, upsert_launchd_job
    
    agents = list_agents(enabled_only=True)
    created = 0
    
    for agent in agents:
        label = agent.get("launchd_label")
        if not label:
            continue
        
        # Check if job already exists
        existing = get_launchd_job(label)
        if existing:
            continue
        
        # Build program from agent
        agent_name = agent["name"]
        agent_type = agent["type"]
        
        if agent_type == "llm":
            # LLM agent - runs a Python script
            program = ["/usr/bin/python3", f"/Users/aryanagarwal/AI-Office/office-core/agents/{agent_name}/run.py"]
        elif agent_type == "script":
            program = ["/bin/bash", f"/Users/aryanagarwal/AI-Office/office-core/agents/{agent_name}/run.sh"]
        elif agent_type == "daemon":
            program = ["/usr/bin/python3", f"/Users/aryanagarwal/AI-Office/office-core/agents/{agent_name}/daemon.py"]
        elif agent_type == "bridge":
            program = ["/usr/bin/python3", f"/Users/aryanagarwal/AI-Office/office-core/agents/{agent_name}/bridge.py"]
        elif agent_type == "monitor":
            program = ["/usr/bin/python3", f"/Users/aryanagarwal/AI-Office/office-core/agents/{agent_name}/monitor.py"]
        else:
            program = ["/usr/bin/python3", f"/Users/aryanagarwal/AI-Office/office-core/agents/{agent_name}/main.py"]
        
        # Working directory
        working_dir = f"/Users/aryanagarwal/AI-Office/office-core/agents/{agent_name}"
        
        # Schedule
        schedule = agent.get("schedule")
        start_calendar = None
        if schedule and schedule.startswith("@"):
            # Parse cron-like: @hourly, @daily, @weekly, @monthly, @yearly
            cron_map = {
                "@hourly": {"Minute": 0},
                "@daily": {"Hour": 0, "Minute": 0},
                "@weekly": {"Weekday": 0, "Hour": 0, "Minute": 0},
                "@monthly": {"Day": 1, "Hour": 0, "Minute": 0},
            }
            start_calendar = cron_map.get(schedule)
        elif schedule and " " in schedule:
            # Cron expression: "*/5 * * * *"
            parts = schedule.split()
            if len(parts) == 5:
                start_calendar = {
                    "Minute": parts[0] if parts[0] != "*" else None,
                    "Hour": parts[1] if parts[1] != "*" else None,
                    "Day": parts[2] if parts[2] != "*" else None,
                    "Weekday": parts[4] if parts[4] != "*" else None,
                }
                # Remove None values
                start_calendar = {k: v for k, v in start_calendar.items() if v is not None}
        
        upsert_launchd_job(
            label=label,
            agent_name=agent_name,
            program=program,
            working_directory=working_dir,
            start_calendar_interval=start_calendar,
            standard_out_path=f"/Users/aryanagarwal/Library/Logs/{label}.log",
            standard_error_path=f"/Users/aryanagarwal/Library/Logs/{label}.err.log",
        )
        created += 1
        print(f"Created launchd job for agent: {agent_name} -> {label}")
    
    print(f"Synced {created} new launchd jobs from agents")
    return created

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate launchd plists from office-core DB")
    parser.add_argument("--deploy", action="store_true", help="Deploy to ~/Library/LaunchAgents")
    parser.add_argument("--sync-agents", action="store_true", help="Sync launchd jobs from agent registry")
    args = parser.parse_args()
    
    if args.sync_agents:
        sync_from_agents()
    
    generate_all(deploy=args.deploy)