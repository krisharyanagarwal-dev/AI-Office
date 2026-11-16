import json, os, re, subprocess, time

HIVE = "/Users/a/trading/openalice-fleet/hive"
LIVE = os.path.join(HIVE, "costs.json")

def snap():
    d = json.load(open(LIVE))
    return {k: len((v.get("records") or [])) for k, v in d.items()}

print("  capturing which agents lose records, to test the shared-agent hypothesis")
lost_tot = {}
prev = snap()
t0 = time.time()
while time.time() - t0 < 180:
    time.sleep(1.0)
    cur = snap()
    for k in prev:
        if cur.get(k, 0) < prev[k]:
            lost_tot[k] = lost_tot.get(k, 0) + (prev[k] - cur.get(k, 0))
    prev = cur

print()
print("  agents that lost records (agent -> records lost):")
for k, v in sorted(lost_tot.items(), key=lambda x: -x[1]):
    print("     %-18s %d" % (k, v))

# Which processes record for which agentId?
print()
print("  AGENT_ID -> process count (a value > 1 means multiple writers for one agent)")
out = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True)
procs = {}
for line in out.splitlines():
    m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/([a-z_]+)\.js", line)
    if m:
        procs.setdefault(m.group(1), []).append(line.split()[0])

# agent managers hardcode their own AGENT_ID, so count is 1 each. The question
# is whether any manager is passed a different agentId at runtime. Check the
# registry ids against the manager script's own AGENT_ID.
multi = {k: v for k, v in procs.items() if len(v) > 1}
print("     managers running more than one process: %s" % (multi or "none"))
print()
print("  -> shared-agent writers are NOT process-per-agent if the next check finds")
print("     one manager invoking recordCost with an agentId that is not its own.")
