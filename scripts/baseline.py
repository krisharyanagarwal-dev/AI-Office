import json, os, re, subprocess, datetime

HIVE = "/Users/a/trading/openalice-fleet/hive"
OUTER = "/Users/a/trading/openalice-fleet"
FIX = "17669a9"  # the atomic-write fix that must end up loaded

def sh(cmd, cwd=None):
    return subprocess.check_output(cmd, shell=True, cwd=cwd, text=True).strip()

print("== REPOS ==")
for name, d in (("outer", OUTER), ("hive", HIVE)):
    head = sh("git log -1 --format='%h %s'", cwd=d)[:58]
    unpushed = sh("git log --oneline @{u}..HEAD 2>/dev/null | wc -l | tr -d ' '", cwd=d)
    mod = sh("git status --porcelain | grep -c '^ M'", cwd=d)
    print("  %-5s HEAD=%s" % (name, head))
    print("        unpushed=%s  foreign_modified=%s" % (unpushed, mod))

print("\n== FLEET ==")
mgrs = sh("pgrep -f agent_manager.js | wc -l | tr -d ' '")
allnode = sh("pgrep -f 'node.*openalice-fleet' | wc -l | tr -d ' '")
print("  agent_manager processes : %s" % mgrs)
print("  all openalice node procs: %s" % allnode)

print("\n== TRADING SAFETY ==")
ps = sh("ps -eww -o args=")
live1 = ps.count("ALPHAINSIDER_TRADER_ENABLED=1")
live0 = ps.count("ALPHAINSIDER_TRADER_ENABLED=0")
print("  ALPHAINSIDER_TRADER_ENABLED=1 processes: %d  (must be 0)" % live1)
print("  ALPHAINSIDER_TRADER_ENABLED=0 processes: %d" % live0)
print("  TRADER LOCKED: %s" % (live1 == 0))

print("\n== COST LEDGER ==")
u = json.load(open(os.path.join(HIVE, "costs-union.json")))
l = json.load(open(os.path.join(HIVE, "costs.json")))
uc = {k: len((v.get("records") or [])) for k, v in u.items()}
lc = {k: len((v.get("records") or [])) for k, v in l.items()}
behind = sorted(k for k in u if lc.get(k, 0) < uc[k])
print("  ARCHIVE : %d ids / %d records" % (len(u), sum(uc.values())))
print("  LIVE    : %d ids / %d records" % (len(l), sum(lc.values())))
print("  GAP     : %d records across %d agents" % (sum(uc.values()) - sum(lc.values()), len(behind)))
print("  newest live record: %s" % max(
    (r.get("timestamp") or "") for v in l.values() for r in (v.get("records") or [])))

print("\n== STALE WRITER MAP (who has the pre-fix module) ==")
fix_ct = int(sh("git log -1 --format=%%ct %s" % FIX, cwd=HIVE))
prev_ct = int(sh("git log -1 --format=%%ct f0d7912", cwd=HIVE))
psout = sh("ps -eo pid=,lstart=,args=")
stale_prev, stale_now = [], []
for line in psout.splitlines():
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
    if ts < prev_ct:
        stale_prev.append((m.group(1) + "/" + m.group(2), p[0], ts))
    elif ts < fix_ct:
        stale_now.append((m.group(1) + "/" + m.group(2), p[0], ts))
print("  need restart (pre f0d7912 merge): %d" % len(stale_prev))
for a, p, t in sorted(stale_prev):
    print("     %-34s pid=%-7s started %s" % (a, p, datetime.datetime.fromtimestamp(t).strftime("%m-%d %H:%M:%S")))
print("  need restart (pre %s atomic fix): %d" % (FIX[:7], len(stale_now)))
for a, p, t in sorted(stale_now):
    print("     %-34s pid=%-7s started %s" % (a, p, datetime.datetime.fromtimestamp(t).strftime("%m-%d %H:%M:%S")))
