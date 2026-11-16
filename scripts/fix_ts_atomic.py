import pathlib
import re

p = pathlib.Path("lib/llm/cost.ts")
s = p.read_text(encoding="utf-8")

m = re.search(r"function saveCosts\(\) \{.*?\n\}", s, re.S)
assert m, "saveCosts not found in cost.ts"
old = m.group(0)

Q = "'"
new = (
    "function saveCosts() {\n"
    "  try {\n"
    "    const fs = require(" + Q + "fs" + Q + ");\n"
    "    let disk: Record<string, unknown>;\n"
    "    try {\n"
    "      disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, " + Q + "utf8" + Q + ")) : {};\n"
    "      if (!disk || typeof disk !== " + Q + "object" + Q + ") disk = {};\n"
    "    } catch (e) {\n"
    "      // Unreadable means a writer was mid-write. Replacing the document now\n"
    "      // would drop every agent this process never loaded, so do not write.\n"
    "      console.warn(" + Q + "[CostTracker] costs.json unreadable, skipping save rather than clobbering it:" + Q + ", (e as Error).message);\n"
    "      return;\n"
    "    }\n"
    "    const data = { ...disk, ...Object.fromEntries(costCache) };\n"
    "    // Atomic: write a sibling temp file then rename, so a concurrent reader\n"
    "    // sees either the whole old document or the whole new one.\n"
    "    const tmp = COST_DB_PATH + " + Q + ".tmp." + Q + " + process.pid;\n"
    "    fs.writeFileSync(tmp, JSON.stringify(data, null, 2));\n"
    "    fs.renameSync(tmp, COST_DB_PATH);\n"
    "  } catch (e) {\n"
    "    console.warn(" + Q + "[CostTracker] Save failed:" + Q + ", (e as Error).message);\n"
    "  }\n"
    "}"
)

p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("  cost.ts: mirrored refuse-on-parse-failure + atomic rename write")
