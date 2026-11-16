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
MEMORY = _dost_module.MEMORY


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Talk to your dost")
    parser.add_argument("message", nargs="?")
    parser.add_argument("--department", choices=["research", "trading", "fleet", "ops", "upgrade", "assistant"])
    parser.add_argument("--briefing", action="store_true")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--context", action="store_true")
    parser.add_argument("--health", action="store_true", help="Check OpenAI component availability")
    args = parser.parse_args()

    if args.briefing:
        print(generate_daily_briefing())
    elif args.memory:
        import json
        print(json.dumps(MEMORY.profile, indent=2))
    elif args.context:
        print(MEMORY.get_context())
    elif args.health:
        import json
        print(json.dumps(provider_health(), indent=2))
    elif args.message:
        print(dost_respond(args.message, args.department))
    else:
        print(dost_greeting())


if __name__ == "__main__":
    main()