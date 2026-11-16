import pathlib
import re

# --- cost.ts: same reset fix, in its own idiom -------------------------------
p = pathlib.Path("lib/llm/cost.ts")
s = p.read_text(encoding="utf-8")

m = re.search(r"function resetDailyCosts\(\) \{.*?\n\}", s, re.S)
m2 = re.search(r"function resetMonthlyCosts\(\) \{.*?\n\}", s, re.S)
assert m and m2, "reset functions not found in cost.ts"

new_ts = (
    "function resetPeriod(field: 'daily' | 'monthly') {\n"
    "  const fs = require('fs');\n"
    "  // Act on the document on disk, not this process's cache. Marking the cache\n"
    "  // dirty and saving would re-apply the boot-time snapshot for every agent, and\n"
    "  // a plain saveCosts() writes nothing now that only dirty agents are merged,\n"
    "  // so the reset would silently never persist.\n"
    "  withLock(() => {\n"
    "    let disk: Record<string, any>;\n"
    "    try {\n"
    "      disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {};\n"
    "    } catch (e) {\n"
    "      return;\n"
    "    }\n"
    "    if (!disk || typeof disk !== 'object') disk = {};\n"
    "    for (const v of Object.values(disk)) {\n"
    "      if (v && typeof v === 'object') (v as any)[field] = 0;\n"
    "    }\n"
    "    const tmp = COST_DB_PATH + '.tmp.' + process.pid;\n"
    "    fs.writeFileSync(tmp, JSON.stringify(disk, null, 2));\n"
    "    fs.renameSync(tmp, COST_DB_PATH);\n"
    "    for (const [k, v] of Object.entries(disk)) {\n"
    "      const c = costCache.get(k);\n"
    "      if (c) (c as any)[field] = 0;\n"
    "    }\n"
    "  });\n"
    "}\n"
    "function resetDailyCosts() { resetPeriod('daily'); }\n"
    "function resetMonthlyCosts() { resetPeriod('monthly'); }"
)

start, end = m.start(), m2.end()
s = s[:start] + new_ts + s[end:]
p.write_text(s, encoding="utf-8")
print("  cost.ts: resetPeriod mirrors the disk-based reset")
