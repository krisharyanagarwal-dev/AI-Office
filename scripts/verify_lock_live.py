import os, time, subprocess, json

HIVE = "/Users/a/trading/openalice-fleet/hive"
LOCK = os.path.join(HIVE, "costs.json.lock")
TMP = lambda: [f for f in os.listdir(HIVE) if ".tmp." in f]

seen_lock = 0
seen_tmp = 0
samples = 0
for i in range(60):
    if os.path.exists(LOCK):
        seen_lock += 1
    if TMP():
        seen_tmp += 1
    samples += 1
    time.sleep(0.25)

print("  samples over 15s        : %d" % samples)
print("  samples where costs.json.lock existed : %d" % seen_lock)
print("  samples where a .tmp. file existed     : %d" % seen_tmp)
print()
print("  if the lock never appears, the running managers are not executing withLock")

# Is the lock code actually reachable in the file agents load?
src = open(os.path.join(HIVE, "lib/llm/cost.js")).read()
print("  withLock defined in lib/llm/cost.js : %s" % ("function withLock" in src))
print("  saveCosts calls withLock            : %s" % ("const done = withLock" in src))

# Any other process that could be writing this file?
out = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True)
hits = [l[:110] for l in out.splitlines() if "costs.json" in l and "ps -eo" not in l]
print()
print("  processes with costs.json in their command line: %d" % len(hits))
for h in hits[:5]:
    print("     %s" % h)
