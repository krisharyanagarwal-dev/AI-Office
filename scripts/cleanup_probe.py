import json, os, sys, tempfile

p = "/Users/a/trading/openalice-fleet/hive/costs.json"
d = json.load(open(p))
before = len(d)
had = "PROBE-ONLY" in d
d.pop("PROBE-ONLY", None)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p))
with os.fdopen(fd, "w") as f:
    json.dump(d, f)
os.replace(tmp, p)

orig = ["F2", "F8", "pm-data", "pm-ops", "pm-signal",
        "specialist-07", "specialist-15", "worker-dwight"]
print("  PROBE-ONLY was present :", had)
print("  agentIds %d -> %d" % (before, len(d)))
print("  all original ids intact:", all(k in d for k in orig))
print("  missing originals      :", [k for k in orig if k not in d])
print("  total records          :", sum(len(v.get("records") or []) for v in d.values()))
