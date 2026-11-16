import pathlib

p = pathlib.Path("lib/llm/cost.ts")
s = p.read_text(encoding="utf-8")

# 1. dirty set, next to the cache declaration (which is typed, not "new Map()")
anchor = "let costCache: Map<string, { daily: number; monthly: number; records: CostRecord[] }> = new Map()"
assert s.count(anchor) == 1, "cache decl anchor"
s = s.replace(anchor, anchor + "\n"
              "// Agents this process has modified since load. loadCosts() pulls in every agent,\n"
              "// so without this a process re-applies its whole boot-time snapshot on save and\n"
              "// reverts every other agent's newer records.\n"
              "const dirtyAgents = new Set<string>()", 1)

# 2. recordCost marks its agent dirty
old_rec = "  cache.daily += cost;\n  cache.monthly += cost;\n  \n  saveCosts();\n  return cost;"
new_rec = "  cache.daily += cost;\n  cache.monthly += cost;\n  dirtyAgents.add(agentId);\n  saveCosts();\n  return cost;"
assert s.count(old_rec) == 1, "recordCost anchor %d" % s.count(old_rec)
s = s.replace(old_rec, new_rec, 1)

# 3. merge only dirty entries
old_merge = "    const data = { ...disk, ...Object.fromEntries(costCache) };"
new_merge = ("    for (const k of dirtyAgents) {\n"
             "      if (costCache.has(k)) disk[k] = costCache.get(k);\n"
             "    }\n"
             "    dirtyAgents.clear();\n"
             "    const data = disk;")
assert s.count(old_merge) == 1, "merge anchor"
s = s.replace(old_merge, new_merge, 1)

p.write_text(s, encoding="utf-8")
print("  cost.ts: dirtyAgents tracking mirrored")
