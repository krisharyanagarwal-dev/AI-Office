import hashlib, json, os, time

P = "/Users/a/trading/openalice-fleet/hive/costs.json"

def snap():
    try:
        st = os.stat(P)
        raw = open(P, "rb").read()
        d = json.loads(raw)
        return {
            "t": time.time(),
            "ino": st.st_ino,
            "size": st.st_size,
            "sha": hashlib.sha256(raw).hexdigest()[:12],
            "ids": set(d.keys()),
            "counts": {k: len((v.get("records") or [])) for k, v in d.items()},
            "total": sum(len(v.get("records") or []) for v in d.values()),
        }
    except Exception as e:
        return {"t": time.time(), "error": str(e)}

a = snap()
print("  t=0s  ids=%d total=%d sha=%s ino=%s" % (len(a["ids"]), a["total"], a["sha"], a["ino"]))
time.sleep(30)
b = snap()
print("  t=30s ids=%d total=%d sha=%s ino=%s" % (len(b["ids"]), b["total"], b["sha"], b["ino"]))

print()
print("  file rewritten in 30s :", a["sha"] != b["sha"])
print("  inode changed        :", a["ino"] != b["ino"], "(write-then-rename)")
print("  ids ADDED   :", sorted(b["ids"] - a["ids"]))
print("  ids REMOVED :", sorted(a["ids"] - b["ids"]), "  <-- data destroyed" if a["ids"] - b["ids"] else "")
print()
print("  per-agent record count changes (negative = LOST):")
lost = 0
for k in sorted(a["ids"] | b["ids"]):
    x, y = a["counts"].get(k), b["counts"].get(k)
    if x != y:
        d = (y or 0) - (x or 0)
        lost += max(0, -(d))
        print("    %-16s %6s -> %6s  (%+d)" % (k, x, y, d))
print("  total records LOST in 30s:", lost)
