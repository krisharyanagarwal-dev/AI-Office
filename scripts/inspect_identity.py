import json, os

HIVE = "/Users/a/trading/openalice-fleet/hive"
u = json.load(open(os.path.join(HIVE, "costs-union.json")))
l = json.load(open(os.path.join(HIVE, "costs.json")))

allrecs = [r for v in u.values() for r in (v.get("records") or [])]
print("  archive records total      : %d" % len(allrecs))
if not allrecs:
    raise SystemExit
r = allrecs[0]
print("  record fields              : %s" % ",".join(sorted(r.keys())))

def uniq(keyfn, rows):
    return len({keyfn(x) for x in rows})

print()
print("  uniqueness across ALL archive records:")
print("    timestamp alone          : %d unique of %d" % (uniq(lambda x: x.get("timestamp"), allrecs), len(allrecs)))
print("    taskId alone             : %d unique of %d" % (uniq(lambda x: x.get("taskId"), allrecs), len(allrecs)))
print("    (timestamp, taskId)      : %d unique of %d" % (uniq(lambda x: (x.get("timestamp"), x.get("taskId")), allrecs), len(allrecs)))
print("    (agentId,timestamp,taskId): %d unique of %d" % (
    uniq(lambda x: (x.get("agentId"), x.get("timestamp"), x.get("taskId")), allrecs), len(allrecs)))

# Is the archive a strict superset of live, per agent?
print()
print("  per-agent: does live's record set appear inside the archive's?")
def keyset(rows):
    return {(x.get("timestamp"), x.get("taskId")) for x in (rows or [])}
not_subset = []
for k in sorted(u):
    a = keyset(u[k].get("records"))
    b = keyset(l.get(k, {}).get("records"))
    if not b <= a:
        not_subset.append((k, len(b - a)))
print("    agents where live has records the archive lacks: %d" % len(not_subset))
for k, n in not_subset[:6]:
    print("       %-16s %d" % (k, n))
print()
print("  -> archive is a superset" if not not_subset else "  -> NOT a strict superset; a union merge is required")
