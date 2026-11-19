#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Unified Company Dispatcher

Routes every task to the right department:
- Research → hypothesis queue, backtests, verdict gates, calibration
- Trading → paper engine, cost models, forward sim
- Fleet → JEV 32-agent dispatch (paper-only, Tier C blocked)
- Assistant → code, write, analyze, strategize, plan
- Ops → P&L, tiers, health, dashboards
- Upgrade → self-improvement (code, prompts, configs, processes)

All PAPER ONLY. Kill switch LOCKED. No live orders ever.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

# Add office-os to path for existing dispatcher imports
sys.path.insert(0, "/Users/aryanagarwal/AI-Office/packages/office-os")

COMPANY_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = Path("/Users/aryanagarwal/Documents/indian-paper-trading")
FLEET_DISPATCHER = "/Users/aryanagarwal/.openclaw/jev-dispatcher.py"

COMPANY_LOG = Path("/Users/aryanagarwal/AI-Office/logs/company.log")
COMPANY_LOG.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}: {msg}"
    print(line, flush=True)
    with open(COMPANY_LOG, "a") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Department routing
# ---------------------------------------------------------------------------

TRADING_KEYWORDS = (
    "backtest", "strategy", "option", "stock", "nifty", "nse", "trade",
    "paper", "cost", "margin", "stt", "gst", "brokerage", "equity",
    "intraday", "momentum", "mean reversion", "pair", "fii", "dii",
    "bhavcopy", "iv rank", "straddle", "strangle", "condor",
)

RESEARCH_KEYWORDS = (
    "hypothesis", "gate", "holdout", "calibration", "public record",
    "research report", "pre-register", "out-of-sample", "edge",
)

UPGRADE_KEYWORDS = (
    "upgrade", "refactor", "improve", "evolve", "migrate", "update config",
    "self-improve", "optimize code",
)

OPS_KEYWORDS = (
    "pnl", "profit", "loss", "tier", "autonomy", "provider health",
    "dashboard", "metrics", "kill switch", "ops",
)

ASSISTANT_KEYWORDS = (
    "code", "write", "analyze", "strategize", "plan", "memo", "report",
    "document", "review", "debug", "draft", "email", "slide",
)


def route_department(task: str) -> str:
    """Route a task to the right department based on keywords."""
    t = task.lower()
    score = {
        "research": 0,
        "trading": 0,
        "upgrade": 0,
        "ops": 0,
        "assistant": 0,
    }

    for kw in RESEARCH_KEYWORDS:
        if kw in t:
            score["research"] += 2
    for kw in TRADING_KEYWORDS:
        if kw in t:
            score["trading"] += 2
    for kw in UPGRADE_KEYWORDS:
        if kw in t:
            score["upgrade"] += 2
    for kw in OPS_KEYWORDS:
        if kw in t:
            score["ops"] += 2
    for kw in ASSISTANT_KEYWORDS:
        if kw in t:
            score["assistant"] += 2

    # Default to assistant for general tasks
    best = max(score, key=score.get)
    if score[best] == 0:
        return "assistant"
    return best


# ---------------------------------------------------------------------------
# Department handlers
# ---------------------------------------------------------------------------

def handle_research(task: str) -> dict:
    """Route to NSE research machine."""
    log(f"RESEARCH: {task[:80]}")
    return {
        "department": "research",
        "handled_by": "research_machine",
        "task": task,
        "status": "queued",
        "note": "Use hypothesis_queue.py / o3_runner.py in research dept",
        "available_commands": [
            "python hypothesis_queue.py list",
            "python o3_runner.py register",
            "python o3_runner.py gate",
            "python o3_runner.py holdout",
            "python o3_runner.py calibrate",
            "python o3_runner.py report",
        ],
    }


def handle_trading(task: str) -> dict:
    """Route to paper trading engine."""
    log(f"TRADING: {task[:80]}")
    return {
        "department": "trading",
        "handled_by": "paper_engine",
        "task": task,
        "status": "queued",
        "note": "Paper only — backtests and forward sim. No live orders.",
        "available_commands": [
            "python backtest_defined_risk.py",
            "python backtest_options_selling.py",
            "python paper_trader.py",
            "python chain_metrics.py",
        ],
    }


def handle_fleet(task: str) -> dict:
    """Route to JEV fleet dispatch."""
    log(f"FLEET: {task[:80]}")
    return {
        "department": "fleet",
        "handled_by": "jev_dispatcher",
        "task": task,
        "status": "queued",
        "note": "32 agents, paper-only, Tier C blocked, kill switch LOCKED",
        "available_commands": [
            "python jev-dispatcher.py --pnl",
        ],
        "dispatcher": FLEET_DISPATCHER,
    }


def handle_upgrade(task: str) -> dict:
    """Route to self-upgrade system."""
    log(f"UPGRADE: {task[:80]}")
    return {
        "department": "upgrade",
        "handled_by": "upgrade_system",
        "task": task,
        "status": "queued",
        "note": "Self-upgrade: code, prompts, configs, processes",
        "available_commands": [
            "Review COMPANY_CHARTER.md for upgrade rules",
            "Run dispatcher tests: pytest tests/test_dispatcher.py",
        ],
    }


def handle_ops(task: str) -> dict:
    """Route to company operations."""
    log(f"OPS: {task[:80]}")
    pnl_file = Path("/Users/aryanagarwal/.openclaw/office_pnl.json")
    pnl_exists = pnl_file.exists()
    return {
        "department": "ops",
        "handled_by": "ops_system",
        "task": task,
        "status": "queued",
        "note": "Company P&L, tiers, provider health, dashboards",
        "pnl_ledger_exists": pnl_exists,
        "available_commands": [
            "python jev-dispatcher.py --pnl",
            "curl http://127.0.0.1:8083/metrics",
        ],
    }


def handle_assistant(task: str) -> dict:
    """Handle general Claude capabilities (code, write, analyze, strategize)."""
    log(f"ASSISTANT: {task[:80]}")
    return {
        "department": "assistant",
        "handled_by": "general_assistant",
        "task": task,
        "status": "ready",
        "capabilities": [
            "code_generation",
            "code_review",
            "debugging",
            "writing",
            "analysis",
            "strategy",
            "planning",
            "research_support",
        ],
        "note": "General assistant — autonomous Tier A. Describe what you need built.",
    }


# ---------------------------------------------------------------------------
# Company entry point
# ---------------------------------------------------------------------------

DEPARTMENT_HANDLERS = {
    "research": handle_research,
    "trading": handle_trading,
    "fleet": handle_fleet,
    "upgrade": handle_upgrade,
    "ops": handle_ops,
    "assistant": handle_assistant,
}


def dispatch(task: str, department: str | None = None) -> dict:
    """Dispatch a task to the right department."""
    dept = department or route_department(task)
    handler = DEPARTMENT_HANDLERS.get(dept, handle_assistant)
    result = handler(task)
    result["routed_department"] = dept
    result["task_id"] = f"c-{uuid.uuid4().hex[:8]}"
    result["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="THE CLAUDE COMPANY — Unified Dispatcher")
    parser.add_argument("task", nargs="?", help="Task description")
    parser.add_argument("--department", choices=list(DEPARTMENT_HANDLERS.keys()),
                        help="Force department routing")
    parser.add_argument("--route", action="store_true",
                        help="Show routing decision without executing")
    args = parser.parse_args()

    if not args.task:
        parser.print_help()
        return

    if args.route:
        dept = route_declaration(args.task) if False else route_department(args.task)
        print(f"Task: {args.task}")
        print(f"Routed to: {dept} department")
        return

    result = dispatch(args.task, args.department)
    print(json.dumps(result, indent=2))


def route_declaration(task: str) -> str:
    return route_department(task)


if __name__ == "__main__":
    main()
