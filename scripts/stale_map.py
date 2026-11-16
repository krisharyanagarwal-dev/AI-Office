import re, subprocess, datetime

HIVE = "/Users/a/trading/openalice-fleet/hive"
FIX = "17669a9"      # atomic-write fix that must end up loaded
MERGE = "f0d7912"    # earlier merge fix

def ct(ref):
    return int(subprocess.check_output(
        ["git", "-C", HIVE, "log", "-1", "--format=%ct", ref], text=True).strip())

merge_ct, fix_ct = ct(MERGE), ct(FIX)
print("  f0d7912 (merge)   %s" % datetime.datetime.fromtimestamp(merge_ct).strftime("%Y-%m-%d %H:%M:%S"))
print("  17669a9 (atomic)  %s" % datetime.datetime.fromtimestamp(fix_ct).strftime("%Y-%m-%d %H:%M:%S"))

# is the fix still reachable from HEAD after other agents committed?
ok = subprocess.run(["git", "-C", HIVE, "merge-base", "--is-ancestor", FIX, "HEAD"]).returncode == 0
print("  17669a9 still an ancestor of HEAD: %s" % ok)

out = subprocess.check_output(["ps", "-eo", "pid=,lstart=,args="], text=True)
need_merge, need_atomic, current = [], [], []
for line in out.splitlines():
    m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/([a-z_]+)\.js", line)
    if not m:
        continue
    p = line.split()
    lstart = " ".join(p[1:6])
    try:
        ts = int(subprocess.check_output(
            ["date", "-j", "-f", "%a %b %d %H:%M:%S %Y", lstart, "+%s"], text=True).strip())
    except Exception:
        continue
    rec = (m.group(1) + "/" + m.group(2), int(p[0]), ts)
    if ts < merge_ct:
        need_merge.append(rec)
    elif ts < fix_ct:
        need_atomic.append(rec)
    else:
        current.append(rec)

def show(title, rows):
    print("\n  %s: %d" % (title, len(rows)))
    for a, p, t in sorted(rows):
        print("     %-34s pid=%-7s started %s" % (a, p, datetime.datetime.fromtimestamp(t).strftime("%m-%d %H:%M:%S")))

show("ON the atomic fix (no action needed)", current)
show("pre-f0d7912 merge (clobbers, needs restart)", need_merge)
show("pre-17669a9 atomic (parse-hole, needs restart)", need_atomic)
print("\n  TOTAL needing restart: %d" % (len(need_merge) + len(need_atomic)))
