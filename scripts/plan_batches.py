import importlib.util, re

spec = importlib.util.spec_from_file_location("rr", "scripts/rolling_restart_agents.py")
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SystemExit:
    pass

_, ct = mod.fix_commit()
pids = mod.agent_pids()

def started(p):
    vals = [t for t in p.values() if t]
    return max(vals) if vals else 0

stale = [a for a in pids if pids[a] and started(pids[a]) and started(pids[a]) < ct]

def bucket(a):
    if a in ("mainbot", "office-manager", "god"):
        return 4                      # protected / special: last
    if re.fullmatch(r"[Ff]\d+", a):
        return 3                      # numbered floors
    if a.startswith("pm-"):
        return 2
    if a.startswith("worker-"):
        return 1
    return 0                          # specialists

groups = {i: sorted([a for a in stale if bucket(a) == i]) for i in range(5)}
for i in range(5):
    print("  batch %d: %d agents" % (i + 1, len(groups[i])))

# Pad to exactly 5 non-empty batches, splitting the largest group if needed.
plan = []
big = max(range(5), key=lambda i: len(groups[i]))
while len([g for g in groups.values() if g]) < 5 and len(groups[big]) >= 2:
    half = len(groups[big]) // 2
    groups[big + 0.5] = groups[big][:half]
    groups[big + 0.5].extend(groups[big])
    del groups[big]
    big = max((i for i in groups if isinstance(i, int)), key=lambda i: len(groups[i]))

print()
n = 0
for i in sorted(groups):
    g = groups[i]
    if not g:
        continue
    n += 1
    print("BATCH %d (%d): %s" % (n, len(g), ",".join(g)))
