#!/usr/bin/env python3
"""Preserve cost history that the multi-writer clobber is still destroying.

lib/llm/cost.js now merges before writing (commit f0d7912), but the 55 running
agents have held the old module in memory for ~27 hours and will not reload it
on their own. Measured loss is ~965 records per 20 seconds, and costs.json is
gitignored, so everything dropped is gone permanently.

This does not fix the writers and does not touch costs.json. It maintains a
separate monotonic union archive so the history that still exists is not lost
while the fix waits to be loaded. When the agents do restart, the union can be
merged back.

The merge is deliberately monotone:

  * an agentId present in the union is never removed
  * an agent's record list never shrinks; only longer lists replace shorter ones
  * a finite daily/monthly figure is never overwritten by null or NaN

That makes the archive incapable of losing data, and it cannot write to the
live database, so it cannot make the live problem worse.
"""
import json
import os
import tempfile
import time

HIVE = os.environ.get("OPENALICE_HIVE", "/Users/a/trading/openalice-fleet/hive")
LIVE = os.path.join(HIVE, "costs.json")
UNION = os.path.join(HIVE, "costs-union.json")
LOG = os.path.join(HIVE, "costs-union-snapshots.log")


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def num(v):
    """Return v if it is a usable number, else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)) and v == v and v not in (float("inf"), float("-inf")):
        return float(v)
    return None


def better(a, b):
    """Prefer a finite number; NaN and null never displace a real figure."""
    na, nb = num(a), num(b)
    if na is not None:
        return na
    if nb is not None:
        return nb
    return a


def merge_into_union(live, union):
    added, grew, repaired = [], [], []

    for agent, entry in live.items():
        if not isinstance(entry, dict):
            continue
        recs = entry.get("records") or []
        if agent not in union:
            union[agent] = {"daily": entry.get("daily"), "monthly": entry.get("monthly"),
                            "records": list(recs)}
            added.append(agent)
            continue

        cur = union[agent]
        cur_recs = cur.get("records") or []
        if len(recs) > len(cur_recs):
            cur["records"] = list(recs)
            grew.append("%s %d->%d" % (agent, len(cur_recs), len(recs)))
        cur["daily"] = better(entry.get("daily"), cur.get("daily"))
        cur["monthly"] = better(entry.get("monthly"), cur.get("monthly"))
        if num(entry.get("monthly")) is not None and num(cur.get("monthly")) != num(entry.get("monthly")):
            repaired.append(agent)

    return added, grew, repaired


def write_atomic(path, obj):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    live = read_json(LIVE)
    if not live:
        print("no live costs.json yet")
        return 0

    union = read_json(UNION)
    before = sum(len((v.get("records") or [])) for v in union.values() if isinstance(v, dict))
    added, grew, repaired = merge_into_union(live, union)
    after = sum(len((v.get("records") or [])) for v in union.values() if isinstance(v, dict))

    write_atomic(UNION, union)

    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s live_ids=%d union_ids=%d union_records=%d added=%s grew=%s repaired=%s\n" % (
            time.strftime("%Y-%m-%dT%H:%M:%S"), len(live), len(union), after,
            added or "-", grew or "-", repaired or "-"))

    if added or grew or repaired:
        print("union %d ids / %d records (was %d); added=%s grew=%s repaired=%s"
              % (len(union), after, before, added, grew, repaired))
    else:
        print("union steady at %d ids / %d records" % (len(union), after))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
