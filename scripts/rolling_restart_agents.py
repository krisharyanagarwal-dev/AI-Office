#!/usr/bin/env python3
"""Floor-by-floor rolling restart so agents load the fixed lib/llm/cost.js.

Why this exists
---------------
lib/llm/cost.js now merges before writing instead of replacing the whole
shared database (commit f0d7912). But every running agent loaded the module
at startup and has held the old code in memory for roughly 27 hours, so the
multi-writer clobber is still live and was re-measured at 965 records lost
per 20 seconds. No agent will pick the fix up on its own.

Safety model
------------
* Dry run by default. Nothing is signalled unless --apply is passed.
* Never touches the office manager, mainbot, or the trading service.
* One agent at a time, and only after the previous one is proven back.
* A PID is only accepted as restored if it is genuinely NEW (different pid
  from the one we signalled) so a supervisor respawn cannot be mistaken for
  the old process.
* New processes must start after the fix commit, otherwise the restart did
  not achieve its purpose and the run aborts.
* Any timeout or anomaly aborts the whole run. It never continues past a
  floor it could not verify.

Usage
-----
  scripts/rolling_restart_agents.py                 # dry run, prints the plan
  scripts/rolling_restart_agents.py --apply         # execute
  scripts/rolling_restart_agents.py --apply --only F4,F9
  scripts/rolling_restart_agents.py --apply --max 3 # stop after 3 agents
"""
import argparse
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import time

HIVE = os.environ.get("OPENALICE_HIVE", "/Users/a/trading/openalice-fleet/hive")
REGISTRY = os.path.join(HIVE, "registry.json")

# The commit whose module must end up loaded. Copied from git so the check
# follows the fix rather than a hand-typed timestamp.
def fix_commit():
    try:
        out = subprocess.check_output(
            ["git", "-C", HIVE, "log", "-1", "--format=%H %ct", "f0d7912"],
            text=True).strip()
        h, ts = out.split()
        return h, int(ts)
    except Exception:
        return "f0d7912", 0

NEVER_TOUCH = {"office-manager", "mainbot", "trader", "alphainsider"}


def agent_pids():
    """Map agent_id -> set of pids running its manager."""
    out = subprocess.check_output(["ps", "-eo", "pid=,lstart=,args="], text=True)
    found = {}
    for line in out.splitlines():
        m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/agent_manager\.js", line)
        if not m:
            continue
        parts = line.split()
        pid = int(parts[0])
        # lstart occupies fields 1..5, pid 0.
        lstart = " ".join(parts[1:6])
        try:
            started = int(subprocess.check_output(
                ["date", "-j", "-f", "%a %b %d %H:%M:%S %Y", lstart, "+%s"],
                text=True).strip())
        except Exception:
            started = 0
        found.setdefault(m.group(1), {})[pid] = started
    return found


def registry_agents():
    with open(REGISTRY) as f:
        agents = json.load(f)["agents"]
    if isinstance(agents, dict):
        return {k: (v if isinstance(v, dict) else {}) for k, v in agents.items()}
    return {a.get("id"): a for a in agents if isinstance(a, dict)}


def targets(only):
    pids = agent_pids()
    order = []
    for aid in sorted(pids):
        if aid in NEVER_TOUCH:
            continue
        if only and aid not in only:
            continue
        order.append(aid)
    # Lowest risk first: specialists, then numeric floors, then the rest.
    def rank(a):
        if re.fullmatch(r"[A-Za-z]+-\d+|[A-Za-z]+", a):
            return 0
        if re.fullmatch(r"[Ff]\d+", a):
            return 1
        return 2
    return sorted(order, key=lambda a: (rank(a), a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually signal (default is dry run)")
    ap.add_argument("--only", default="", help="comma separated agent ids")
    ap.add_argument("--max", type=int, default=0, help="stop after N agents")
    ap.add_argument("--timeout", type=int, default=90, help="seconds to wait for respawn")
    args = ap.parse_args()

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    commit, commit_ts = fix_commit()
    mode = "APPLY" if args.apply else "DRY RUN (no signals sent)"

    print("=" * 72)
    print("  rolling restart  |  %s" % mode)
    print("  fix commit      : %s  (%s)" % (commit[:8], datetime.datetime.fromtimestamp(commit_ts).strftime("%Y-%m-%d %H:%M:%S") if commit_ts else "?"))
    print("  never touched   : %s" % ", ".join(sorted(NEVER_TOUCH)))
    print("=" * 72)

    pids = agent_pids()
    stale = {a: p for a, p in pids.items()
             if p and max(p.values()) < commit_ts}
    live = {a: p for a, p in pids.items() if a not in stale}

    print("\n  agents running old code (need restart): %d" % len(stale))
    print("  agents already on new code            : %d" % len(live))
    if live:
        print("    already new: %s" % ", ".join(sorted(live)[:10]))

    order = [a for a in targets(only) if a in stale]
    if args.max:
        order = order[:args.max]

    print("\n  planned order (%d):" % len(order))
    for i, a in enumerate(order, 1):
        print("    %2d. %-18s pids=%s" % (i, a, ",".join(str(p) for p in sorted(stale[a]))))

    if not order:
        print("\n  nothing to do")
        return 0

    if not args.apply:
        print("\n  DRY RUN complete. Re-run with --apply to execute.")
        return 0

    results = []
    for i, aid in enumerate(order, 1):
        old = set(stale[aid])
        print("\n  [%d/%d] %s  pids=%s" % (i, len(order), aid, ",".join(str(p) for p in sorted(old))))
        for p in old:
            try:
                os.kill(p, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.time() + args.timeout
        newpid, started = None, 0
        while time.time() < deadline:
            cur = agent_pids().get(aid, {})
            fresh = {p: t for p, t in cur.items() if p not in old}
            if fresh:
                newpid, started = sorted(fresh.items())[0]
                break
            time.sleep(1)

        if not newpid:
            print("      ABORT: %s did not come back within %ds" % (aid, args.timeout))
            return 2
        age_ok = started >= commit_ts
        print("      new pid %d started %s  [%s]" % (
            newpid,
            datetime.datetime.fromtimestamp(started).strftime("%H:%M:%S") if started else "?",
            "loads fix" if age_ok else "WARNING: predates fix commit"))
        results.append((aid, old, newpid, age_ok))
        if not age_ok:
            print("      ABORT: respawn predates the fix, refusing to continue")
            return 3
        time.sleep(3)

    print("\n  restart complete: %d agents" % len(results))
    print("  verify: pgrep -f agent_manager.js | wc -l")
    return 0


if __name__ == "__main__":
    sys.exit(main())
