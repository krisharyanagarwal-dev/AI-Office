#!/usr/bin/env python3
"""THE CLAUDE COMPANY — Dost CLI wrapper.

One command to talk to your dost:
  python dost.py "research NSE options edges"
  python dost.py --briefing
  python dost.py --memory
  python dost.py --context
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_dost_path = Path(__file__).resolve().parent / "dost" / "dost.py"
_spec = importlib.util.spec_from_file_location("dost_module", _dost_path)
_dost_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dost_module)

dost_respond = _dost_module.dost_respond
dost_greeting = _dost_module.dost_greeting
generate_daily_briefing = _dost_module.generate_daily_briefing
provider_health = _dost_module.provider_health
build_context = _dost_module.build_context
doctor = _dost_module.doctor
MEMORY = _dost_module.MEMORY


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Talk to your dost")
    parser.add_argument("message", nargs="?")
    parser.add_argument("--department", choices=["research", "trading", "fleet", "ops", "upgrade", "assistant"])
    parser.add_argument("--briefing", action="store_true")
    parser.add_argument("--push-telegram", action="store_true", help="Push daily briefing to Telegram")
    parser.add_argument("--status", action="store_true", help="Show live fleet status from dispatcher metrics")
    parser.add_argument("--dispatch", nargs="?", const="", help="Submit a prompt to the fleet orchestrator")
    parser.add_argument("--debate", nargs="?", const="", help="Debate mode: fan a question to multiple pro agents and synthesize")
    parser.add_argument("--results", action="store_true", help="List recent dost-submitted tasks from the fleet hive")
    parser.add_argument("--history", nargs="?", const="", help="Search dost task history by keyword (optional search term)")
    parser.add_argument("--results-status", choices=["done", "error", "in_progress", "pending"], help="Filter --results by status")
    parser.add_argument("--results-agent", help="Filter --results by agent_id")
    parser.add_argument("--briefing-now", action="store_true", help="Generate on-demand briefing immediately")
    parser.add_argument("--export", choices=["md", "json"], help="Export last debate/dispatch results to file")
    parser.add_argument("--synthesis", action="store_true", help="Show detailed synthesis report over all findings")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--context", action="store_true")
    parser.add_argument("--health", action="store_true", help="Check OpenAI component availability")
    parser.add_argument("--doctor", action="store_true",
                        help="Run a one-command system health check")
    args = parser.parse_args()

    if args.doctor:
        board, code = doctor()
        print(board)
        sys.exit(code)
    if args.push_telegram:
        _dost_module._push_telegram_briefing()
    elif args.briefing:
        print(generate_daily_briefing())
    elif args.status:
        st = _dost_module._fetch_dispatcher_status()
        if st:
            print(json.dumps(st, indent=2))
        else:
            print("Fleet status: unreachable (dispatcher may be down).")
    elif args.dispatch is not None:
        prompt = args.dispatch if args.dispatch else input("Prompt to send to fleet: ")
        result = _dost_module.dispatch_prompt_to_fleet(prompt)
        print(json.dumps(result, indent=2))
    elif args.debate is not None:
        prompt = args.debate if args.debate else input("Debate question: ")
        result = _dost_module.dispatch_debate_to_fleet(prompt)
        print(json.dumps(result, indent=2))
        if result.get("cost_units"):
            print(f"\n💰 Debate cost: {result['cost_units']} cost_units")
        if result.get("_cached"):
            print("⚡ Served from answer cache (no provider calls)")
    elif args.results:
        tasks = _dost_module.list_recent_dost_tasks(
            status_filter=args.results_status,
            agent_filter=args.results_agent,
        )
        if not tasks:
            print("No dost-submitted tasks found.")
        else:
            for t in tasks:
                print(
                    f"{t['task_id']} | {t['status']} | {t['agent_id']} | "
                    f"{t['model']} | {t['pool']} | {t['updated_at']}"
                )
                if t["preview"]:
                    print(f"    preview: {t['preview']}")
    elif args.briefing_now:
        print(_dost_module.generate_daily_briefing())
    elif args.history is not None:
        query = args.history if args.history else input("Search history for: ")
        results = _dost_module.search_history(query)
        if not results:
            print(f"No dost tasks matching '{query}'.")
        else:
            print(f"Found {len(results)} dost task(s) matching '{query}':")
            for t in results:
                print(
                    f"{t['task_id']} | {t['status']} | {t['agent_id']} | "
                    f"{t['model']} | {t['pool']} | {t['updated_at']}"
                )
                if t["preview"]:
                    print(f"    preview: {t['preview']}")
    elif args.export:
        _dost_module.export_results(args.export)
    elif args.synthesis:
        print(_dost_module.synthesis_detail())
    elif args.memory:
        print(json.dumps(MEMORY.profile, indent=2))
    elif args.context:
        print(build_context())
    elif args.health:
        print(json.dumps(provider_health(), indent=2))
    elif args.message:
        print(dost_respond(args.message, args.department))
    else:
        print(dost_greeting())
        print("\nI'm your dost. Tell me what you need: research, trading, code, writing, strategy.")
        print("Commands: --briefing, --push-telegram, --status, --dispatch, --results, --history, --memory, --context, --health, --doctor, --department X")


if __name__ == "__main__":
    main()