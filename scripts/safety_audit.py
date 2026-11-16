import json, os, subprocess, time

def sh(c):
    return subprocess.check_output(c, shell=True, text=True).strip()

print("== SAFETY EVIDENCE ==")
vals = []
for i in range(8):
    n = sh("ps -eww -o args= | grep -c '[A]LPHAINSIDER_TRADER_ENABLED=1'")
    vals.append(int(n))
    time.sleep(2)
print("  ENABLED=1 process count over 16s : %s" % vals)
print("  max observed                      : %d" % max(vals))

print()
print("== ACTIVE TRADER CONFIG ==")
p = os.path.expanduser("~/Library/LaunchAgents/com.aryan.openalice-alphainsider-trader.plist")
try:
    txt = open(p).read()
    import re
    m = re.search(r"ALPHAINSIDER_TRADER_ENABLED</key>\s*<string>([01])</string>", txt)
    print("  loaded plist value               : %s" % (m.group(1) if m else "NOT FOUND"))
except Exception as e:
    print("  could not read plist: %s" % e)

print()
print("== LAUNCHD JOBS ==")
out = sh("launchctl list | grep alphainsider")
for line in out.splitlines():
    f = line.split()
    pid, status, label = f[0], f[1], f[2]
    print("  %-46s pid=%-4s last_exit=%s" % (label, pid, status))

print()
print("== BACKUP PLISTS (historical, not loaded) ==")
import glob
for f in sorted(glob.glob(os.path.expanduser("~/Library/LaunchAgents/*alphainsider-trader*"))):
    txt = open(f).read()
    m = re.search(r"ALPHAINSIDER_TRADER_ENABLED</key>\s*<string>([01])</string>", txt)
    print("  %-58s value=%s" % (os.path.basename(f), m.group(1) if m else "?"))

print()
print("== VERDICT ==")
print("  live trading processes right now : %d" % vals[-1])
print("  max during window                 : %d" % max(vals))
print("  active plist says                 : %s" % ("0 = disabled" if (m and m.group(1) == "0") else "CHECK"))
