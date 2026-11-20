import json, os, subprocess, time

HIVE = "/Users/a/trading/openalice-fleet/hive"
LIVE = os.path.join(HIVE, "costs.json")
UNION = os.path.join(HIVE, "costs-union.json")


def snap():
    d = json.load(open(LIVE))
    return ({k: len((v.get("records") or [])) for k, v in d.items()}, set(d))


def agent_count():
    return int(subprocess.check_output(["pgrep", "-f", "agent_manager.js"], text=True).split() and
               len(subprocess.check_output(["pgrep", "-f", "agent_manager.js"], text=True).split()) or 0)


def trader_locked():
    out = subprocess.check_output(["ps", "-eww", "-o", "args="], text=True)
    return sum(1 for l in out.splitlines() if "ALPHAINSIDER_TRADER_ENABLED=1" in l) == 0


print("  %-6s %-6s %-9s %-7s %-7s %-6s %-8s" % ("t", "ids", "records", "lost", "gained", "gone", "trader"))
prev_counts, prev_ids = snap()
start = time.time()
prev_t = start
for i in range(1, 5):
    time.sleep(60)
    counts, ids = snap()
    lost = sum(max(0, -(counts.get(k, 0) - prev_counts.get(k, 0))) for k in prev_ids)
    gained = sum(max(0, (counts.get(k, 0) - prev_counts.get(k, 0))) for k in prev_counts)
    gone = sorted(prev_ids - ids)
    t = int(time.time() - start)
    print("  %-6s %-6d %-9d %-7d %-7d %-6d %-8s" % (
        "%ds" % t, len(ids), sum(counts.values()), lost, gained,
        len(gone), "LOCKED" if trader_locked() else "UNLOCKED"))
    if gone:
        print("        ids removed: %s" % gone)
    prev_counts, prev_ids = counts, ids

u = json.load(open(UNION))
print()
print("  union archive intact : %d ids / %d records" % (
    len(u), sum(len((v.get("records") or [])) for v in u.values())))
print("  agent managers alive : %d" % agent_count())
print("  trader locked        : %s" % trader_locked())
