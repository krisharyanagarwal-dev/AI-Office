#!/usr/bin/env python3
"""CLI entry point for Dost Proactive Agent.

Usage:
    python -m dost.cli_proactive start      # Start proactive agent
    python -m dost.cli_proactive status     # Check agent status
    python -m dost.cli_proactive briefing   # Generate morning briefing now
    python -m dost.cli_proactive scan       # Run opportunity scan now
    python -m dost.cli_proactive heal       # Run self-healing check now
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ops.proactive_agent import ProactiveAgent


async def cmd_start(args):
    """Start the proactive agent."""
    config = {
        "scheduler": {"enabled": True, "jobs": {}},
        "anomaly_watch": {"enabled": True, "check_interval_sec": 60},
        "opportunity_scanner": {"enabled": True, "schedule_interval_sec": 3600},
        "self_healing": {"enabled": True, "check_interval_sec": 60},
    }

    agent = ProactiveAgent(config)
    print("Starting Dost Proactive Agent...")
    print("Press Ctrl+C to stop")
    try:
        await agent.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        agent.stop()


async def cmd_briefing(args):
    """Generate and display morning briefing now."""
    from ops.morning_briefing import MorningBriefing
    briefing = MorningBriefing()
    result = briefing.generate_briefing()
    if result.get("ok"):
        print(result["content"])
    else:
        print(f"Error: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


async def cmd_scan(args):
    """Run opportunity scan now."""
    from ops.opportunity_scanner import OpportunityScanner
    scanner = OpportunityScanner()
    result = await scanner.run_once()
    if result.get("ok"):
        print(json.dumps(result, indent=2))
    else:
        print(f"Error: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


async def cmd_heal(args):
    """Run self-healing check now."""
    from ops.self_healing import FleetSelfHealing
    healing = FleetSelfHealing()
    result = await healing.run_once()
    if result.get("ok"):
        print(json.dumps(result, indent=2))
    else:
        print(f"Error: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


async def cmd_status(args):
    """Check proactive agent status."""
    from ops.proactive_scheduler import ProactiveScheduler
    scheduler = ProactiveScheduler()
    status = scheduler.get_job_status()
    print(json.dumps(status, indent=2))


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Dost Proactive Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("start", help="Start proactive agent (runs until Ctrl+C)")
    subparsers.add_parser("briefing", help="Generate morning briefing now")
    subparsers.add_parser("scan", help="Run opportunity scan now")
    subparsers.add_parser("heal", help="Run self-healing check now")
    subparsers.add_parser("status", help="Check scheduler job status")

    args = parser.parse_args()

    if args.command == "start":
        asyncio.run(cmd_start(args))
    elif args.command == "briefing":
        asyncio.run(cmd_briefing(args))
    elif args.command == "scan":
        asyncio.run(cmd_scan(args))
    elif args.command == "heal":
        asyncio.run(cmd_heal(args))
    elif args.command == "status":
        asyncio.run(cmd_status(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()