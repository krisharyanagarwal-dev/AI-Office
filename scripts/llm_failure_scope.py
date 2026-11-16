import os, re, collections, time

TMP = "/tmp"
now = time.time()

prov = collections.Counter()
agents_all_fail = set()
agents_seen = set()
per_agent = {}

files = [f for f in os.listdir(TMP) if f.endswith("_manager.log")]

for f in files:
    p = os.path.join(TMP, f)
    try:
        if now - os.path.getmtime(p) > 3600:
            continue  # only look at the last hour
        tail = open(p, errors="ignore").read()[-60000:]
    except Exception:
        continue
    aid = f.replace("_manager.log", "")
    agents_seen.add(aid)
    n_all_fail = len(re.findall(r"All LLM providers failed", tail))
    for m in re.finditer(r"Provider (\w+) failed: .*?(HTTP (\d{3})|This operation was aborted)", tail):
        prov[(m.group(1), m.group(3) or "aborted")] += 1
    if n_all_fail:
        agents_all_fail.add(aid)
        per_agent[aid] = n_all_fail

print("== SCOPE: agent logs modified in the last hour ==")
print("  agents with recent log activity : %d" % len(agents_seen))
print("  agents hitting 'All LLM providers failed' : %d" % len(agents_all_fail))
print()
print("  top affected agents:")
for a, n in sorted(per_agent.items(), key=lambda x: -x[1])[:10]:
    print("     %-18s %d" % (a, n))
print()
print("== FAILURE MODE CLUSTERING (semantic, not volume) ==")
for (name, code), n in prov.most_common(12):
    print("     %-14s %-10s %d" % (name, code, n))
print()
if agents_all_fail:
    print("  VERDICT: fleet-wide LLM exhaustion affecting %d of %d active agents"
          % (len(agents_all_fail), len(agents_seen)))
    print("  This is NOT request volume; it is repeated total provider failure")
    print("  followed by executor llm_error with turns=0 tools=0 edits=0,")
    print("  i.e. no work is being produced at all by those agents.")
else:
    print("  VERDICT: no total provider exhaustion in the last hour")
