import json, os, time

HIVE = "/Users/a/trading/openalice-fleet/hive"

def counts():
    u = json.load(open(os.path.join(HIVE, "costs-union.json")))
    l = json.load(open(os.path.join(HIVE, "costs.json")))
    ur = sum(len((v.get("records") or [])) for v in u.values())
    lr = sum(len((v.get("records") or [])) for v in l.values())
    return ur, lr, ur - lr

print("  10 x 30s samples. Success = no loss and a gap that does not grow.")
prev = counts()
print("  %-8s %-10s %-10s %-9s %-8s" % ("t", "archive", "live", "gap", "delta"))
print("  %-8s %-10d %-10d %-9d" % ("0s", prev[0], prev[1], prev[2]))
losses = []
for i in range(10):
    time.sleep(30)
    cur = counts()
    d = cur[1] - prev[1]
    losses.append(d < 0)
    print("  %-8s %-10d %-10d %-9d %+d" % ("%ds" % ((i + 1) * 30), cur[0], cur[1], cur[2], d))
    prev = cur

print()
print("  samples where live lost records : %d of 10" % sum(losses))
print("  gap at start                     : see row 0")
print("  gap at end                       : %d" % prev[2])
