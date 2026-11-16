#!/usr/bin/env python3
"""Detect any process still holding a pre-fix lib/llm/cost.js.

The multi-writer clobber in costs.json cannot recur while every writer merges
before writing, so the invariant worth testing permanently is: no running
process predates the fix commit.

This exists because a hand-typed epoch was wrong once and reported a clean
fleet while a stale writer was running. The comparison timestamp is read from
git, never hardcoded, so it follows the fix rather than a constant somebody
has to remember to update.

Exit codes:
  0  every node process that can write costs is on or after the fix
  1  at least one process predates the fix and can clobber costs.json
  2  the fix commit could not be resolved
"""
import argparse
import datetime
import re
import subprocess
import sys

DEFAULT_HIVE = "/Users/a/trading/openalice-fleet/hive"
DEFAULT_FIX = "f0d7912"

# Only processes that can actually reach saveCosts() matter. Agents get there
# through lib/llm/client.js requiring ./cost.
WRITER = re.compile(r"(?:agents/[A-Za-z0-9_.-]+/bin/[a-z_]+\.js|lib/llm/(?:client|cost)\.js)")


def fix_epoch(hive, ref):
    out = subprocess.check_output(["git", "-C", hive, "log", "-1", "--format=%H %ct", ref], text=True)
    h, ts = out.strip().split()
    return h, int(ts)


def parse_lstart(lstart):
    try:
        return int(subprocess.check_output(
            ["date", "-j", "-f", "%a %b %d %H:%M:%S %Y", lstart, "+%s"],
            text=True).strip())
    except Exception:
        return None


def scan():
    out = subprocess.check_output(["ps", "-eo", "pid=,lstart=,args="], text=True)
    writers, unreadable = [], []
    for line in out.splitlines():
        if "node" not in line or not WRITER.search(line):
            continue
        p = line.split()
        if len(p) < 6:
            continue
        pid, lstart = p[0], " ".join(p[1:6])
        m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/([a-z_]+)\.js", line)
        label = "%s/%s" % (m.group(1), m.group(2)) if m else "lib/llm"
        ts = parse_lstart(lstart)
        if ts is None:
            unreadable.append((label, pid, lstart))
        else:
            writers.append((label, pid, ts))
    return writers, unreadable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hive", default=DEFAULT_HIVE)
    ap.add_argument("--fix", default=DEFAULT_FIX,
                    help="commit that must be loaded; timestamp is read from git")
    args = ap.parse_args()

    try:
        commit, fix = fix_epoch(args.hive, args.fix)
    except Exception as e:
        print("  cannot resolve fix commit %s: %s" % (args.fix, e))
        return 2

    writers, unreadable = scan()
    stale = [w for w in writers if w[2] < fix]

    print("  fix commit      : %s  %s" % (commit[:8],
          datetime.datetime.fromtimestamp(fix).strftime("%Y-%m-%d %H:%M:%S")))
    print("  cost writers    : %d" % len(writers))
    print("  on/after fix    : %d" % (len(writers) - len(stale)))
    print("  PRE-FIX writers : %d" % len(stale))
    for label, pid, ts in sorted(stale):
        print("     STALE  %-26s pid=%-7s started %s" % (
            label, pid, datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")))
    for label, pid, lstart in unreadable:
        print("     UNREADABLE start time, left alone: %-22s pid=%s %r" % (label, pid, lstart))

    if stale:
        print("\n  RESULT: a pre-fix writer is live and can still clobber costs.json.")
        print("  The union snapshot is doing real work and must not be removed.")
        return 1
    print("\n  RESULT: no pre-fix cost writer is live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
