import json, time

LIVE = "/Users/a/trading/openalice-fleet/hive/costs.json"

def snap():
    d = json.load(open(LIVE))
    return {k: len((v.get("records") or [])) for k, v in d.items()}

print("  sampling every 2s for 30s to separate one big revert from many small collisions")
prev = snap()
events = []
for i in range(15):
    time.sleep(2)
    cur = snap()
    lost = {k: prev[k] - cur[k] for k in prev if cur.get(k, 0) < prev[k]}
    gone = sorted(set(prev) - set(cur))
    if lost or gone:
        events.append((i * 2, sum(lost.values()), len(lost), gone))
        print("    t=%2ds  records lost=%-5d across %-3d agents  ids removed=%s"
              % (i * 2, sum(lost.values()), len(lost), gone or "none"))
    prev = cur

print()
if not events:
    print("  no loss observed in 30s")
elif len(events) == 1 and events[0][1] > 200:
    print("  PATTERN: single large event -> whole-file revert by a pre-fix writer")
else:
    print("  PATTERN: %d separate small events -> lost-update race in read-merge-write,"
          % len(events))
    print("           not a whole-file revert. Merge has no lock, so two writers")
    print("           can read the same base and the second write drops the first.")
