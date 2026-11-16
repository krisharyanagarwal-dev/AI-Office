"""
CLI for Office OS - create tasks, check status, list agents.
User-based: each task is tagged with a user_id.
"""
import json
import sys

sys.path.insert(0, "/Users/aryanagarwal/office-os")
from core.hive import Hive
from core.router import ProviderRouter
from agents.god_agent import GodAgent


def cmd_status():
    hive = Hive()
    router = ProviderRouter()
    god = GodAgent(hive, router)
    status = god.status()
    print(json.dumps(status, indent=2))


def cmd_task(title, description, agent_id=None, priority="normal", user_id=None):
    hive = Hive()
    router = ProviderRouter()
    god = GodAgent(hive, router)
    result = god.create_task(title, description, agent_id=agent_id, priority=priority, user_id=user_id)
    print(json.dumps(result, indent=2))


def cmd_list_tasks(status=None, agent_id=None, user_id=None):
    hive = Hive()
    tasks = hive.list_tasks(status=status, agent_id=agent_id, user_id=user_id)
    if not tasks:
        print("No tasks found.")
        return
    for t in tasks:
        user = t.get('user_id', '?')
        print(f"{t['id']} [{t['status']}] {t['title']} -> {t.get('agent_id', 'unassigned')} (user: {user})")


def cmd_inbox(agent_id, user_id=None):
    hive = Hive()
    msgs = hive.get_inbox(agent_id, unread_only=True, user_id=user_id)
    if not msgs:
        print("No unread messages.")
        return
    for m in msgs:
        print(f"{m['id']} from {m['from']}: {m['subject']}")
        print(f"  {m['body'][:100]}...")
        print()


def cmd_providers():
    router = ProviderRouter()
    status = router.status()
    for name, s in status.items():
        avail = "AVAILABLE" if s["available"] else f"COOLDOWN ({s['cooldown_remaining']:.0f}s)"
        print(f"{name}: {avail} (tier={s['tier']})")


def cmd_users():
    import json as _json
    with open("/Users/aryanagarwal/office-os/config/users.json") as f:
        cfg = _json.load(f)
    for uid, u in cfg.get("users", {}).items():
        print(f"{uid}: {u.get('name', uid)} (role: {u.get('role', '?')})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: cli.py <command> [args]")
        print("  status")
        print("  task <title> <description> [agent_id] [priority] [user_id]")
        print("  list-tasks [status] [agent_id] [user_id]")
        print("  inbox <agent_id> [user_id]")
        print("  providers")
        print("  users")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "status":
        cmd_status()
    elif cmd == "task":
        title = sys.argv[2] if len(sys.argv) > 2 else "Untitled"
        desc = sys.argv[3] if len(sys.argv) > 3 else ""
        agent = sys.argv[4] if len(sys.argv) > 4 else None
        prio = sys.argv[5] if len(sys.argv) > 5 else "normal"
        user = sys.argv[6] if len(sys.argv) > 6 else None
        cmd_task(title, desc, agent_id=agent, priority=prio, user_id=user)
    elif cmd == "list-tasks":
        # Parse optional flags: --user <id>, --agent <id>, --status <status>
        args = sys.argv[2:]
        status = None
        agent = None
        user = None
        i = 0
        while i < len(args):
            if args[i] == "--user" and i + 1 < len(args):
                user = args[i + 1]
                i += 2
            elif args[i] == "--agent" and i + 1 < len(args):
                agent = args[i + 1]
                i += 2
            elif args[i] == "--status" and i + 1 < len(args):
                status = args[i + 1]
                i += 2
            else:
                i += 1
        cmd_list_tasks(status=status, agent_id=agent, user_id=user)
    elif cmd == "inbox":
        args = sys.argv[2:]
        agent_id = "michael"
        user = None
        i = 0
        while i < len(args):
            if args[i] == "--user" and i + 1 < len(args):
                user = args[i + 1]
                i += 2
            elif args[i] == "--agent" and i + 1 < len(args):
                agent_id = args[i + 1]
                i += 2
            else:
                i += 1
        cmd_inbox(agent_id, user_id=user)
    elif cmd == "providers":
        cmd_providers()
    elif cmd == "users":
        cmd_users()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
