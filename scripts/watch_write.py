import os, time, hashlib

P = "/Users/a/trading/openalice-fleet/hive/costs.json"

def s():
    st = os.stat(P)
    return st.st_ino, hashlib.sha256(open(P, "rb").read()).hexdigest()[:10]

prev = s()
print("  watching up to 240s for a real write; atomic rename must change the inode")
print("  t=0s ino=%d sha=%s" % prev)
seen = 0
rename = 0
inplace = 0
t0 = time.time()
while time.time() - t0 < 240 and seen < 6:
    time.sleep(0.4)
    cur = s()
    if cur[1] != prev[1]:
        seen += 1
        if cur[0] != prev[0]:
            rename += 1
            tag = "RENAME (atomic write active)"
        else:
            inplace += 1
            tag = "IN-PLACE (atomic write NOT active)"
        print("  t=%5.1fs ino=%-10d sha=%s  %s" % (time.time() - t0, cur[0], cur[1], tag))
        prev = cur
    elif cur[0] != prev[0]:
        print("  t=%5.1fs inode changed with same content (rename of identical data)" % (time.time() - t0))
        prev = cur

print()
print("  writes observed : %d" % seen)
print("  via rename      : %d" % rename)
print("  in place        : %d" % inplace)
if seen and rename == 0:
    print("  -> the running agents are NOT using the atomic write path")
elif seen:
    print("  -> atomic write path is active")
else:
    print("  -> no writes in the window; increase the observation time")
