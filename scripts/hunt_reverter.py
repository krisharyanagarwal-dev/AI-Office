import json, os, time

HIVE = "/Users/a/trading/openalice-fleet/hive"
LIVE = os.path.join(HIVE, "costs.json")

def snap():
    d = json.load(open(LIVE))
    return {k: len((v.get("records") or [])) for k, v in d.items()}

print("  hunting the reverter: which agents lose records, and by how much")
prev = snap()
lost = {}
events = []
for i in range(24):
    time.sleep(10)
    cur = snap()
    drop = {k: prev[k] - cur.get(k, 0) for k in prev if cur.get(k, 0) < prev[k]}
    if drop:
        tot = sum(drop.values())
        events.append(tot)
        for k, v in drop.items():
            lost[k] = lost.get(k, 0) + v
        print("    t=%3ds total_lost=%-6d agents=%s" % ((i + 1) * 10, tot,
              sorted(drop, key=lambda x: -drop[x])[:4]))
    prev = cur

print()
print("  cumulative loss by agent:")
for k, v in sorted(lost.items(), key=lambda x: -x[1])[:10]:
    print("     %-18s %d" % (k, v))
print("  agents involved: %d   total events: %d   total lost: %d"
      % (len(lost), len(events), sum(events)))
