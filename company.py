#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Unified Launcher

One entry point for everything:
  python company.py dispatch "task description" [--department X]
  python company.py upgrade --list | --test | --rules
  python company.py pnl
  python company.py metrics
  python company.py status
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

COMPANY_DIR = Path(__file__).resolve().parent
DISPATCHER = COMPANY_DIR / "company_dispatcher.py"


def _fmt_money(v) -> str:
    """Format a large market-cap number with commas; '—' if missing."""
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"
UPGRADE = COMPANY_DIR / "upgrade_system.py"
DOST = COMPANY_DIR / "dost.py"
STOCKS_BOT = COMPANY_DIR / "scripts" / "all_stocks_bot.py"
STOCKS_METRICS_FILE = (Path.home() / ".openclaw" / "stocks_metrics.json")
PNL_FILE = (Path.home() / ".openclaw" / "office_pnl.json")
METRICS_URL = "http://127.0.0.1:8083/metrics"
OFFICE_OS_PATH = Path.home() / "AI-Office" / "packages" / "office-os"
SESSION_PATH = OFFICE_OS_PATH / "session"
SHARED_PATH = OFFICE_OS_PATH.parent / "shared"


def cmd_dispatch(task: str, department: str | None) -> None:
    import subprocess
    cmd = [sys.executable, str(DISPATCHER), task]
    if department:
        cmd += ["--department", department]
    subprocess.run(cmd)


def cmd_dost(message: str | None, department: str | None, briefing: bool,
             push_telegram: bool, memory: bool, context: bool, health: bool) -> None:
    cmd = [sys.executable, str(DOST)]
    if briefing:
        cmd.append("--briefing")
    elif push_telegram:
        cmd.append("--push-telegram")
    elif memory:
        cmd.append("--memory")
    elif context:
        cmd.append("--context")
    elif health:
        cmd.append("--health")
    elif message:
        cmd.append(message)
    if department:
        cmd += ["--department", department]
    subprocess.run(cmd)


def cmd_upgrade(args) -> None:
    cmd = [sys.executable, str(UPGRADE)]
    if args.list:
        cmd.append("--list")
    elif args.test:
        cmd.append("--test")
    elif args.rules:
        cmd.append("--rules")
    subprocess.run(cmd)


def _pnl_summary() -> dict | None:
    """Totals from the P&L ledger. Returns None when there is no readable ledger."""
    if not PNL_FILE.exists():
        return None
    try:
        rows = json.loads(PNL_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(rows, list):
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    agg = {"entries": len(rows), "cost": 0.0, "outcome": 0.0, "net": 0.0,
           "today_entries": 0, "today_cost": 0.0, "by_status": {}, "by_agent": {}}
    for r in rows:
        if not isinstance(r, dict):
            continue
        cost = float(r.get("cost_units") or 0)
        agg["cost"] += cost
        agg["outcome"] += float(r.get("outcome_value") or 0)
        agg["net"] += float(r.get("net_value") or 0)
        st = str(r.get("status") or "unknown")
        agg["by_status"][st] = agg["by_status"].get(st, 0) + 1
        ag = str(r.get("agent_id") or "unknown")
        a = agg["by_agent"].setdefault(ag, {"n": 0, "cost": 0.0})
        a["n"] += 1
        a["cost"] += cost
        if str(r.get("created_at") or "").startswith(today):
            agg["today_entries"] += 1
            agg["today_cost"] += cost
    return agg


def cmd_pnl(raw: bool = False, limit: int = 10) -> None:
    """Office P&L. Summary by default -- the ledger is tens of thousands of rows,
    and printing it was what made `status` unreadable."""
    if not PNL_FILE.exists():
        print("No P&L ledger found. Run tasks first to generate cost/outcome data.")
        print(f"Expected at: {PNL_FILE}")
        return
    if raw:
        print(PNL_FILE.read_text())
        return
    s = _pnl_summary()
    if s is None:
        print(f"Could not parse the ledger at {PNL_FILE}")
        return
    print(f"Entries: {s['entries']:,}   cost {s['cost']:,.0f}u   "
          f"outcome {s['outcome']:,.0f}   net {s['net']:,.0f}")
    print(f"Today:   {s['today_entries']:,} entries, {s['today_cost']:,.0f}u")
    if s["by_status"]:
        order = sorted(s["by_status"].items(), key=lambda kv: -kv[1])
        print("Status:  " + "  ".join(f"{k}={v:,}" for k, v in order[:6]))
    top = sorted(s["by_agent"].items(), key=lambda kv: -kv[1]["cost"])[:limit]
    if top:
        print(f"Top {len(top)} agents by cost:")
        for name, a in top:
            print(f"  {name[:34]:34} {a['n']:>6,} tasks  {a['cost']:>10,.0f}u")
    print(f"(full ledger: python company.py pnl --raw)")


def cmd_metrics(as_json: bool = False) -> None:
    try:
        import urllib.request
        with urllib.request.urlopen(METRICS_URL, timeout=5) as resp:
            data = json.loads(resp.read())
        if as_json:
            print(json.dumps(data, indent=2))
            return
        if isinstance(data, dict):
            for key in ("office", "tasks", "agents", "providers", "provider_pools",
                        "stocks", "cost_cap", "free_ceiling"):
                if key in data:
                    val = data[key]
                    if isinstance(val, dict):
                        inner = "  ".join(f"{k}={v}" for k, v in list(val.items())[:4]
                                          if not isinstance(v, (dict, list)))
                        print(f"  {key}: {inner or '{...}'}")
                    elif isinstance(val, list):
                        print(f"  {key}: {len(val)} item(s)")
                    else:
                        print(f"  {key}: {val}")
            print("  (full payload: python company.py metrics --json)")
        else:
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Dashboard not reachable at {METRICS_URL}: {e}")
        print(f"Start it: cd {OFFICE_OS_PATH} && python core/web_server.py")


def cmd_stocks(args) -> None:
    """Run the all-listed-stocks fundamental analysis bot."""
    if not STOCKS_BOT.exists():
        print(f"Stocks bot not found at {STOCKS_BOT}")
        return
    cmd = [sys.executable, str(STOCKS_BOT)]
    if args.file:
        cmd += ["--file", args.file]
    if args.limit is not None:
        cmd += ["--limit", str(args.limit)]
    if args.market:
        cmd += ["--market", args.market]
    if args.outdir:
        cmd += ["--outdir", args.outdir]
    if args.resume:
        cmd.append("--resume")
    if args.rate_limit is not None:
        cmd += ["--rate-limit", str(args.rate_limit)]
    subprocess.run(cmd)


def cmd_stock_metrics() -> None:
    """Show the last stock analysis run pushed to the metrics endpoint."""
    if not STOCKS_METRICS_FILE.exists():
        print("No stock metrics found. Run a stock analysis first:")
        print(f"  python company.py stocks --limit 10")
        print(f"Expected metrics at: {STOCKS_METRICS_FILE}")
        return
    print(STOCKS_METRICS_FILE.read_text())


def cmd_tasks(list_all: bool, status: str | None, department: str | None, limit: int) -> None:
    """List or query tasks from the task registry."""
    import sys
    sys.path.insert(0, str(COMPANY_DIR))
    from tasks import list_tasks, queue_tasks

    if list_all:
        tasks = list_tasks(status, department, limit)
    elif status == "queued":
        # queue_tasks needs a department - if none specified, get all queued tasks
        if department:
            tasks = queue_tasks(department, limit)
        else:
            # Get all queued tasks by department
            import sqlite3
            from tasks import TASKS_DB
            conn = sqlite3.connect(TASKS_DB)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tasks
                WHERE status = 'QUEUED'
                ORDER BY created_at ASC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            conn.close()

            tasks = []
            for r in rows:
                from tasks import Task
                tasks.append(Task(
                    task_id=r[0], description=r[1], department=r[2], status=r[3],
                    created_at=r[4], updated_at=r[5], assigned_agent=r[6],
                    result=r[7], error=r[8]
                ))
    else:
        tasks = list_tasks(status, department, limit)

    print(f"=== Task Registry ({len(tasks)} tasks) ===")
    for t in tasks:
        print(f"[{t.status:12}] {t.task_id} | {t.description[:50]}...")

    if not tasks:
        print("No tasks found")


def cmd_status() -> None:
    print("=== THE CLAUDE COMPANY — Status ===")
    print()

    # Task Registry
    import sys
    sys.path.insert(0, str(COMPANY_DIR))
    from tasks import list_tasks

    tasks = list_tasks(limit=10)
    print(f"--- Tasks ({len(tasks)} total) ---")
    for t in tasks[:5]:
        print(f"  {t.task_id}: {t.status:12} | {t.description[:40]}...")
    if len(tasks) > 5:
        print(f"  ... and {len(tasks) - 5} more")

    # The office loop. `status` reports; it must not RUN things -- this used to
    # shell out to upgrade_system.py --test, so asking for status executed a
    # test suite and dumped pytest output above the header.
    print("\n--- Office loop ---")
    for label, prog in (("orchestrator", "orchestrator.py"), ("dispatcher", "jev-dispatcher.py")):
        try:
            out = subprocess.run(["/usr/bin/pgrep", "-f", prog],
                                 capture_output=True, text=True, timeout=10)
            pids = [x for x in (out.stdout or "").split() if x]
            print(f"  {label:13} {'RUNNING pid ' + pids[0] if pids else 'not running'}")
        except (OSError, subprocess.SubprocessError):
            print(f"  {label:13} unknown (could not probe)")
    hive_tasks = Path(os.environ.get("OFFICE_OS_HOME") or (Path.home() / "office-os")) / "tasks"
    if hive_tasks.is_dir():
        counts = {}
        for f in hive_tasks.glob("*.json"):
            try:
                counts_key = json.loads(f.read_text()).get("status", "unknown")
            except (json.JSONDecodeError, OSError):
                counts_key = "unreadable"
            counts[counts_key] = counts.get(counts_key, 0) + 1
        total = sum(counts.values())
        detail = "  ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        print(f"  hive tasks    {total} total   {detail}")
    else:
        print(f"  hive tasks    none at {hive_tasks}")

    # Stocks
    print("\n--- Stocks (last run) ---")
    if STOCKS_METRICS_FILE.exists():
        try:
            sm = json.loads(STOCKS_METRICS_FILE.read_text())
            print(f"Service: {sm.get('service')}  Market: {sm.get('market')}  Status: {sm.get('status')}")
            print(f"Symbols analyzed: {sm.get('symbols_analyzed')}  Errors: {sm.get('errors')}")
            print(f"Analyzed at: {sm.get('analyzed_at')}")
            top = sm.get("top_by_market_cap") or []
            if top:
                print("Top by market cap:")
                for t in top[:5]:
                    print(f"  {t.get('symbol')} — {t.get('name')} — {_fmt_money(t.get('market_cap'))} — {t.get('valuation_flag')}")
        except (json.JSONDecodeError, OSError) as e:
            print(f"Could not read stock metrics: {e}")
    else:
        print("No stock metrics found. Run: python company.py stocks --limit 10")

    # P&L
    print("\n--- Office P&L ---")
    cmd_pnl()

    # Metrics
    print("\n--- Dashboard Metrics ---")
    cmd_metrics()

    # Charter: a pointer. Printing 1500 characters of it pushed the status
    # numbers off the screen, which is the opposite of a status command.
    charter = Path(COMPANY_DIR / "COMPANY_CHARTER.md")
    if charter.exists():
        first = next((l.strip("# ").strip() for l in charter.read_text().splitlines()
                      if l.strip()), "")
        print(f"\n--- Charter --- {first[:60]}  ({charter})")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="THE CLAUDE COMPANY — Unified Launcher")
    sub = parser.add_subparsers(dest="command")

    p_dispatch = sub.add_parser("dispatch", help="Dispatch a task to a department")
    p_dispatch.add_argument("task", nargs="?", help="Task description")
    p_dispatch.add_argument("--department", choices=["research", "trading", "fleet", "upgrade", "ops", "assistant"])

    p_tasks = sub.add_parser("tasks", help="Query task registry")
    p_tasks.add_argument("--all", "-a", action="store_true", help="List all tasks")
    p_tasks.add_argument("--status", "-s", choices=["SUBMITTED", "VALIDATING", "QUEUED", "LEASED", "RUNNING", "VERIFYING", "SUCCEEDED", "FAILED"])
    p_tasks.add_argument("--department", "-d", choices=["research", "trading", "fleet", "upgrade", "ops", "assistant", "stocks"])
    p_tasks.add_argument("--limit", "-l", type=int, default=10, help="Max tasks to show")

    p_queue = sub.add_parser("queue", help="Show queued tasks")
    p_queue.add_argument("--department", "-d", choices=["research", "trading", "fleet", "upgrade", "ops", "assistant", "stocks"])
    p_queue.add_argument("--limit", "-l", type=int, default=10, help="Max tasks to show")

    p_dost = sub.add_parser("dost", help="Talk to your dost")
    p_dost.add_argument("message", nargs="?")
    p_dost.add_argument("--department", choices=["research", "trading", "fleet", "upgrade", "ops", "assistant"])
    p_dost.add_argument("--briefing", action="store_true")
    p_dost.add_argument("--push-telegram", action="store_true", help="Push daily briefing to Telegram")
    p_dost.add_argument("--memory", action="store_true")
    p_dost.add_argument("--context", action="store_true")
    p_dost.add_argument("--health", action="store_true", help="Check OpenAI component availability")

    p_upgrade = sub.add_parser("upgrade", help="Self-upgrade system")
    p_upgrade.add_argument("--list", action="store_true")
    p_upgrade.add_argument("--test", action="store_true")
    p_upgrade.add_argument("--rules", action="store_true")

    p_pnl = sub.add_parser("pnl", help="Show office P&L")
    p_pnl.add_argument("--raw", action="store_true", help="Print the whole ledger")
    p_pnl.add_argument("--limit", type=int, default=10, help="Agents to list")
    p_metrics = sub.add_parser("metrics", help="Show dashboard metrics")
    p_metrics.add_argument("--json", action="store_true", dest="as_json",
                           help="Print the raw payload")
    sub.add_parser("stock-metrics", help="Show last stock analysis metrics")
    p_stocks = sub.add_parser("stocks", help="Run all-listed-stocks fundamental analysis bot")
    p_stocks.add_argument("--file", help="Path to a file with one symbol per line")
    p_stocks.add_argument("--limit", type=int, help="Max symbols to analyze (for testing)")
    p_stocks.add_argument("--market", choices=["nse", "us", "both"], default="nse",
                          help="Market universe: nse (default), us, or both")
    p_stocks.add_argument("--outdir", default="reports", help="Output directory (default: reports/)")
    p_stocks.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    p_stocks.add_argument("--rate-limit", type=float, default=0.5, help="Seconds between yfinance calls")
    sub.add_parser("status", help="Full company status")

    args = parser.parse_args()

    if args.command == "dispatch":
        cmd_dispatch(args.task, args.department)
    elif args.command == "tasks":
        cmd_tasks(args.all, args.status, args.department, args.limit)
    elif args.command == "queue":
        cmd_tasks(False, "QUEUED", args.department, args.limit)
    elif args.command == "dost":
        cmd_dost(args.message, args.department, args.briefing, args.push_telegram,
                 args.memory, args.context, args.health)
    elif args.command == "upgrade":
        cmd_upgrade(args)
    elif args.command == "pnl":
        cmd_pnl(args.raw, args.limit)
    elif args.command == "metrics":
        cmd_metrics(args.as_json)
    elif args.command == "stocks":
        cmd_stocks(args)
    elif args.command == "stock-metrics":
        cmd_stock_metrics()
    elif args.command == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
