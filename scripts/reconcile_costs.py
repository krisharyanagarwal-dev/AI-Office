#!/usr/bin/env python3
"""Reconcile live costs.json with the union archive, without inventing data.

The multi-writer clobber dropped records from the live database while the
archive kept them. The writers are fixed, so the loss has stopped, and the
remaining deficit can now be closed safely: a merge performed today is not
immediately undone the way every earlier attempt would have been.

This is a union, not an overwrite, for three measured reasons:

  * the archive is not a superset. 27 agents have records in live that the
    archive never saw, because the archive itself started partway through.
  * (timestamp, taskId) is unique across all 20950 archive records, so it is
    a safe identity and the union cannot duplicate a record.
  * historical costUsd values are null from the earlier NaN defect. They are
    carried through untouched rather than recomputed, because recomputing
    would silently rewrite history with numbers that were never measured.

daily and monthly are accumulators the writers maintained. The union has more
records than either side alone, so the larger of the two is taken; neither
side's figure is discarded and neither is inflated.

Safety: takes the same exclusive lock the writers use, writes via a temp file
and rename, and takes a timestamped backup before touching anything.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

HIVE = os.environ.get("OPENALICE_HIVE", "/Users/a/trading/openalice-fleet/hive")
LIVE = os.path.join(HIVE, "costs.json")
UNION = os.path.join(HIVE, "costs-union.json")
LOCK = LIVE + ".lock"
LOCK_STALE_MS = 30000


def key(rec):
    """Stable identity for a cost record. Unique across the whole archive."""
    return (rec.get("timestamp"), rec.get("taskId"))


def take_lock(timeout_s=10.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            return os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if (time.time() - os.path.getmtime(LOCK)) * 1000 > LOCK_STALE_MS:
                    os.unlink(LOCK)
            except OSError:
                pass
            time.sleep(0.05)
    return None


def release_lock(fd):
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(LOCK)
    except OSError:
        pass


def num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)) and v == v and v not in (float("inf"), float("-inf")):
        return float(v)
    return None


def merge_agent(live_entry, union_entry):
    """Union of two record lists, ordered by timestamp. No value is invented."""
    seen = {}
    for rec in (live_entry.get("records") or []):
        seen[key(rec)] = rec
    added = 0
    for rec in (union_entry.get("records") or []):
        k = key(rec)
        if k not in seen:
            seen[k] = rec
            added += 1

    records = sorted(seen.values(),
                     key=lambda r: (r.get("timestamp") or "", r.get("taskId") or ""))

    daily = [num(live_entry.get("daily")), num(union_entry.get("daily"))]
    monthly = [num(live_entry.get("monthly")), num(union_entry.get("monthly"))]
    daily = [d for d in daily if d is not None]
    monthly = [m for m in monthly if m is not None]

    return {
        "daily": max(daily) if daily else None,
        "monthly": max(monthly) if monthly else None,
        "records": records,
    }, added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="default is a dry run")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    live = json.load(open(LIVE))
    union = json.load(open(UNION))

    plan, total_added = {}, 0
    for aid in sorted(union):
        if aid not in live:
            plan[aid] = None
            total_added += len(union[aid].get("records") or [])
            continue
        merged, added = merge_agent(live[aid], union[aid])
        if added:
            plan[aid] = merged
            total_added += added

    live_recs = sum(len((v.get("records") or [])) for v in live.values())
    print("  mode            : %s" % ("APPLY" if args.apply else "DRY RUN"))
    print("  live now        : %d agents / %d records" % (len(live), live_recs))
    print("  agents to merge : %d" % len(plan))
    print("  records to add  : %d" % total_added)
    print("  result would be : %d records (gap %d -> 0)"
          % (live_recs + total_added, sum(len((v.get("records") or [])) for v in union.values()) - live_recs))
    if not args.apply:
        print("\n  DRY RUN complete. Re-run with --apply.")
        return 0

    if not args.no_backup:
        dest = LIVE + ".pre-reconcile-%s.bak" % time.strftime("%Y%m%dT%H%M%S")
        shutil.copy2(LIVE, dest)
        print("  backup          : %s" % os.path.basename(dest))

    fd = take_lock()
    if fd is None:
        print("  could not take the costs.json lock; refusing to write")
        return 2
    try:
        current = json.load(open(LIVE))  # re-read under the lock
        for aid, merged in plan.items():
            if merged is None:
                current[aid] = union[aid]
            else:
                fresh, _ = merge_agent(current.get(aid, {}), union[aid])
                current[aid] = fresh
        tfd, tmp = tempfile.mkstemp(dir=HIVE)
        with os.fdopen(tfd, "w") as f:
            json.dump(current, f)
        os.replace(tmp, LIVE)
    finally:
        release_lock(fd)

    after = json.load(open(LIVE))
    print("  live after      : %d agents / %d records" % (
        len(after), sum(len((v.get("records") or [])) for v in after.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
