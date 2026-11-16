"""
Office OS Dashboard - Terminal office UI using Python stdlib + tmux.
No installs. User-based: each user sees only their own tasks.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/Users/aryanagarwal/office-os")
from core.hive import Hive
from core.router import ProviderRouter

OFFICE_ROOT = Path("/Users/aryanagarwal/office-os")


def load_users():
    with open(OFFICE_ROOT / "config" / "users.json") as f:
        return json.load(f).get("users", {})


def clear():
    os.system("clear")


def header(user_id, users):
    print("=" * 78)
    user = users.get(user_id, {})
    print(f"  OFFICE OS  |  User: {user.get('name', user_id)} ({user.get('role', '?')})  |  Zero Claude Tokens  |  Free Models Only")
    print("=" * 78)
    from datetime import datetime
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def provider_status():
    router = ProviderRouter()
    status = router.status()
    print("  PROVIDER POOLS")
    print("  " + "-" * 76)
    for name, s in status.items():
        mark = "[OK]" if s["available"] else f"[COOLDOWN {s['cooldown_remaining']:.0f}s]"
        models = ", ".join(m.split("/")[-1] for m in s["models"][:2])
        print(f"  {mark}  {name:20s}  tier={s['tier']:12s}  models={models}")
    print()


def task_board(hive, user_id):
    print("  YOUR TASK BOARD")
    print("  " + "-" * 76)

    statuses = ["pending", "assigned", "in_progress", "done", "failed"]
    any_tasks = False
    for status in statuses:
        tasks = hive.list_tasks(status=status, user_id=user_id)
        if tasks:
            any_tasks = True
            status_color = {
                "pending": "PEND",
                "assigned": "ASGN",
                "in_progress": "RUN ",
                "done": "DONE",
                "failed": "FAIL",
            }[status]
            for t in tasks:
                agent = t.get("agent_id", "unassigned")[:20]
                title = t["title"][:45]
                pool = t.get("assigned_pool", "-")[:15]
                print(f"  [{status_color}]  {t['id']:8s}  {agent:20s}  {pool:15s}  {title}")
    if not any_tasks:
        print("  (no tasks yet)")
    print()


def agent_status(hive, user_id):
    print("  AGENT STATUS")
    print("  " + "-" * 76)
    memory_dir = OFFICE_ROOT / "memory"
    agents = {}
    if memory_dir.exists():
        for f in memory_dir.glob("memory_*.jsonl"):
            agent_id = f.stem.replace("memory_", "")
            role = "?"
            st = "?"
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("key") == "role":
                        role = entry.get("value", "?")
                    elif entry.get("key") == "status":
                        st = entry.get("value", "?")
            agents[agent_id] = (role, st)
    if not agents:
        print("  (no agent memory yet)")
    else:
        for aid, (role, st) in sorted(agents.items()):
            print(f"  {aid:25s}  role={role:20s}  state={st}")
    print()


def recent_results(hive, user_id):
    print("  LATEST RESULTS (YOUR TASKS)")
    print("  " + "-" * 76)
    tasks = hive.list_tasks(status="done", user_id=user_id)
    if not tasks:
        print("  (no completed tasks)")
    else:
        for t in tasks[-5:]:
            agent = t.get("agent_id", "?")[:20]
            result = t.get("result") or ""
            preview = result[:60].replace("\n", " ")
            print(f"  {t['id']:8s}  {agent:20s}  {t['title'][:35]:35s}  ...{preview}")
    print()


def inbox_alerts(hive, user_id):
    print("  UNREAD INBOX (YOUR MESSAGES)")
    print("  " + "-" * 76)
    msgs = hive.get_inbox("michael", unread_only=True, user_id=user_id)
    if msgs:
        for m in msgs[-5:]:
            print(f"  {m['id']:8s}  from={m['from']:20s}  {m['subject'][:50]}")
    else:
        print("  (none)")
    print()


def menu():
    print("  COMMANDS")
    print("  " + "-" * 76)
    print("  [n] New task    [r] Refresh    [u] Switch user    [q] Quit")
    print()


def run_dashboard(default_user="aryan"):
    users = load_users()
    current_user = default_user if default_user in users else list(users.keys())[0]

    while True:
        clear()
        hive = Hive()
        header(current_user, users)
        provider_status()
        agent_status(hive, current_user)
        task_board(hive, current_user)
        recent_results(hive, current_user)
        inbox_alerts(hive, current_user)
        menu()

        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            break

        if choice == "q":
            print("  Goodbye.")
            break
        elif choice == "r":
            continue
        elif choice == "u":
            print("  Available users:")
            for uid, u in users.items():
                marker = " (current)" if uid == current_user else ""
                print(f"    {uid} - {u.get('name', uid)} ({u.get('role', '?')}){marker}")
            new_user = input("  Switch to user: ").strip()
            if new_user in users:
                current_user = new_user
            else:
                print("  Invalid user.")
                input("  Press Enter to continue...")
        elif choice == "n":
            create_task_flow(hive, users, current_user)
        else:
            print("  Unknown command. Press Enter to continue.")
            input()


def create_task_flow(hive, users, current_user):
    clear()
    from datetime import datetime
    print(f"  User: {users[current_user].get('name', current_user)}")
    print("  CREATE NEW TASK")
    print("  " + "-" * 76)
    try:
        title = input("  Title: ").strip()
        if not title:
            print("  Cancelled.")
            input()
            return
        desc = input("  Description: ").strip()
        agent = input("  Agent ID (e.g. principal-architect, software-architect): ").strip() or "principal-architect"
        prio = input("  Priority (low/normal/high/critical) [normal]: ").strip() or "normal"
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        input()
        return

    from agents.god_agent import GodAgent
    router = ProviderRouter()
    god = GodAgent(hive, router)
    result = god.create_task(title, desc, agent_id=agent, priority=prio, user_id=current_user)
    print()
    print(f"  Created: {result.get('task_id', '?')}")
    print(f"  Agent: {result.get('agent_id', '?')}")
    print(f"  Pool: {result.get('pool', '?')}")
    print(f"  Model: {result.get('model', '?')}")
    print(f"  User: {current_user}")
    input("\n  Press Enter to return to dashboard...")


if __name__ == "__main__":
    import sys
    default_user = sys.argv[1] if len(sys.argv) > 1 else "aryan"
    run_dashboard(default_user)
