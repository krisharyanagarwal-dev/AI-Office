import pathlib

# 57 processes each hold a partial in-memory cache snapshotted at their own
# startup, and saveCosts() wrote the WHOLE file from that snapshot. Any entry
# another process added after our snapshot was silently reverted, and any agent
# whose data we never loaded was erased outright. Measured: F4 lost all 473
# records in a 30s window.
#
# Fix: re-read the file immediately before writing and merge our entries over
# it, so we only ever add or update keys we actually own. Format is unchanged.
OLD = ("function saveCosts() { try { fs.writeFileSync(COST_DB_PATH, JSON.stringify(Object.fromEntries(costCache), null, 2)); "
       "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")

NEW = ("function saveCosts() { try { let disk = {}; try { if (fs.existsSync(COST_DB_PATH)) disk = JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) || {}; } catch (e) {} "
       "for (const [k, v] of costCache) disk[k] = v; "
       "fs.writeFileSync(COST_DB_PATH, JSON.stringify(disk, null, 2)); "
       "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")

for name in ("lib/llm/cost.js", "lib/llm/cost.ts"):
    p = pathlib.Path(name)
    s = p.read_text(encoding="utf-8")
    if OLD in s:
        assert s.count(OLD) == 1
        p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
        print("  %s: saveCosts now merges before writing" % name)
    else:
        print("  %s: no matching saveCosts, skipping" % name)
