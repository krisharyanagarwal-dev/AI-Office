import pathlib
import re

Q = chr(39)

# Build HEAD + the lock fix for both files, excluding the other session's
# freeHarness pricing edit which must stay uncommitted.

JS_OLD = ("function saveCosts() { try { let disk; "
          "try { disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {}; "
          "if (!disk || typeof disk !== 'object') disk = {}; } catch (e) { "
          "console.warn('[CostTracker] costs.json unreadable, skipping save rather than clobbering it:', e.message); return; } "
          "for (const [k, v] of costCache) disk[k] = v; "
          "const tmp = COST_DB_PATH + '.tmp.' + process.pid; "
          "fs.writeFileSync(tmp, JSON.stringify(disk, null, 2)); fs.renameSync(tmp, COST_DB_PATH); "
          "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")

JS_WITH_LOCK = (
    "function withLock(fn) { const lockPath = COST_DB_PATH + '.lock'; const deadline = Date.now() + 5000; let fd = null; "
    "while (Date.now() < deadline) { try { fd = fs.openSync(lockPath, 'wx'); break; } catch (e) { "
    "if (e.code !== 'EEXIST') return false; "
    "try { if (Date.now() - fs.statSync(lockPath).mtimeMs > 30000) fs.unlinkSync(lockPath); } catch (e2) {} "
    "const spin = Date.now() + 3; while (Date.now() < spin) {} } } "
    "if (fd === null) return false; "
    "try { return fn(); } finally { try { fs.closeSync(fd); } catch (e) {} try { fs.unlinkSync(lockPath); } catch (e) {} } } "
    "function saveCosts() { const done = withLock(() => { try { let disk; "
    "try { disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {}; "
    "if (!disk || typeof disk !== 'object') disk = {}; } catch (e) { "
    "console.warn('[CostTracker] costs.json unreadable, skipping save rather than clobbering it:', e.message); return; } "
    "for (const [k, v] of costCache) disk[k] = v; "
    "const tmp = COST_DB_PATH + '.tmp.' + process.pid; "
    "fs.writeFileSync(tmp, JSON.stringify(disk, null, 2)); fs.renameSync(tmp, COST_DB_PATH); } catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }); "
    "if (!done) console.warn('[CostTracker] could not acquire costs.json lock, skipping save'); }"
)

js = pathlib.Path("/tmp/h.js")
s = js.read_text()
assert s.count(JS_OLD) == 1, "js anchor %d" % s.count(JS_OLD)
js.write_text(s.replace(JS_OLD, JS_WITH_LOCK, 1))
print("  js staged copy has withLock")

ts = pathlib.Path("/tmp/h.ts")
s = ts.read_text()
m = re.search(r"function saveCosts\(\) \{.*?\n\}", s, re.S)
assert m, "ts saveCosts not found"
new_ts = (
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
ts.write_text(s[:m.start()] + new_ts + s[m.end():])
print("  ts staged copy has withLock")
