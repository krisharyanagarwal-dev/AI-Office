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
import subprocess
import sys
from pathlib import Path

COMPANY_DIR = Path(__file__).resolve().parent
DISPATCHER = COMPANY_DIR / "company_dispatcher.py"
UPGRADE = COMPANY_DIR / "upgrade_system.py"
DOST = COMPANY_DIR / "dost.py"
STOCKS_BOT = COMPANY_DIR / "scripts" / "all_stocks_bot.py"
PNL_FILE = Path("/Users/aryanagarwal/.openclaw/office_pnl.json")
METRICS_URL = "http://127.0.0.1:8083/metrics"


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


def cmd_pnl() -> None:
    if not PNL_FILE.exists():
        print("No P&L ledger found. Run tasks first to generate cost/outcome data.")
        print(f"Expected at: {PNL_FILE}")
        return
    print(PNL_FILE.read_text())


def cmd_metrics() -> None:
    try:
        import urllib.request
        with urllib.request.urlopen(METRICS_URL, timeout=5) as resp:
            data = json.loads(resp.read())
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Dashboard not reachable at {METRICS_URL}: {e}")
        print("Start it: cd /Users/aryanagarwal/AI-Office/packages/office-os && python core/web_server.py")


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
    if args.outdir:
        cmd += ["--outdir", args.outdir]
    if args.resume:
        cmd.append("--resume")
    if args.rate_limit is not None:
        cmd += ["--rate-limit", str(args.rate_limit)]
    subprocess.run(cmd)


def cmd_status() -> None:
    print("=== THE CLAUDE COMPANY — Status ===")
    print()

    # Dispatcher
    print("--- Fleet Dispatcher ---")
    subprocess.run([sys.executable, str(UPGRADE), "--test"])

    # P&L
    print("\n--- Office P&L ---")
    cmd_pnl()

    # Metrics
    print("\n--- Dashboard Metrics ---")
    cmd_metrics()

    # Charter
    print("\n--- Company Charter ---")
    charter = Path(COMPANY_DIR / "COMPANY_CHARTER.md")
    if charter.exists():
        print(charter.read_text()[:1500])
        print("...")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="THE CLAUDE COMPANY — Unified Launcher")
    sub = parser.add_subparsers(dest="command")

    p_dispatch = sub.add_parser("dispatch", help="Dispatch a task to a department")
    p_dispatch.add_argument("task", help="Task description")
    p_dispatch.add_argument("--department", choices=["research", "trading", "fleet", "upgrade", "ops", "assistant"])

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

    sub.add_parser("pnl", help="Show office P&L")
    sub.add_parser("metrics", help="Show dashboard metrics")
    p_stocks = sub.add_parser("stocks", help="Run all-listed-stocks fundamental analysis bot")
    p_stocks.add_argument("--file", help="Path to a file with one symbol per line")
    p_stocks.add_argument("--limit", type=int, help="Max symbols to analyze (for testing)")
    p_stocks.add_argument("--outdir", default="reports", help="Output directory (default: reports/)")
    p_stocks.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    p_stocks.add_argument("--rate-limit", type=float, default=0.5, help="Seconds between yfinance calls")
    sub.add_parser("status", help="Full company status")

    args = parser.parse_args()

    if args.command == "dispatch":
        cmd_dispatch(args.task, args.department)
    elif args.command == "dost":
        cmd_dost(args.message, args.department, args.briefing, args.push_telegram,
                 args.memory, args.context, args.health)
    elif args.command == "upgrade":
        cmd_upgrade(args)
    elif args.command == "pnl":
        cmd_pnl()
    elif args.command == "metrics":
        cmd_metrics()
    elif args.command == "stocks":
        cmd_stocks(args)
    elif args.command == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
