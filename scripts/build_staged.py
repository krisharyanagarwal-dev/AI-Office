import pathlib
import re

# Build HEAD + my saveCosts fix for both files, so the other session's
# freeHarness pricing edit stays uncommitted and un-staged.

Q = chr(39)

JS_OLD = ("function saveCosts() { try { let disk = {}; try { if (fs.existsSync(COST_DB_PATH)) disk = JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) || {}; } catch (e) {} "
          "for (const [k, v] of costCache) disk[k] = v; "
          "fs.writeFileSync(COST_DB_PATH, JSON.stringify(disk, null, 2)); "
          "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")
JS_NEW = ("function saveCosts() { try { let disk; "
          "try { disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {}; "
          "if (!disk || typeof disk !== 'object') disk = {}; } catch (e) { "
          "console.warn('[CostTracker] costs.json unreadable, skipping save rather than clobbering it:', e.message); return; } "
          "for (const [k, v] of costCache) disk[k] = v; "
          "const tmp = COST_DB_PATH + '.tmp.' + process.pid; "
          "fs.writeFileSync(tmp, JSON.stringify(disk, null, 2)); fs.renameSync(tmp, COST_DB_PATH); "
          "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")

js = pathlib.Path("/tmp/h.js")
s = js.read_text()
assert s.count(JS_OLD) == 1, "js anchor %d" % s.count(JS_OLD)
js.write_text(s.replace(JS_OLD, JS_NEW, 1))

ts = pathlib.Path("/tmp/h.ts")
s = ts.read_text()
m = re.search(r"function saveCosts\(\) \{.*?\n\}", s, re.S)
assert m, "ts saveCosts not found"
new_ts = (
    "function saveCosts() {\n"
    "  try {\n"
    "    const fs = require('fs');\n"
    "    let disk: Record<string, unknown>;\n"
    "    try {\n"
    "      disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {};\n"
    "      if (!disk || typeof disk !== 'object') disk = {};\n"
    "    } catch (e) {\n"
    "      // Unreadable means a writer was mid-write. Replacing the document now\n"
    "      // would drop every agent this process never loaded, so do not write.\n"
    "      console.warn('[CostTracker] costs.json unreadable, skipping save rather than clobbering it:', (e as Error).message);\n"
    "      return;\n"
    "    }\n"
    "    const data = { ...disk, ...Object.fromEntries(costCache) };\n"
    "    // Atomic: write a sibling temp file then rename, so a concurrent reader\n"
    "    // sees either the whole old document or the whole new one.\n"
    "    const tmp = COST_DB_PATH + '.tmp.' + process.pid;\n"
    "    fs.writeFileSync(tmp, JSON.stringify(data, null, 2));\n"
    "    fs.renameSync(tmp, COST_DB_PATH);\n"
    "  } catch (e) {\n"
    "    console.warn('[CostTracker] Save failed:', (e as Error).message);\n"
    "  }\n"
    "}"
)
ts.write_text(s[:m.start()] + new_ts + s[m.end():])
print("  built clean HEAD+fix copies for both files")
