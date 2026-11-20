#!/usr/bin/env python3
"""
ops_check - re-run office survey checks from the terminal (read-only).

The one verification command the Ops agents may cite:

    cd ~/AI-Office/packages/office-os && python3 -m core.ops_check            # all checks
    cd ~/AI-Office/packages/office-os && python3 -m core.ops_check ops-paper-safety ops-mini-services

Exit code 0 when every requested check is OK, 1 otherwise (so it can gate scripts).
"""
import sys

from core import sources


def main(argv):
    wanted = set(argv)
    by_name = {}
    for fn in sources.COLLECTORS:
        by_name[fn.__name__.replace("_", "-")] = fn
    unknown = wanted - set(by_name)
    if unknown:
        print("unknown check(s): " + ", ".join(sorted(unknown)))
        print("available: " + ", ".join(sorted(by_name)))
        return 2
    results = []
    for name, fn in by_name.items():
        if wanted and name not in wanted:
            continue
        try:
            results.append(fn())
        except Exception as e:  # a crashing check is a failed check
            results.append({"name": name, "ok": False, "summary": "check crashed", "problems": [str(e)[:160]]})
    for r in results:
        print(f"{'OK     ' if r['ok'] else 'PROBLEM'} {r['name']}: {r['summary']}")
        for p in r.get("problems", []):
            print(f"        - {p}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
