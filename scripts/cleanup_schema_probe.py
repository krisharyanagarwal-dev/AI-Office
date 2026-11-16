import json, os, tempfile

p = "/Users/a/trading/openalice-fleet/hive/costs.json"
d = json.load(open(p))
before = len(d)
d.pop("SCHEMA-PROBE", None)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p))
with os.fdopen(fd, "w") as f:
    json.dump(d, f)
os.replace(tmp, p)
print("  agentIds %d -> %d" % (before, len(d)))
print("  schema keys intact:", all(k in d for k in ["F2", "F8", "pm-data"]))
