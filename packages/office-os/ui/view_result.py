#!/usr/bin/env python3
"""View a specific task result in full. User-based: only your own tasks."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/aryanagarwal/office-os")
from core.hive import Hive

if len(sys.argv) < 2:
    print("Usage: python3 ui/view_result.py <task_id> [user_id]")
    sys.exit(1)

task_id = sys.argv[1]
user_id = sys.argv[2] if len(sys.argv) > 2 else None

hive = Hive()
task = hive.get_task(task_id, user_id=user_id)

if not task:
    print(f"Task {task_id} not found or not accessible by user '{user_id or 'anonymous'}'.")
    sys.exit(1)

print("=" * 78)
print(f"  TASK: {task['id']}")
print("=" * 78)
print(f"  Title:    {task['title']}")
print(f"  Agent:    {task.get('agent_id', 'unassigned')}")
print(f"  User:     {task.get('user_id', '?')}")
print(f"  Status:   {task['status']}")
print(f"  Priority: {task.get('priority', 'normal')}")
print(f"  Pool:     {task.get('assigned_pool', '-')}")
print(f"  Model:    {task.get('assigned_model', '-')}")
print(f"  Created:  {task.get('created_at', '-')}")
print(f"  Updated:  {task.get('updated_at', '-')}")
print("-" * 78)

if task.get("error"):
    print("  ERROR:")
    print(f"  {task['error']}")
    print("-" * 78)

if task.get("result"):
    print("  RESULT:")
    print(task["result"])
    print("-" * 78)

print()
