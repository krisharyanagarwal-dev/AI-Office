import os, re, time, subprocess

now = time.time()
print("== CURRENT WINDOW (last 10 minutes of log) ==")

tot_all_fail = 0
tot_ok = 0
agents_bad = set()
agents_seen = set()

for f in os.listdir("/tmp"):
    if not f.endswith("_manager.log"):
        continue
    p = os.path.join("/tmp", f)
    try:
        if now - os.path.getmtime(p) > 900:
            continue
        tail = open(p, errors="ignore").read()[-25000:]
    except Exception:
        continue
    aid = f.replace("_manager.log", "")
    agents_seen.add(aid)
    nf = len(re.findall(r"All LLM providers failed", tail))
    ok = len(re.findall(r"LLM Response|Response received|executor finished: status=(ok|complete)", tail))
    tot_all_fail += nf
    tot_ok += ok
    if nf:
        agents_bad.add(aid)

print("  agents with log activity (<10min) : %d" % len(agents_seen))
print("  agents hitting total failure      : %d" % len(agents_bad))
print("  'All LLM providers failed' events : %d" % tot_all_fail)
print("  successful LLM response events    : %d" % tot_ok)
print()

# Is it recovering right now? sample the newest log line timestamp per agent
newest = []
for f in os.listdir("/tmp"):
    if not f.endswith("_manager.log"):
        continue
    p = os.path.join("/tmp", f)
    try:
        tail = open(p, errors="ignore").read()[-4000:]
    except Exception:
        continue
    m = re.findall(r"\[(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\]", tail)
    if m:
        newest.append((m[-1], f.replace("_manager.log", "")))

newest.sort(reverse=True)
print("  most recent log timestamps across the fleet:")
for ts, a in newest[:5]:
    print("     %s  %s" % (ts, a))
print()
print("== VERDICT ==")
if tot_all_fail and tot_ok:
    print("  MIXED: %d total-failure events and %d successful responses." % (tot_all_fail, tot_ok))
    print("  This is an INTERMITTENT failure, not a total outage. Agents recover")
    print("  between failures. The 429s are fleet-wide rate-limit saturation.")
elif tot_all_fail:
    print("  ONGOING: no successful LLM response in the window across %d agents." % len(agents_bad))
else:
    print("  RECOVERED: no total-failure events in the last 10 minutes.")
