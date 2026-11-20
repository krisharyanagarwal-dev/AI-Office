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
dispatch_prompt_to_fleet = _dost_module.dispatch_prompt_to_fleet
create_workspace = _dost_module.create_workspace
get_workspace = _dost_module.get_workspace
list_workspaces = _dost_module.list_workspaces
add_user = _dost_module.add_user
list_users = _dost_module.list_users
get_user_role = _dost_module.get_user_role
ensure_default_workspace = _dost_module.ensure_default_workspace
DEFAULT_WORKSPACE_ID = _dost_module.DEFAULT_WORKSPACE_ID
_handle_workspace_command = _dost_module._handle_workspace_command

# Strategy pipeline (dispatch → backtest → cost-size → validate)
_strategy_pipeline_path = Path(__file__).resolve().parent / "dost" / "trading" / "strategy_pipeline.py"
_strategy_pipeline_spec = importlib.util.spec_from_file_location("strategy_pipeline", _strategy_pipeline_path)
_strategy_pipeline_module = importlib.util.module_from_spec(_strategy_pipeline_spec)
_strategy_pipeline_spec.loader.exec_module(_strategy_pipeline_module)
run_strategy_pipeline = _strategy_pipeline_module.run_strategy_pipeline


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
    parser.add_argument("--backtest", nargs="?", const="", help="Run full strategy pipeline: dispatch, backtest, cost-size, validate. Optional prompt text.")
    parser.add_argument("--results", action="store_true", help="List recent dost-submitted tasks from the fleet hive")
    parser.add_argument("--history", nargs="?", const="", help="Search dost task history by keyword (optional search term)")
    parser.add_argument("--history-regex", help="Search dost task history by regex pattern")
    parser.add_argument("--results-status", choices=["done", "error", "in_progress", "pending"], help="Filter --results by status")
    parser.add_argument("--results-agent", help="Filter --results by agent_id")
    parser.add_argument("--briefing-now", action="store_true", help="Generate on-demand briefing immediately")
    parser.add_argument("--export", choices=["md", "json"], help="Export last debate/dispatch results to file")
    parser.add_argument("--synthesis", action="store_true", help="Show detailed synthesis report over all findings")
    parser.add_argument("--auto-archive", action="store_true", help="Auto-archive pending findings older than 30 days")
    parser.add_argument("--weekly-digest", action="store_true", help="Show weekly findings digest")
    parser.add_argument("--debug", action="store_true", help="Verbose provider calls, model selection, pool routing")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be dispatched without writing")
    parser.add_argument("--batch", help="Batch dispatch: comma-separated prompts")
    parser.add_argument("--parent", help="Parent task ID to thread this dispatch under")
    parser.add_argument("--chain", help='Chain metadata JSON: {"prompt": "...", "agent_id": "...", "priority": "normal"}. Auto-dispatched when this task completes.')
    parser.add_argument("--review", help="Tier C review: comma-separated 'index:action' pairs (action: confirm/contest/skip/delete). Example: --review '3:confirm,7:contest,9:skip'")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--context", action="store_true")
    parser.add_argument("--health", action="store_true", help="Check OpenAI component availability")
    parser.add_argument("--doctor", action="store_true",
                        help="Run a one-command system health check")
    parser.add_argument("--workspace", help="Workspace id to scope all dispatch operations to")
    parser.add_argument("--create-workspace", metavar="NAME",
                        help="Create a new workspace with the given name")
    parser.add_argument("--list-workspaces", action="store_true",
                        help="List all workspaces")
    parser.add_argument("--add-user", nargs=2, metavar=("EMAIL", "ROLE"),
                        help="Add a user (email role) to the current/default workspace")

    # `dost workspace` subcommand group for workspace management
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")
    ws_parser = subparsers.add_parser("workspace", help="Workspace management")
    ws_parser.add_argument("action", choices=["list", "create", "add-user"],
                           help="Workspace action: list | create <name> | add-user <workspace_id> <email> [role]")
    ws_parser.add_argument("rest", nargs="*", help="Additional arguments for the workspace action")

    args = parser.parse_args()

    if args.doctor:
        board, code = doctor()
        print(board)
        sys.exit(code)
    if args.push_telegram:
        _dost_module._push_telegram_briefing()
    elif args.command == "workspace":
        _handle_workspace_command(args)
    elif args.briefing:
        print(generate_daily_briefing())
    elif args.status:
        st = _dost_module._fetch_dispatcher_status()
        if st:
            print(json.dumps(st, indent=2))
        else:
            print("Fleet status: unreachable (dispatcher may be down).")
    elif args.create_workspace:
        ws = create_workspace(args.create_workspace, owner_email="admin@default.local")
        print(json.dumps(ws, indent=2))
    elif args.list_workspaces:
        workspaces = list_workspaces()
        if not workspaces:
            print("No workspaces found.")
        else:
            print("ID | Name | Plan | Owner")
            for ws in workspaces:
                print(f"{ws['id']} | {ws.get('name','')} | {ws.get('plan','')} | {ws.get('owner_email','')}")
    elif args.add_user:
        email, role = args.add_user
        ws_id = args.workspace or ensure_default_workspace()
        added = add_user(ws_id, email, role)
        print(json.dumps(added, indent=2))
    elif args.dispatch is not None:
        workspace_id = args.workspace or ensure_default_workspace()
        prompt = args.dispatch if args.dispatch else input("Prompt to send to fleet: ")
        chain = None
        if args.chain:
            try:
                chain = json.loads(args.chain)
            except json.JSONDecodeError as e:
                print(f"Invalid --chain JSON: {e}")
                sys.exit(1)
        result = _dost_module.dispatch_prompt_to_fleet(
            prompt,
            priority=args.results_status or "normal",
            dry_run=args.dry_run,
            parent_task_id=args.parent,
            chain=chain,
            workspace_id=workspace_id,
        )
        print(json.dumps(result, indent=2))
        if args.debug:
            print(f"\n🔧 Debug: dispatch_prompt_to_fleet called with priority={args.results_status or 'normal'}, dry_run={args.dry_run}, parent={args.parent or 'none'}, chain={chain is not None}")
    elif args.batch:
        chain = None
        if args.chain:
            try:
                chain = json.loads(args.chain)
            except json.JSONDecodeError as e:
                print(f"Invalid --chain JSON: {e}")
                sys.exit(1)
        prompts = [p.strip() for p in args.batch.split(",") if p.strip()]
        print(f"Batch dispatch: {len(prompts)} prompts")
        for i, prompt in enumerate(prompts, 1):
            print(f"\n[{i}/{len(prompts)}] {prompt[:80]}")
            result = _dost_module.dispatch_prompt_to_fleet(
                prompt,
                priority="normal",
                dry_run=args.dry_run,
                parent_task_id=args.parent,
                chain=chain,
            )
            print(json.dumps(result, indent=2))
            if args.debug:
                print(f"  [debug] priority=normal, dry_run={args.dry_run}, parent={args.parent or 'none'}, task_id={result.get('task_id', '?')}")
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
        query = args.history if args.history else None
        results = _dost_module.search_history(query)
        if not results:
            if query:
                print(f"No dost tasks matching '{query}'.")
            else:
                print("No dost tasks found.")
        else:
            if query:
                print(f"Found {len(results)} dost task(s) matching '{query}':")
            else:
                print(f"Recent dost tasks ({len(results)}):")
            for i, t in enumerate(results, 1):
                parent = f" ← {t['parent_task_id'][:8]}" if t.get("parent_task_id") else ""
                print(
                    f"{i}. {t['task_id']} | {t['status']} | {t['agent_id']} | "
                    f"{t['pool']} | {t['updated_at']}{parent}"
                )
                if t["preview"]:
                    print(f"    preview: {t['preview']}")
    elif args.history_regex:
        import re
        try:
            pattern = re.compile(args.history_regex)
        except re.error as e:
            print(f"Invalid regex: {e}")
            sys.exit(1)
        results = _dost_module.search_history_regex(pattern)
        if not results:
            print(f"No dost tasks matching regex '{args.history_regex}'.")
        else:
            print(f"Found {len(results)} dost task(s) matching regex '{args.history_regex}':")
            for i, t in enumerate(results, 1):
                parent = f" ← {t['parent_task_id'][:8]}" if t.get("parent_task_id") else ""
                print(
                    f"{i}. {t['task_id']} | {t['status']} | {t['agent_id']} | "
                    f"{t['pool']} | {t['updated_at']}{parent}"
                )
                if t["preview"]:
                    print(f"    preview: {t['preview']}")
    elif args.export:
        _dost_module.export_results(args.export)
    elif args.synthesis:
        print(_dost_module.synthesis_detail())
    elif args.auto_archive:
        n = _dost_module.auto_archive_findings()
        print(f"Archived {n} pending findings older than 30 days.")
    elif args.weekly_digest:
        print(_dost_module.weekly_findings_digest())
    elif args.review:
        actions = []
        for pair in args.review.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if ":" not in pair:
                print(f"Invalid review pair '{pair}' — use index:action (action: confirm/contest/skip/delete)")
                sys.exit(1)
            idx_str, act = pair.split(":", 1)
            try:
                idx = int(idx_str.strip())
            except ValueError:
                print(f"Invalid index '{idx_str}' — must be an integer")
                sys.exit(1)
            actions.append({"index": idx, "action": act.strip().lower()})
        result = _dost_module.review_findings(actions)
        print(f"Tier C review applied: {result['actions_applied']} action(s), {result['deleted']} deleted")
        print(f"Verification after: {result['verification_after']}")
        print(f"Total findings: {result['total_after']}")
        for d in result["details"]:
            err = f" — {d['error']}" if d.get("error") else ""
            print(f"  [{d['index']}] {d['action']} → {d.get('status', d.get('agent', '?'))}{err}")
    elif args.memory:
        print(json.dumps(MEMORY.profile, indent=2))
    elif args.context:
        print(build_context())
    elif args.health:
        print(json.dumps(provider_health(), indent=2))
    elif args.backtest is not None:
        prompt = args.backtest if args.backtest else input("Strategy pipeline prompt: ")
        result = run_strategy_pipeline(
            prompt=prompt,
            agent_id="strategy-advisor",
            priority="normal",
        )
        print(json.dumps(result, indent=2, default=str))
    elif args.message:
        print(dost_respond(args.message, args.department))
    else:
        print(dost_greeting())
        print("\nI'm your dost. Tell me what you need: research, trading, code, writing, strategy.")
        print("Commands: --briefing, --briefing-now, --push-telegram, --status, --dispatch, --dry-run, --batch, --debug, --parent, --results, --results-status, --results-agent, --history, --history-regex, --export, --synthesis, --review, --auto-archive, --weekly-digest, --memory, --context, --health, --doctor, --department X")


if __name__ == "__main__":
    main()