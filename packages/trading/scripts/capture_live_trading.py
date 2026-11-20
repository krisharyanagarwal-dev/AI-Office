import subprocess, time, os, json

HITS = []
END = time.time() + 90
seen = {}

while time.time() < END:
    out = subprocess.run("ps -eww -o pid=,ppid=,lstart=,args=",
                         shell=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "ALPHAINSIDER_TRADER_ENABLED=1" not in line:
            continue
        # skip this poller's own shell
        if "ps -eww" in line or "python" in line.split(" ")[0:2][0]:
            pass
        pid = line.split()[0]
        key = pid
        if key in seen:
            continue
        seen[key] = line
        HITS.append({
            "pid": pid,
            "ppid": line.split()[1],
            "cmdline": line[:400],
        })
    time.sleep(0.4)

print("== CAPTURED PROCESSES WITH ALPHAINSIDER_TRADER_ENABLED=1 ==")
if not HITS:
    print("  none observed in 90s")
for h in HITS:
    print("  pid=%s ppid=%s" % (h["pid"], h["ppid"]))
    print("    %s" % h["cmdline"][:300])
    print()

# Classify
print("== CLASSIFICATION ==")
prod = [h for h in HITS if "/agents/" in h["cmdline"] or "trader" in h["cmdline"].lower()]
test = [h for h in HITS if "pytest" in h["cmdline"] or "/tmp/" in h["cmdline"]]
print("  looks like production trading process : %d" % len(prod))
print("  looks like test/probe process         : %d" % len(test))
print()
if prod:
    print("  VERDICT: PRODUCTION PROCESS WITH LIVE TRADING ENABLED - investigate immediately")
elif test:
    print("  VERDICT: only test/probe processes - not a production safety breach")
else:
    print("  VERDICT: UNKNOWN - could not classify")
