set -e
cd /Users/a/trading/openalice-fleet/hive

# Build HEAD + my change only, so the other session's freeHarness edit stays
# uncommitted and un-staged in the worktree.
git show HEAD:lib/llm/cost.js > /tmp/h.js
git show HEAD:lib/llm/cost.ts > /tmp/h.ts

python3 - <<'PY'
import pathlib

js = pathlib.Path("/tmp/h.js"); s = js.read_text()
js_old = "function calculateCost(provider, model, usage) { const pricing = PRICING[provider]?.[model] || { input: 0.0004, output: 0.0004 }; return (usage.promptTokens * pricing.input + usage.completionTokens * pricing.output) / 1000; }"
js_new = ("function tokenCount(usage, snake, camel) { if (!usage) return 0; const v = usage[snake] != null ? usage[snake] : usage[camel]; const n = Number(v); return Number.isFinite(n) ? n : 0; }\n"
           "function calculateCost(provider, model, usage) { const pricing = PRICING[String(provider).toLowerCase()]?.[model] || { input: 0.0004, output: 0.0004 }; return (tokenCount(usage,'prompt_tokens','promptTokens') * pricing.input + tokenCount(usage,'completion_tokens','completionTokens') * pricing.output) / 1000; }")
assert s.count(js_old) == 1
js.write_text(s.replace(js_old, js_new, 1))

ts = pathlib.Path("/tmp/h.ts"); s = ts.read_text()
s = s.replace("PRICING[provider]?.[model]", "PRICING[String(provider).toLowerCase()]?.[model]", 1)
s = s.replace("  return (usage.promptTokens * pricing.input + usage.completionTokens * pricing.output) / 1000;",
              "  return (tokenCount(usage, 'prompt_tokens', 'promptTokens') * pricing.input + tokenCount(usage, 'completion_tokens', 'completionTokens') * pricing.output) / 1000;", 1)
s = s.replace("function calculateCost(",
              "function tokenCount(usage: unknown, snake: string, camel: string): number {\n  if (!usage || typeof usage !== 'object') return 0;\n  const rec = usage as Record<string, unknown>;\n  const v = rec[snake] != null ? rec[snake] : rec[camel];\n  const n = Number(v);\n  return Number.isFinite(n) ? n : 0;\n}\n\nfunction calculateCost(", 1)
s = s.replace("function calculateCost(provider: string, model: string, usage: { promptTokens: number; completionTokens: number }):",
              "function calculateCost(provider: string, model: string, usage: { promptTokens?: number; completionTokens?: number; prompt_tokens?: number; completion_tokens?: number } | null | undefined):", 1)
ts.write_text(s)
print("  built clean HEAD+fix copies")
PY

BJ=$(git hash-object -w /tmp/h.js); BT=$(git hash-object -w /tmp/h.ts)
MJ=$(git ls-files -s lib/llm/cost.js | awk '{print $1}'); MT=$(git ls-files -s lib/llm/cost.ts | awk '{print $1}')
git update-index --cacheinfo "$MJ,$BJ,lib/llm/cost.js"
git update-index --cacheinfo "$MT,$BT,lib/llm/cost.ts"
rm -f /tmp/h.js /tmp/h.ts
git add -- lib/llm/test/cost_usage_schema.test.js

echo "  --- staged files ---"
git diff --cached --name-only | sed 's/^/    /'
echo "  --- their edit must NOT be staged ---"
git diff --cached lib/llm/cost.js | grep -c "kimi-k3" | sed 's/^/    kimi-k3 occurrences in staged js: /'
echo "  --- worktree still holds their edit ---"
grep -c "moonshotai/kimi-k3" lib/llm/cost.js lib/llm/cost.ts | sed 's/^/    /'
git diff --check && echo "    whitespace clean"
