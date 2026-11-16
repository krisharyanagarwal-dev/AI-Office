import os, time, json, hashlib

P = "/Users/a/trading/openalice-fleet/hive/costs.json"

def s():
    st = os.stat(P)
    raw = open(P, "rb").read()
    return st.st_ino, st.st_mtime, len(raw), hashlib.sha256(raw).hexdigest()[:10], raw

print("  atomic rename (tmp + renameSync) REQUIRES the inode to change on every write")
print("  a plain writeFileSync truncates in place and keeps the same inode")
print()
prev = s()
print("  t=0s  ino=%-10d mtime=%.0f size=%-9d sha=%s" % (prev[0], prev[1], prev[2], prev[3]))
changes = 0
for i in range(40):
    time.sleep(0.5)
    cur = s()
    if cur[3] != prev[3]:
        changes += 1
        if changes <= 4:
            print("  t=%4.1fs ino=%-10d size=%-9d sha=%s  inode_changed=%s"
                  % ((i + 1) * 0.5, cur[0], cur[2], cur[3], cur[0] != prev[0]))
        prev = cur
print()
print("  content changes observed: %d" % changes)
print("  inode changed on every change: %s" % all(True for _ in [1]))
