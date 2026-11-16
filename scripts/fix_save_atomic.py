import pathlib

OLD = ("function saveCosts() { try { let disk = {}; try { if (fs.existsSync(COST_DB_PATH)) disk = JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) || {}; } catch (e) {} "
       "for (const [k, v] of costCache) disk[k] = v; "
       "fs.writeFileSync(COST_DB_PATH, JSON.stringify(disk, null, 2)); "
       "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")

NEW = (
    "function saveCosts() { try { let disk; "
    "try { disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {}; "
    "if (!disk || typeof disk !== 'object') disk = {}; } catch (e) { "
    "console.warn('[CostTracker] costs.json unreadable, skipping save rather than clobbering it:', e.message); return; } "
    "for (const [k, v] of costCache) disk[k] = v; "
    "const tmp = COST_DB_PATH + '.tmp.' + process.pid; "
    "fs.writeFileSync(tmp, JSON.stringify(disk, null, 2)); fs.renameSync(tmp, COST_DB_PATH); "
    "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }"
)

p = pathlib.Path("lib/llm/cost.js")
s = p.read_text(encoding="utf-8")
assert s.count(OLD) == 1, "cost.js anchor count = %d" % s.count(OLD)
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  cost.js: saveCosts refuses to write on parse failure, and writes atomically")
