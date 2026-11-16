#!/usr/bin/env python3
"""Hourly floor rollup: what each floor did, and what is wrong with it.

Every agent logs its own STATUS line and nothing reads them. A floor lead
knows what its own agents are doing, and the top-level agent knows what it was
told, and nothing reconciles the two. So a floor can be silent for hours and
still look fine from above, which is the failure mode this exists to close.

This reads the canonical sources rather than creating a new registry:

    registry.json            agent -> floor, the ownership map
    sessions.json            live agent state: status, heartbeat, current task
    task_truth_summary.json  the fleet-wide findings, including the LLM check

and writes a single rollup that answers, per floor: how many agents are
healthy, how many are stale, how many have vanished from the registry, and
what work is in flight. It escalates a line only when something is wrong,
because a summary that reads the same when everything is fine and when a
floor is dead is a summary nobody reads.

Read-only. It never writes to the files it reads.
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.environ.get("OPENALICE_ROOT", "/Users/a/trading/openalice-fleet")
HIVE = os.environ.get("OPENALICE_HIVE", os.path.join(ROOT, "hive"))

REGISTRY = os.path.join(HIVE, "registry.json")
SESSIONS = os.path.join(HIVE, "sessions.json")
TRUTH = os.path.join(HIVE, "task_truth_summary.json")
OUT = os.path.join(HIVE, "floor_rollup.json")

# A session that has not heartbeated inside this is not doing anything,
# whatever its recorded status says.
STALE_AFTER_S = 300


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def parse_ts(raw):
    if not raw or not isinstance(raw, str):
        return None
    t = raw.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(t)
    except ValueError:
        return None


def floor_of(registry):
    """agent_id -> floor, from the registry's own ownership map."""
    agents = registry.get("agents") if isinstance(registry, dict) else None
    out = {}
    if isinstance(agents, dict):
        items = agents.items()
    elif isinstance(agents, list):
        items = [(a.get("id"), a) for a in agents if isinstance(a, dict)]
    else:
        return out
    for aid, entry in items:
        if not aid:
            continue
        floor = (entry or {}).get("floor")
        if floor:
            out[aid] = floor
    return out


def live_sessions(sessions, now):
    """agent_id -> freshest session dict."""
    if isinstance(sessions, dict):
        items = sessions.values()
    elif isinstance(sessions, list):
        items = sessions
    else:
        return {}
    best = {}
    for s in items:
        if not isinstance(s, dict):
            continue
        aid = s.get("agent_id")
        if not aid:
            continue
        hb = parse_ts(s.get("last_heartbeat"))
        cur = best.get(aid)
        curb = parse_ts(cur.get("last_heartbeat")) if cur else None
        if cur is None or (hb and (not curb or hb > curb)):
            best[aid] = s
    return best


def staleness(session, now):
    hb = parse_ts(session.get("last_heartbeat"))
    if hb is None:
        return None  # unknown, not stale. Do not invent a verdict.
    age = (now - hb).total_seconds()
    return age


def truth_findings():
    """Fleet-wide findings, summarised. Absent file is not a clean bill."""
    d = read_json(TRUTH)
    if not isinstance(d, dict):
        return None
    checks = d.get("checks")
    if isinstance(checks, list):
        rows = []
        for c in checks:
            if not isinstance(c, dict):
                continue
            st = c.get("status") or c.get("state")
            if st in ("finding", "failed", "FAIL", "1"):
                rows.append(c)
        return rows
    return None


def llm_success_rate():
    """Reuse the scheduled check rather than re-measuring it here."""
    script = os.path.join(ROOT, "scripts", "check_llm_success_rate.py")
    if not os.path.isfile(script):
        return None
    try:
        p = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    rate = None
    m = re.search(r"success rate\s+:\s+(\d+)%", p.stdout)
    if m:
        rate = int(m.group(1))
    return {"rate": rate, "exit": p.returncode}


def build(now):
    registry = read_json(REGISTRY, {}) or {}
    sessions = read_json(SESSIONS, {}) or {}
    owners = floor_of(registry)
    live = live_sessions(sessions, now)

    floors = {}
    for aid, fl in owners.items():
        f = floors.setdefault(fl, {"floor": fl, "agents": 0, "healthy": 0, "stale": 0,
                                   "unknown_heartbeat": 0, "in_flight": 0, "agents_detail": {}})
        f["agents"] += 1
        s = live.get(aid)
        if not s:
            f["agents_detail"][aid] = "NO_SESSION"
            continue
        if s.get("current_task_id"):
            f["in_flight"] += 1
        age = staleness(s, now)
        if age is None:
            f["unknown_heartbeat"] += 1
            f["agents_detail"][aid] = "UNKNOWN_HEARTBEAT"
        elif age > STALE_AFTER_S:
            f["stale"] += 1
            f["agents_detail"][aid] = "STALE_%ds" % int(age)
        else:
            f["healthy"] += 1
            f["agents_detail"][aid] = "OK"

    # agents with a session but no registry entry: unowned work
    unowned = sorted(a for a in live if a not in owners)

    total = {"agents": sum(f["agents"] for f in floors.values()),
             "healthy": sum(f["healthy"] for f in floors.values()),
             "stale": sum(f["stale"] for f in floors.values()),
             "unknown_heartbeat": sum(f["unknown_heartbeat"] for f in floors.values()),
             "in_flight": sum(f["in_flight"] for f in floors.values())}

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_note": "point-in-time; staleness is last_heartbeat older than %ds" % STALE_AFTER_S,
        "totals": total,
        "floors": [floors[k] for k in sorted(floors)],
        "unowned_agents_with_sessions": unowned,
        "fleet_findings_count": None,
        "llm_success_rate": llm_success_rate(),
    }


def render(r):
    t = r["totals"]
    lines = []
    lines.append("FLOOR ROLLUP  %s" % r["generated_at"])
    lines.append("  agents %d | healthy %d | stale %d | unknown %d | in flight %d"
                 % (t["agents"], t["healthy"], t["stale"], t["unknown_heartbeat"], t["in_flight"]))
    lines.append("")
    for f in r["floors"]:
        flag = "" if f["stale"] == 0 and f["unknown_heartbeat"] == 0 else "   <-- attention"
        lines.append("  %-12s agents %-3d healthy %-3d stale %-3d unknown %-3d flight %-3d%s"
                     % (f["floor"], f["agents"], f["healthy"], f["stale"],
                        f["unknown_heartbeat"], f["in_flight"], flag))
    if r["unowned_agents_with_sessions"]:
        lines.append("")
        lines.append("  agents running with NO registry entry: %s"
                     % ", ".join(r["unowned_agents_with_sessions"]))
    llm = r.get("llm_success_rate") or {}
    if llm.get("rate") is not None:
        verdict = "healthy" if llm.get("exit") == 0 else "DEGRADED"
        lines.append("")
        lines.append("  LLM success rate: %d%%  (%s)" % (llm["rate"], verdict))
    return "\n".join(lines)


def write_atomic(path, obj):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", type=float, default=None, help="epoch seconds, for tests")
    ap.add_argument("--dry-run", action="store_true", help="print only, write nothing")
    args = ap.parse_args()

    now = args.now if args.now is not None else time.time()
    r = build(now)
    print(render(r))

    if not args.dry_run:
        write_atomic(OUT, r)
        print("\n  wrote %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
