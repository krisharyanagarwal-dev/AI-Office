set -e
cd /Users/a/trading/openalice-fleet/hive

git show HEAD:lib/llm/cost.js > /tmp/h.js
git show HEAD:lib/llm/cost.ts > /tmp/h.ts

python3 - <<'PY'
import pathlib

js = pathlib.Path("/tmp/h.js"); s = js.read_text()
old = ("function saveCosts() { try { fs.writeFileSync(COST_DB_PATH, JSON.stringify(Object.fromEntries(costCache), null, 2)); "
       "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")
new = ("function saveCosts() { try { let disk = {}; try { if (fs.existsSync(COST_DB_PATH)) disk = JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) || {}; } catch (e) {} "
       "for (const [k, v] of costCache) disk[k] = v; "
       "fs.writeFileSync(COST_DB_PATH, JSON.stringify(disk, null, 2)); "
       "} catch (e) { console.warn('[CostTracker] Save failed:', e.message); } }")
assert s.count(old) == 1, "js saveCosts anchor %d" % s.count(old)
js.write_text(s.replace(old, new, 1))

ts = pathlib.Path("/tmp/h.ts"); s = ts.read_text()
old_ts = """function saveCosts() {
  try {
    const fs = require('fs');
    const data = Object.fromEntries(costCache);
    fs.writeFileSync(COST_DB_PATH, JSON.stringify(data, null, 2));"""
new_ts = """function saveCosts() {
  try {
    const fs = require('fs');
    let disk: Record<string, unknown> = {};
    try {
      if (fs.existsSync(COST_DB_PATH)) {
        disk = JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) || {};
      }
    } catch (e) {
      disk = {};
    }
    const data = { ...disk, ...Object.fromEntries(costCache) };
    fs.writeFileSync(COST_DB_PATH, JSON.stringify(data, null, 2));"""
assert s.count(old_ts) == 1, "ts saveCosts anchor %d" % s.count(old_ts)
ts.write_text(s.replace(old_ts, new_ts, 1))
print("  built clean HEAD+merge-fix copies")
PY

BJ=$(git hash-object -w /tmp/h.js); BT=$(git hash-object -w /tmp/h.ts)
MJ=$(git ls-files -s lib/llm/cost.js | awk '{print $1}'); MT=$(git ls-files -s lib/llm/cost.ts | awk '{print $1}')
git update-index --cacheinfo "$MJ,$BJ,lib/llm/cost.js"
git update-index --cacheinfo "$MT,$BT,lib/llm/cost.ts"
rm -f /tmp/h.js /tmp/h.ts
git add -- lib/llm/test/cost_multiwriter.test.js

echo "  --- staged ---"
git diff --cached --name-only | sed 's/^/    /'
echo "  --- foreign edit must NOT be staged (expect 0) ---"
git diff --cached lib/llm/cost.js | grep -c "kimi-k3" | sed 's/^/    kimi-k3 in staged js: /'
echo "  --- foreign edit still in worktree (expect 1) ---"
grep -c "moonshotai/kimi-k3" lib/llm/cost.js lib/llm/cost.ts | sed 's/^/    /'
git diff --check && echo "    whitespace clean"
