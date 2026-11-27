"""
Office OS Dashboard - Terminal office UI using Python stdlib + tmux.
No installs. User-based: each user sees only their own tasks.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os")))))
from core.hive import Hive
from core.router import ProviderRouter

OFFICE_ROOT = (Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))))
HOME = Path.home()
DISPATCHER_LOG = HOME / ".openclaw" / "jev-dispatcher.log"
OFFICE_PNL = HOME / ".openclaw" / "office_pnl.json"


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
    print("  [n] New task    [r] Refresh    [c] Cycle stats    [a] Agent stats    [u] Switch user    [q] Quit")
    print()


def cycle_breakdown():
    """Per-cycle stats from the dispatcher log: done/error/skipped per cycle."""
    print("  CYCLE BREAKDOWN (dispatcher log)")
    print("  " + "-" * 76)
    if not DISPATCHER_LOG.exists():
        print("  (dispatcher log not found)")
        print()
        return

    cycle_re = re.compile(
        r"JEV cycle complete:\s+(\d+)\s+done,\s+(\d+)\s+error,\s+(\d+)\s+skipped"
    )
    cycles = []
    try:
        lines = DISPATCHER_LOG.read_text(errors="replace").splitlines()
    except OSError:
        print("  (could not read dispatcher log)")
        print()
        return

    for ln in lines:
        m = cycle_re.search(ln)
        if m:
            ts = ln[:19]
            cycles.append({
                "ts": ts,
                "done": int(m.group(1)),
                "error": int(m.group(2)),
                "skipped": int(m.group(3)),
            })

    if not cycles:
        print("  (no cycle records yet)")
        print()
        return

    total_done = sum(c["done"] for c in cycles)
    total_error = sum(c["error"] for c in cycles)
    total_skipped = sum(c["skipped"] for c in cycles)
    total_cycles = len(cycles)

    print(f"  Cycles: {total_cycles}  |  Done: {total_done}  Error: {total_error}  Skipped: {total_skipped}")
    if total_done + total_error > 0:
        err_rate = total_error / (total_done + total_error) * 100
        print(f"  Aggregate error rate: {err_rate:.1f}%")
    print("  Last 5 cycles:")
    for c in cycles[-5:]:
        print(f"    {c['ts']}  done={c['done']:3d}  error={c['error']:3d}  skipped={c['skipped']:3d}")
    print()


def per_agent_breakdown():
    """Per-agent cost / value / net from office_pnl.json."""
    print("  PER-AGENT BREAKDOWN (office P&L ledger)")
    print("  " + "-" * 76)
    if not OFFICE_PNL.exists():
        print("  (office P&L ledger not found)")
        print()
        return

    try:
        ledger = json.loads(OFFICE_PNL.read_text())
    except (OSError, json.JSONDecodeError):
        print("  (could not read P&L ledger)")
        print()
        return

    if not isinstance(ledger, list) or not ledger:
        print("  (no agent records yet)")
        print()
        return

    # Compute per-agent aggregates from task ledger
    by_agent = {}
    total_cost = 0
    total_value = 0
    for t in ledger:
        aid = t.get("agent_id", "?")
        cost = t.get("cost_units", 0)
        val = t.get("outcome_value", 0)
        net = val - cost
        tier = t.get("autonomy_tier", "?")
        a = by_agent.setdefault(aid, {"tier": tier, "count": 0, "cost": 0, "value": 0, "net": 0})
        a["count"] += 1
        a["cost"] += cost
        a["value"] += val
        a["net"] += net
        total_cost += cost
        total_value += val

    # Sort by net value descending
    rows = sorted(by_agent.items(), key=lambda kv: kv[1]["net"], reverse=True)
    print(f"  {'Agent':<30} {'Tier':<5} {'Tasks':>6} {'Cost':>6} {'Value':>7} {'Net':>7}")
    for aid, info in rows[:15]:
        print(f"  {aid:<30} {info['tier']:<5} {info['count']:>6} "
              f"{info['cost']:>6} {info['value']:>7} {info['net']:>7}")
    print(f"  {'TOTAL':<30} {'':<5} {len(ledger):>6} "
          f"{total_cost:>6} {total_value:>7} {total_value - total_cost:>7}")
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
        elif choice == "c":
            cycle_breakdown()
            input("  Press Enter to return to dashboard...")
        elif choice == "a":
            per_agent_breakdown()
            input("  Press Enter to return to dashboard...")
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
