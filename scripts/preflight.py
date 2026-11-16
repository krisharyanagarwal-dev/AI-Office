import json, os, time

HIVE = "/Users/a/trading/openalice-fleet/hive"

def snap():
    l = json.load(open(os.path.join(HIVE, "costs.json")))
    u = json.load(open(os.path.join(HIVE, "costs-union.json")))
    lr = sum(len((v.get("records") or [])) for v in l.values())
    ur = sum(len((v.get("records") or [])) for v in u.values())
    return len(l), lr, len(u), ur

print("  PRE-APPLY parity samples (60s apart) -- loss must be 0")
prev = snap()
print("    t=  0s  live=%d agents/%d recs   archive=%d/%d   gap=%d"
      % (prev[0], prev[1], prev[2], prev[3], prev[3] - prev[1]))
losses = 0
for i in range(1, 4):
    time.sleep(60)
    cur = snap()
    d = cur[1] - prev[1]
    if d < 0:
        losses += 1
    print("    t=%3ds  live=%d agents/%d recs   archive=%d/%d   gap=%d  delta=%+d"
          % (i * 60, cur[0], cur[1], cur[2], cur[3], cur[3] - cur[1], d))
    prev = cur

print()
print("  samples with loss: %d of 3" % losses)
print("  SAFE TO RECONCILE: %s" % (losses == 0))
