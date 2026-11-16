"""Per-batch health verification for the rolling restart.

Usage: batch_health.py <label> a,b,c
Exits non-zero if anything a batch must not break is broken, so the run can
stop before the next batch.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

HIVE = "/Users/a/trading/openalice-fleet/hive"

spec = importlib.util.spec_from_file_location("rr", os.path.join(HIVE, "scripts/rolling_restart_agents.py"))
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SystemExit:
    pass

label = sys.argv[1] if len(sys.argv) > 1 else "?"
batch = [a for a in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if a]

_, fix_ct = mod.fix_commit()
pids = mod.agent_pids()


def started(p):
    vals = [t for t in p.values() if t]
    return max(vals) if vals else 0


fail = []

# 1. trading safety
ps = subprocess.check_output(["ps", "-eww", "-o", "args="], text=True)
trader_live = ps.count("ALPHAINSIDER_TRADER_ENABLED=1")
print("  [%s] trading: ENABLED=1 count=%d  -> %s"
      % (label, trader_live, "LOCKED" if trader_live == 0 else "UNSAFE"))
if trader_live:
    fail.append("TRADER NOT LOCKED")

# 2. batch members
print("  [%s] batch members: %d" % (label, len(batch)))
notalive, notfixed = [], []
for a in batch:
    p = pids.get(a)
    if not p:
        notalive.append(a)
        continue
    if started(p) < fix_ct:
        notfixed.append(a)
    for pid, ts in sorted(p.items()):
        print("     %-16s pid=%-7s on_fix=%s" % (a, pid, ts >= fix_ct))
if notalive:
    fail.append("not running: %s" % ",".join(notalive))
if notfixed:
    fail.append("still pre-fix: %s" % ",".join(notfixed))

# 3. fleet + supervisor
n_mgr = len(subprocess.check_output(["pgrep", "-f", "agent_manager.js"], text=True).split())
sup = len(subprocess.check_output(["pgrep", "-f", "agent_supervisor.py"], text=True).split())
print("  [%s] fleet: %d agent_managers, supervisor=%d" % (label, n_mgr, sup))
if sup == 0:
    fail.append("SUPERVISOR DOWN")
if n_mgr < 50:
    fail.append("fleet collapsed to %d" % n_mgr)

# 4. cost ledger
u = json.load(open(os.path.join(HIVE, "costs-union.json")))
l = json.load(open(os.path.join(HIVE, "costs.json")))
ur = sum(len((v.get("records") or [])) for v in u.values())
lr = sum(len((v.get("records") or [])) for v in l.values())
behind = sum(1 for k in u if len(((l.get(k) or {}).get("records")) or []) < len((u[k].get("records") or [])))
newest = max((r.get("timestamp") or "") for v in l.values() for r in (v.get("records") or []))
print("  [%s] ARCHIVE %d ids / %d records" % (label, len(u), ur))
print("  [%s] LIVE    %d ids / %d records" % (label, len(l), lr))
print("  [%s] GAP     %d records across %d agents" % (label, ur - lr, behind))
print("  [%s] newest live record: %s" % (label, newest))

# 5. batch logs: any crash signature?
for a in batch:
    p = os.path.join(HIVE, "agents", a, "agent.log")
    if not os.path.isfile(p):
        continue
    try:
        tail = open(p, errors="ignore").read()[-4000:]
    except Exception:
        continue
    bad = re.findall(r"(Uncaught|FATAL|SyntaxError|out of memory|ENOMEM)", tail)
    if bad:
        fail.append("%s log shows %s" % (a, set(bad)))

print()
if fail:
    print("  BATCH %s FAILED:" % label)
    for f in fail:
        print("     - %s" % f)
    sys.exit(1)
print("  BATCH %s HEALTHY" % label)
