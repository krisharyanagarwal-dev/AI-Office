#!/usr/bin/env python3
"""
office-core CLI
Unified command interface for the office system.
"""

import sys
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent))
from db import (
    create_task, get_task, update_task, list_tasks, delete_task,
    upsert_agent, get_agent, list_agents, delete_agent,
    upsert_model_route, get_model_route, list_model_routes,
    upsert_launchd_job, get_launchd_job, list_launchd_jobs,
    set_state, get_state, init_db,
    log_event
)

def cmd_tasks(args):
    """Task management commands."""
    sub = args.task_cmd
    
    if sub == "create":
        task_id = args.id or str(uuid.uuid4())[:8]
        create_task(
            id=task_id,
            title=args.title,
            description=args.desc or "",
            priority=args.priority,
            assignee=args.assignee,
            source=args.source,
            tags=args.tags or "",
            depends_on=args.depends.split(",") if args.depends else None
        )
        print(f"Created task: {task_id}")
        return task_id
    
    elif sub == "get":
        task = get_task(args.id)
        if task:
            print(json.dumps(task, indent=2, default=str))
        else:
            print(f"Task not found: {args.id}")
    
    elif sub == "update":
        updates = {}
        if args.title: updates["title"] = args.title
        if args.desc: updates["description"] = args.desc
        if args.status: updates["status"] = args.status
        if args.priority is not None: updates["priority"] = args.priority
        if args.assignee: updates["assignee"] = args.assignee
        if args.tags: updates["tags"] = args.tags
        if args.depends: updates["depends_on"] = args.depends.split(",")
        if update_task(args.id, **updates):
            print(f"Updated task: {args.id}")
        else:
            print(f"Task not found or no changes: {args.id}")
    
    elif sub == "list":
        tasks = list_tasks(
            status=args.status,
            assignee=args.assignee,
            source=args.source,
            limit=args.limit
        )
        for t in tasks:
            deps = f" [{t['depends_on']}]" if t['depends_on'] and t['depends_on'] != '[]' else ""
            print(f"  {t['id']:12} | {t['status']:12} | {t['priority']:3} | {t['assignee'] or '-':15} | {t['title'][:60]}{deps}")
    
    elif sub == "delete":
        if delete_task(args.id):
            print(f"Deleted task: {args.id}")
        else:
            print(f"Task not found: {args.id}")

def cmd_agents(args):
    """Agent management commands."""
    sub = args.agent_cmd
    
    if sub == "create":
        upsert_agent(
            name=args.name,
            type=args.type,
            model=args.model,
            tools=args.tools.split(",") if args.tools else [],
            policy=json.loads(args.policy) if args.policy else None,
            launchd_label=args.launchd_label,
            health_endpoint=args.health_endpoint,
            schedule=args.schedule,
            enabled=not args.disabled
        )
        print(f"Created agent: {args.name}")
    
    elif sub == "get":
        agent = get_agent(args.name)
        if agent:
            print(json.dumps(agent, indent=2, default=str))
        else:
            print(f"Agent not found: {args.name}")
    
    elif sub == "list":
        agents = list_agents(enabled_only=args.enabled_only)
        for a in agents:
            print(f"  {a['name']:30} | {a['type']:10} | {a['model'] or '-':40} | {'enabled' if a['enabled'] else 'disabled'}")
    
    elif sub == "delete":
        if delete_agent(args.name):
            print(f"Deleted agent: {args.name}")
        else:
            print(f"Agent not found: {args.name}")

def cmd_models(args):
    """Model router commands."""
    sub = args.model_cmd
    
    if sub == "add":
        upsert_model_route(
            name=args.name,
            backend=args.backend,
            endpoint=args.endpoint,
            models=args.models.split(",") if args.models else [],
            priority=args.priority,
            enabled=not args.disabled,
            config=json.loads(args.config) if args.config else None
        )
        print(f"Added model route: {args.name}")
    
    elif sub == "list":
        routes = list_model_routes(enabled_only=args.enabled_only)
        for r in routes:
            models = json.loads(r["models"]) if r["models"] else []
            print(f"  {r['name']:20} | {r['backend']:12} | {r['endpoint']:30} | {r['priority']:3} | {len(models)} models | {'on' if r['enabled'] else 'off'}")

def cmd_launchd(args):
    """Launchd management commands."""
    sub = args.launchd_cmd
    
    if sub == "generate":
        from scripts.generate_launchd import generate_all
        generate_all(deploy=args.deploy)
    
    elif sub == "sync-agents":
        from scripts.generate_launchd import sync_from_agents
        sync_from_agents()
    
    elif sub == "list":
        jobs = list_launchd_jobs(enabled_only=args.enabled_only)
        for j in jobs:
            print(f"  {j['label']:40} | {j['agent_name']:20} | {'on' if j['enabled'] else 'off'}")

def cmd_migrate(args):
    """Migration commands."""
    sub = args.migrate_cmd
    repo = Path(__file__).resolve().parent.parent

    def migrate_tree(source_root: Path, source_label: str) -> int:
        if not source_root.exists():
            print(f"Migration source not found: {source_root}")
            return 0
        count = 0
        skipped = 0
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or path.suffix not in (".json", ".md", ".txt"):
                continue
            rel = str(path.relative_to(source_root))
            task_id = "mig" + hashlib.sha1(f"{source_label}:{rel}".encode()).hexdigest()[:12]
            if get_task(task_id):
                skipped += 1
                continue
            try:
                content = path.read_text(errors="replace")
                create_task(
                    id=task_id,
                    title=path.name,
                    description=content[:500],
                    source=f"{source_label}-migration",
                    metadata={"original_path": str(path), "relative_path": rel}
                )
                count += 1
            except Exception as e:
                print(f"Failed to migrate {path}: {e}")
        print(f"Migrated {count} tasks from {source_label} ({skipped} already present)")
        return count

    if sub == "office-os-tasks":
        count = migrate_tree(repo / "packages" / "office-os" / "tasks", "office-os")
    elif sub == "office-manager-collect":
        count = migrate_tree(repo / "packages" / "_archive" / "office-manager" / "collect", "office-manager")
    else:
        count = 0
    return count


def cmd_health(args):
    """System health check."""
    print("=== office-core Health ===")
    print(f"DB: {Path.home() / 'AI-Office' / 'office-core' / 'tasks.db'}")
    print(f"Log: {Path.home() / 'AI-Office' / 'office-core' / 'tasks.log'}")
    
    # Count tasks
    tasks = list_tasks()
    by_status = {}
    for t in tasks:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    print(f"Tasks: {len(tasks)} total")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    
    # Agents
    agents = list_agents(enabled_only=True)
    print(f"Agents: {len(agents)} enabled")
    
    # Model routes
    routes = list_model_routes(enabled_only=True)
    print(f"Model routes: {len(routes)} enabled")
    
    # Launchd jobs
    jobs = list_launchd_jobs(enabled_only=True)
    print(f"Launchd jobs: {len(jobs)} enabled")
    
    # Check launchd status
    try:
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        loaded = [line.split("\t")[2] for line in result.stdout.strip().split("\n")[1:] if "com.aryan" in line]
        print(f"Loaded in launchd: {len(loaded)}")
        for l in loaded:
            print(f"  {l}")
    except Exception:
        pass

def main():
    import argparse
    import subprocess
    
    parser = argparse.ArgumentParser(prog="office-core", description="Unified office system CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Tasks
    tasks_parser = subparsers.add_parser("tasks", help="Task management")
    tasks_sub = tasks_parser.add_subparsers(dest="task_cmd", required=True)
    
    t_create = tasks_sub.add_parser("create", help="Create task")
    t_create.add_argument("title")
    t_create.add_argument("--id")
    t_create.add_argument("--desc", default="")
    t_create.add_argument("--priority", type=int, default=0)
    t_create.add_argument("--assignee")
    t_create.add_argument("--source", default="cli")
    t_create.add_argument("--tags", default="")
    t_create.add_argument("--depends", default="")
    
    t_get = tasks_sub.add_parser("get", help="Get task")
    t_get.add_argument("id")
    
    t_update = tasks_sub.add_parser("update", help="Update task")
    t_update.add_argument("id")
    t_update.add_argument("--title")
    t_update.add_argument("--desc")
    t_update.add_argument("--status", choices=["pending", "in_progress", "completed", "failed", "cancelled", "blocked"])
    t_update.add_argument("--priority", type=int)
    t_update.add_argument("--assignee")
    t_update.add_argument("--tags")
    t_update.add_argument("--depends")
    
    t_list = tasks_sub.add_parser("list", help="List tasks")
    t_list.add_argument("--status")
    t_list.add_argument("--assignee")
    t_list.add_argument("--source")
    t_list.add_argument("--limit", type=int, default=50)
    
    t_delete = tasks_sub.add_parser("delete", help="Delete task")
    t_delete.add_argument("id")
    
    # Agents
    agents_parser = subparsers.add_parser("agents", help="Agent management")
    agents_sub = agents_parser.add_subparsers(dest="agent_cmd", required=True)
    
    a_create = agents_sub.add_parser("create", help="Create agent")
    a_create.add_argument("name")
    a_create.add_argument("type", choices=["llm", "script", "daemon", "bridge", "monitor"])
    a_create.add_argument("--model")
    a_create.add_argument("--tools", default="")
    a_create.add_argument("--policy")
    a_create.add_argument("--launchd-label")
    a_create.add_argument("--health-endpoint")
    a_create.add_argument("--schedule")
    a_create.add_argument("--disabled", action="store_true")
    
    a_get = agents_sub.add_parser("get", help="Get agent")
    a_get.add_argument("name")
    
    a_list = agents_sub.add_parser("list", help="List agents")
    a_list.add_argument("--enabled-only", action="store_true")
    
    a_delete = agents_sub.add_parser("delete", help="Delete agent")
    a_delete.add_argument("name")
    
    # Models
    models_parser = subparsers.add_parser("models", help="Model router")
    models_sub = models_parser.add_subparsers(dest="model_cmd", required=True)
    
    m_add = models_sub.add_parser("add", help="Add model route")
    m_add.add_argument("name")
    m_add.add_argument("backend", choices=["mlx", "nim", "free-harness", "ollama", "openai", "anthropic"])
    m_add.add_argument("endpoint")
    m_add.add_argument("--models", default="")
    m_add.add_argument("--priority", type=int, default=0)
    m_add.add_argument("--config")
    m_add.add_argument("--disabled", action="store_true")
    
    m_list = models_sub.add_parser("list", help="List model routes")
    m_list.add_argument("--enabled-only", action="store_true")
    
    # Launchd
    launchd_parser = subparsers.add_parser("launchd", help="Launchd management")
    launchd_sub = launchd_parser.add_subparsers(dest="launchd_cmd", required=True)
    
    l_gen = launchd_sub.add_parser("generate", help="Generate plists")
    l_gen.add_argument("--deploy", action="store_true")
    
    l_sync = launchd_sub.add_parser("sync-agents", help="Sync from agent registry")
    
    l_list = launchd_sub.add_parser("list", help="List launchd jobs")
    l_list.add_argument("--enabled-only", action="store_true")
    
    # Migrate
    migrate_parser = subparsers.add_parser("migrate", help="Migrate from old systems")
    migrate_sub = migrate_parser.add_subparsers(dest="migrate_cmd", required=True)
    
    migrate_sub.add_parser("office-os-tasks", help="Migrate tasks from office-os")
    migrate_sub.add_parser("office-manager-collect", help="Migrate from office-manager/collect")
    
    # Health
    subparsers.add_parser("health", help="System health check")
    
    args = parser.parse_args()
    
    # Initialize DB
    init_db()
    
    # Dispatch
    if args.command == "tasks":
        cmd_tasks(args)
    elif args.command == "agents":
        cmd_agents(args)
    elif args.command == "models":
        cmd_models(args)
    elif args.command == "launchd":
        cmd_launchd(args)
    elif args.command == "migrate":
        cmd_migrate(args)
    elif args.command == "health":
        cmd_health(args)

if __name__ == "__main__":
    main()