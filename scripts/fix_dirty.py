import pathlib

p = pathlib.Path("lib/llm/cost.js")
s = p.read_text(encoding="utf-8")

# 1. Track which agents this process has actually changed.
old_cache = "let costCache = new Map();"
new_cache = ("let costCache = new Map();\n"
             "// Agents this process has modified since loadCosts(). loadCosts() pulls in EVERY\n"
             "// agent, so without this a process re-applies its whole startup snapshot on each\n"
             "// save and silently reverts every other agent's newer records.\n"
             "const dirtyAgents = new Set();")
assert s.count(old_cache) == 1, "costCache anchor"
s = s.replace(old_cache, new_cache, 1)

# 2. recordCost marks its agent dirty.
old_rec = "  cache.daily += cost; cache.monthly += cost; saveCosts(); return cost;"
new_rec = "  cache.daily += cost; cache.monthly += cost; dirtyAgents.add(agentId); saveCosts(); return cost;"
assert s.count(old_rec) == 1, "recordCost anchor"
s = s.replace(old_rec, new_rec, 1)

# 3. saveCosts merges ONLY the dirty entries, then clears them.
old_merge = "for (const [k, v] of costCache) disk[k] = v; "
new_merge = ("for (const k of dirtyAgents) { if (costCache.has(k)) disk[k] = costCache.get(k); } "
             "dirtyAgents.clear(); ")
assert s.count(old_merge) == 1, "merge anchor"
s = s.replace(old_merge, new_merge, 1)

p.write_text(s, encoding="utf-8")
print("  cost.js: saveCosts now merges only self-modified agents, then clears the set")
