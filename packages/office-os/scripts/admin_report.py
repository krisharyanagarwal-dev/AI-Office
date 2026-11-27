#!/usr/bin/env python3
"""
admin-report.py - Print findings store summary (Track Record view).

Like tradedesk's scripts/admin_report.py: shows how many findings have run,
the most active agents, results flagged by the automatic checks, and the
hit rate for outcomes that have been decided.

Usage:
    python scripts/admin_report.py          # summary
    python scripts/admin_report.py --json   # machine-readable JSON
    python scripts/admin_report.py --agent <name>  # filter by agent
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# Load the jev_dispatcher module for its findings functions.
_DISPATCHER_PATH = str(Path.home() / ".openclaw" / "jev-dispatcher.py")
_spec = importlib.util.spec_from_file_location("jev_dispatcher", _DISPATCHER_PATH)
jev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jev)


def main():
    parser = argparse.ArgumentParser(
        description="Print findings store summary (Track Record view)"
    )
    parser.add_argument(
        "--json", action="store_true", help="output machine-readable JSON"
    )
    parser.add_argument(
        "--agent", type=str, default=None, help="filter by agent name"
    )
    args = parser.parse_args()

    store = jev.load_findings_store()
    findings = store.get("findings", [])

    if args.agent:
        findings = [f for f in findings if f.get("agent") == args.agent]

    total = len(findings)
    verdicts = {}
    outcomes = {}
    by_agent = {}
    for f in findings:
        v = f.get("verdict", "unknown")
        verdicts[v] = verdicts.get(v, 0) + 1
        o = f.get("outcome", "pending")
        outcomes[o] = outcomes.get(o, 0) + 1
        a = f.get("agent", "unknown")
        by_agent[a] = by_agent.get(a, 0) + 1

    decided = outcomes.get("right", 0) + outcomes.get("wrong", 0)
    hit_rate = round(outcomes.get("right", 0) / decided * 100, 1) if decided else 0

    if args.json:
        print(
            json.dumps(
                {
                    "total_findings": total,
                    "verdicts": verdicts,
                    "outcomes": outcomes,
                    "by_agent": by_agent,
                    "decided": decided,
                    "hit_rate": hit_rate,
                },
                indent=2,
            )
        )
        return

    print("=== Findings Store Summary (Track Record) ===")
    print(f"Total findings: {total}")
    print(f"Decided: {decided} | Hit rate: {hit_rate}%")
    print()

    print("Verdicts:")
    for v, c in sorted(verdicts.items()):
        print(f"  {v:15s} {c}")
    print()

    print("Outcomes:")
    for o, c in sorted(outcomes.items()):
        print(f"  {o:15s} {c}")
    print()

    print("By Agent:")
    for a, c in sorted(by_agent.items(), key=lambda x: -x[1]):
        print(f"  {a:25s} {c}")
    print()

    if total == 0:
        print("No findings yet. Run the JEV dispatcher to generate some.")
    elif decided == 0:
        print(
            "No outcomes decided yet. Use update_finding_outcome() to mark findings "
            "as right/wrong/inconclusive as results come in."
        )


if __name__ == "__main__":
    main()
