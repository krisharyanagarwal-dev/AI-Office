import json, os, collections

HIVE = "/Users/a/trading/openalice-fleet/hive"
l = json.load(open(os.path.join(HIVE, "costs.json")))
u = json.load(open(os.path.join(HIVE, "costs-union.json")))

lr = sum(len((v.get("records") or [])) for v in l.values())
ur = sum(len((v.get("records") or [])) for v in u.values())

print("== COUNTS ==")
print("  live    : %d agents / %d records" % (len(l), lr))
print("  archive : %d agents / %d records" % (len(u), ur))
print("  GAP     : %d" % (ur - lr))
print("  agents only in archive (should be 0 now):", sorted(set(u) - set(l)) or "none")
print("  agents only in live:", sorted(set(l) - set(u)) or "none")

print()
print("== DUPLICATES (per agent, on (timestamp,taskId)) ==")
dup_agents = 0
dup_total = 0
for k, v in l.items():
    recs = v.get("records") or []
    c = collections.Counter((r.get("timestamp"), r.get("taskId")) for r in recs)
    d = {key: n for key, n in c.items() if n > 1}
    if d:
        dup_agents += 1
        dup_total += sum(n - 1 for n in d.values())
        if dup_agents <= 3:
            print("  %-16s %d duplicate entries" % (k, sum(n - 1 for n in d.values())))
print("  agents with duplicates: %d   total duplicate entries: %d" % (dup_agents, dup_total))

print()
print("== PER-AGENT INTEGRITY (live vs archive) ==")
behind = []
for k in sorted(u):
    a = len(((u[k].get("records")) or []))
    b = len(((l.get(k, {}).get("records")) or []))
    if b < a:
        behind.append((k, b, a))
print("  agents where live is behind archive: %d" % len(behind))
for k, b, a in behind[:5]:
    print("     %-16s live=%-6d archive=%-6d gap=%d" % (k, b, a, a - b))

print()
print("== DAILY / MONTHLY INTEGRITY ==")
bad_daily = [k for k, v in l.items() if v.get("daily") is None]
bad_monthly = [k for k, v in l.items() if v.get("monthly") is None]
print("  agents with daily=null   : %d %s" % (len(bad_daily), bad_daily[:4]))
print("  agents with monthly=null : %d %s" % (len(bad_monthly), bad_monthly[:4]))
# live must never be lower than the archive on an accumulator
reg = [k for k in u if isinstance((u[k].get("monthly")), (int, float))
       and isinstance((l.get(k, {}).get("monthly")), (int, float))
       and l[k]["monthly"] < u[k]["monthly"]]
print("  agents where live monthly < archive monthly: %d %s" % (len(reg), reg[:4]))
