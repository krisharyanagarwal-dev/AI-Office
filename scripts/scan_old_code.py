import re, subprocess, datetime, collections, sys

FIX = 1758496690  # f0d7912 committed 2026-09-29 04:58:10 +0530

out = subprocess.check_output(["ps", "-eo", "pid=,lstart=,args="], text=True)

old = []
new = 0
skipped = []

for line in out.splitlines():
    if "node" not in line:
        continue
    p = line.split()
    if len(p) < 6:
        continue
    pid = p[0]
    lstart = " ".join(p[1:6])
    m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/([a-z_]+)\.js", line)
    label = m.group(1) + "/" + m.group(2) if m else "other"
    try:
        ts = int(subprocess.check_output(
            ["date", "-j", "-f", "%a %b %d %H:%M:%S %Y", lstart, "+%s"],
            text=True).strip())
    except Exception as e:
        skipped.append((pid, label, lstart, str(e)[:40]))
        continue
    if ts < FIX:
        old.append((label, pid, lstart, datetime.datetime.fromtimestamp(ts)))
    else:
        new += 1

print("  node processes on the fix : %d" % new)
print("  node processes BEFORE fix : %d" % len(old))
for label, pid, lstart, dt in sorted(old):
    print("     OLD  %-28s pid=%-7s started %s" % (label, pid, dt))
if skipped:
    print("  unparseable lstart (%d):" % len(skipped))
    for pid, label, lstart, err in skipped:
        print("     SKIP %-28s pid=%-7s %r" % (label, pid, lstart))
