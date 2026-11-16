set -e
cd /Users/a/trading/openalice-fleet/hive

# Build a patch containing ONLY the .unref() change, against HEAD, so the
# other session's freeHarness edit stays uncommitted and un-staged.
git show HEAD:lib/llm/cost.js > /tmp/h_cost.js
git show HEAD:lib/llm/cost.ts > /tmp/h_cost.ts

python3 - <<'PY'
import pathlib
js = pathlib.Path("/tmp/h_cost.js")
s = js.read_text()
old = "}, 60000);"
new = "}, 60000).unref();"
assert s.count(old) == 1, s.count(old)
js.write_text(s.replace(old, new, 1))

ts = pathlib.Path("/tmp/h_cost.ts")
s = ts.read_text()
assert s.count(old) == 1, s.count(old)
ts.write_text(s.replace(old, new, 1))
print("  built clean HEAD+unref copies")
PY

# Stage those blobs directly into the index, leaving the worktree alone.
BLOB_JS=$(git hash-object -w /tmp/h_cost.js)
BLOB_TS=$(git hash-object -w /tmp/h_cost.ts)
MODE_JS=$(git ls-files -s lib/llm/cost.js | awk '{print $1}')
MODE_TS=$(git ls-files -s lib/llm/cost.ts | awk '{print $1}')
git update-index --cacheinfo "$MODE_JS,$BLOB_JS,lib/llm/cost.js"
git update-index --cacheinfo "$MODE_TS,$BLOB_TS,lib/llm/cost.ts"
rm -f /tmp/h_cost.js /tmp/h_cost.ts

echo "  --- STAGED diff (must contain ONLY .unref) ---"
git diff --cached lib/llm/cost.js lib/llm/cost.ts | grep -E "^[+-]" | grep -v "^[+-][+-]" | cut -c1-110 | sed 's/^/    /'
echo "  --- staged file count ---"
git diff --cached --name-only | sed 's/^/    /'
