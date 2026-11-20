import json

b = json.load(open("/tmp/costs.pre-cleanup.bak"))
c = json.load(open("/Users/a/trading/openalice-fleet/hive/costs.json"))

s15 = b.get("specialist-15") or {}
print("  backup has specialist-15 :", "specialist-15" in b,
      "->", len(s15.get("records") or []), "records")
print("  current has specialist-15:", "specialist-15" in c)
print("  backup agentIds:", len(b), "| current agentIds:", len(c))
print("  ids LOST vs backup:", sorted(set(b) - set(c)))
print("  ids NEW  vs backup:", sorted(set(c) - set(b)))
print()
print("  per-agent record counts, backup -> current:")
for k in sorted(set(b) | set(c)):
    nb = len(((b.get(k) or {}).get("records")) or [])
    nc = len(((c.get(k) or {}).get("records")) or [])
    flag = "" if nb == nc else "   <-- CHANGED"
    print("    %-16s %6d -> %6d%s" % (k, nb, nc, flag))
