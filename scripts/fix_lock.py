import pathlib

OLD = ("function saveCosts() { try { let disk; "
       "try { disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {}; "
       "if (!disk || typeof disk !== 'object') disk = {}; } catch (e) { "
       "console.warn('[CostTracker] costs.json unreadable, skipping save rather than clobbering it:', e.message); return; } "
       "for (const [k, v] of costCache) disk[k] = v; "
       "const tmp = COST_DB_PATH + '.tmp.' + process.pid; "
       "fs.writeFileSync(tmp, JSON.stringify(disk, null, 2)); fs.renameSync(tmp, COST_DB_PATH); "
       "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")

NEW = (
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

p = pathlib.Path("lib/llm/cost.js")
s = p.read_text(encoding="utf-8")
assert s.count(OLD) == 1, "anchor count = %d" % s.count(OLD)
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  cost.js: saveCosts now holds an exclusive lock across read-merge-write")
