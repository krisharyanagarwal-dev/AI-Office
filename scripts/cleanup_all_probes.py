import json, os, tempfile

p = "/Users/a/trading/openalice-fleet/hive/costs.json"
d = json.load(open(p))
before = len(d)
probes = ["T1", "LIVE-SHAPE", "RATE-nvidia", "RATE-NVIDIA", "C2-nvidia", "C2-NVIDIA"]
for k in list(d):
    if k in probes or k.startswith(("snake-", "camel-", "shape-", "accum-", "unknown-", "case-")):
        d.pop(k)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p))
with os.fdopen(fd, "w") as f:
    json.dump(d, f)
os.replace(tmp, p)
print("  agentIds %d -> %d" % (before, len(d)))
print("  remaining ids:", sorted(d))
