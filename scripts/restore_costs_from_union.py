"""Restore cost history the clobbering destroyed, from the union archive.

The multi-writer clobber erased whole agents between f0d7912 landing and the
rolling restart completing. The union archive captured them. Now that every
live writer merges before writing, adding these back is safe: a merge never
removes keys, and if this write momentarily drops a concurrent addition, that
agent's own process re-adds it on its next write. The operation is therefore
self-healing.

Only agents present in the archive and absent from the live file are touched.
Nothing that exists live is overwritten.
"""
import json
import os
import tempfile

HIVE = "/Users/a/trading/openalice-fleet/hive"
LIVE = os.path.join(HIVE, "costs.json")
UNION = os.path.join(HIVE, "costs-union.json")


def main():
    live = json.load(open(LIVE))
    union = json.load(open(UNION))

    missing = [k for k in union if k not in live]
    if not missing:
        print("  nothing to restore")
        return 0

    restored = 0
    for k in missing:
        recs = union[k].get("records") or []
        live[k] = {
            "daily": union[k].get("daily"),
            "monthly": union[k].get("monthly"),
            "records": list(recs),
        }
        restored += len(recs)
        print("  restored %-18s %d records" % (k, len(recs)))

    fd, tmp = tempfile.mkstemp(dir=HIVE)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(live, f)
    os.replace(tmp, LIVE)

    print("  restored %d agents / %d records" % (len(missing), restored))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
