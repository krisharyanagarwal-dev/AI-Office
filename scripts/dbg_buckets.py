import importlib.util, subprocess

spec = importlib.util.spec_from_file_location("rr", "scripts/rolling_restart_agents.py")
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SystemExit:
    pass

commit, ct = mod.fix_commit()
pids = mod.agent_pids()
print("  fix=%s ct=%d  agent ids=%d" % (commit[:8], ct, len(pids)))

def started(p):
    vals = [t for t in p.values() if t]
    return max(vals) if vals else 0

unknown = {a for a, p in pids.items() if p and not started(p)}
stale = {a: p for a, p in pids.items() if p and started(p) and started(p) < ct}
live = {a: p for a, p in pids.items() if a not in stale and a not in unknown}
empty = {a for a, p in pids.items() if not p}

print("  stale=%d live=%d unknown=%d empty=%d  total=%d" % (
    len(stale), len(live), len(unknown), len(empty),
    len(stale) + len(live) + len(unknown) + len(empty)))
print("  unknown: %s" % sorted(unknown))
print("  empty  : %s" % sorted(empty))
print("  live   : %s" % sorted(live))
print()
for a in sorted(set(pids) - stale - live):
    print("  UNACCOUNTED %-18s pids=%s started=%s" % (a, pids[a], started(pids[a])))
