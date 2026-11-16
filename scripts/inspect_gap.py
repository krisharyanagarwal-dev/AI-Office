import json, os

HIVE = "/Users/a/trading/openalice-fleet/hive"
u = json.load(open(os.path.join(HIVE, "costs-union.json")))
l = json.load(open(os.path.join(HIVE, "costs.json")))

print("  agent            live  archive   delta   sample_record_keys")
shown = 0
for k in sorted(u):
    a = (u[k].get("records") or [])
    b = (l.get(k, {}).get("records") or [])
    if len(a) != len(b):
        keys = sorted(a[0].keys()) if a else []
        print("  %-16s %5d %7d %7d   %s" % (k, len(b), len(a), len(a) - len(b), ",".join(keys)))
        shown += 1
print("  agents differing: %d" % shown)

# Can we build a stable identity for a record?
k0 = sorted(u)[0]
recs = u[k0].get("records") or []
if recs:
    r = recs[0]
    print()
    print("  candidate identity fields:")
    for f in ("timestamp", "taskId", "costUsd", "model"):
        if f in r:
            print("     %-10s = %r" % (f, r[f]))
    ts = [x.get("timestamp") for x in recs if x.get("timestamp")]
    tids = [x.get("taskId") for x in recs if x.get("taskId")]
    print("  records with timestamp: %d/%d  unique: %d" % (len(ts), len(recs), len(set(ts))))
    print("  records with taskId   : %d/%d  unique: %d" % (len(tids), len(recs), len(set(tids))))
    if ts and tids:
        pairs = list(zip(ts, tids))
        print("  (timestamp,taskId) unique pairs: %d of %d" % (len(set(pairs)), len(pairs)))
