import pathlib
import re

Q = chr(39)

p = pathlib.Path("lib/llm/cost.ts")
s = p.read_text(encoding="utf-8")
m = re.search(r"function saveCosts\(\) \{.*?\n\}", s, re.S)
assert m, "saveCosts not found in cost.ts"

new = (
    "function withLock<T>(fn: () => T): T | null {\n"
    "  const lockPath = COST_DB_PATH + '.lock';\n"
    "  const deadline = Date.now() + 5000;\n"
    "  let fd: number | null = null;\n"
    "  while (Date.now() < deadline) {\n"
    "    try {\n"
    "      fd = fs.openSync(lockPath, 'wx');\n"
    "      break;\n"
    "    } catch (e) {\n"
    "      if ((e as NodeJS.ErrnoException).code !== 'EEXIST') return null;\n"
    "      // A writer that died holding the lock must not wedge the database.\n"
    "      try {\n"
    "        if (Date.now() - fs.statSync(lockPath).mtimeMs > 30000) fs.unlinkSync(lockPath);\n"
    "      } catch (e2) { /* raced with another cleaner */ }\n"
    "    }\n"
    "  }\n"
    "  if (fd === null) return null;\n"
    "  try {\n"
    "    return fn();\n"
    "  } finally {\n"
    "    try { fs.closeSync(fd); } catch (e) { /* already closed */ }\n"
    "    try { fs.unlinkSync(lockPath); } catch (e) { /* already removed */ }\n"
    "  }\n"
    "}\n"
    "\n"
    "function saveCosts() {\n"
    "  const fs = require('fs');\n"
    "  // The lock is what makes read-merge-write safe across processes. Writing\n"
    "  // atomically stops a torn read, but two writers can still read the same\n"
    "  // base and the second one drops the first's records.\n"
    "  const done = withLock(() => {\n"
    "    let disk: Record<string, unknown>;\n"
    "    try {\n"
    "      disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {};\n"
    "      if (!disk || typeof disk !== 'object') disk = {};\n"
    "    } catch (e) {\n"
    "      console.warn('[CostTracker] costs.json unreadable, skipping save rather than clobbering it:', (e as Error).message);\n"
    "      return;\n"
    "    }\n"
    "    const data = { ...disk, ...Object.fromEntries(costCache) };\n"
    "    const tmp = COST_DB_PATH + '.tmp.' + process.pid;\n"
    "    fs.writeFileSync(tmp, JSON.stringify(data, null, 2));\n"
    "    fs.renameSync(tmp, COST_DB_PATH);\n"
    "  });\n"
    "  if (done === null) console.warn('[CostTracker] could not acquire costs.json lock, skipping save');\n"
    "}"
)

p.write_text(s[:m.start()] + new + s[m.end():], encoding="utf-8")
print("  cost.ts: withLock + saveCosts mirrored")
