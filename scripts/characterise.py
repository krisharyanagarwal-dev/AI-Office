import json, time

LIVE = "/Users/a/trading/openalice-fleet/hive/costs.json"

def snap():
    d = json.load(open(LIVE))
    return {k: len((v.get("records") or [])) for k, v in d.items()}, set(d)

print("  sampling to characterise the residual loss")
prev, prev_ids = snap()
events = []
for i in range(10):
    time.sleep(10)
    cur, ids = snap()
    lost = {k: prev[k] - cur.get(k, 0) for k in prev if cur.get(k, 0) < prev[k]}
    gone = sorted(prev_ids - ids)
    if lost or gone:
        total = sum(lost.values())
        agents = len(lost)
        ratio = total / max(1, sum(prev.values()))
        events.append(total)
        print("    t=%3ds lost=%-5d across %-3d agents (%4.1f%% of db)  ids_removed=%s"
              % ((i + 1) * 10, total, agents, ratio * 100, gone or "none"))
    prev, prev_ids = cur, ids

print()
if not events:
    print("  NO LOSS observed in 100s")
else:
    worst = max(events)
    print("  largest single loss: %d records" % worst)
    if worst > 2000:
        print("  -> whole-database collapse signature")
    else:
        print("  -> partial, multi-agent loss: consistent with a lost-update race in")
        print("     read-modify-write. Atomic rename stops torn READS but gives no")
        print("     mutual exclusion, so two writers can both read the same base and")
        print("     the second rename drops the first's records.")
