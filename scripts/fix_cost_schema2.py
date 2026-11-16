import pathlib

# --- runtime: lib/llm/cost.js -------------------------------------------
JS = pathlib.Path("lib/llm/cost.js")
js = JS.read_text(encoding="utf-8")

js_old = "function calculateCost(provider, model, usage) { const pricing = PRICING[provider]?.[model] || { input: 0.0004, output: 0.0004 }; return (usage.promptTokens * pricing.input + usage.completionTokens * pricing.output) / 1000; }"
js_new = (
    "function tokenCount(usage, snake, camel) { if (!usage) return 0; const v = usage[snake] != null ? usage[snake] : usage[camel]; const n = Number(v); return Number.isFinite(n) ? n : 0; }\n"
    "function calculateCost(provider, model, usage) { const pricing = PRICING[provider]?.[model] || { input: 0.0004, output: 0.0004 }; return (tokenCount(usage,'prompt_tokens','promptTokens') * pricing.input + tokenCount(usage,'completion_tokens','completionTokens') * pricing.output) / 1000; }"
)
assert js.count(js_old) == 1, "cost.js anchor count = %d" % js.count(js_old)
JS.write_text(js.replace(js_old, js_new, 1), encoding="utf-8")
print("  cost.js: patched calculateCost + added tokenCount")

# --- lockstep copy: lib/llm/cost.ts --------------------------------------
TS = pathlib.Path("lib/llm/cost.ts")
ts = TS.read_text(encoding="utf-8")

ts_old = "  return (usage.promptTokens * pricing.input + usage.completionTokens * pricing.output) / 1000;"
ts_new = "  return (tokenCount(usage, 'prompt_tokens', 'promptTokens') * pricing.input + tokenCount(usage, 'completion_tokens', 'completionTokens') * pricing.output) / 1000;"
assert ts.count(ts_old) == 1, "cost.ts body count = %d" % ts.count(ts_old)
ts = ts.replace(ts_old, ts_new, 1)

helper = """function tokenCount(usage: unknown, snake: string, camel: string): number {
  if (!usage || typeof usage !== 'object') return 0;
  const rec = usage as Record<string, unknown>;
  const v = rec[snake] != null ? rec[snake] : rec[camel];
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function calculateCost("""
assert ts.count("function calculateCost(") == 1
ts = ts.replace("function calculateCost(", helper, 1)

# The signature typed usage as camelCase-only; widen it to the real shape.
ts = ts.replace(
    "function calculateCost(provider: string, model: string, usage: { promptTokens: number; completionTokens: number }):",
    "function calculateCost(provider: string, model: string, usage: { promptTokens?: number; completionTokens?: number; prompt_tokens?: number; completion_tokens?: number } | null | undefined):",
    1,
)
TS.write_text(ts, encoding="utf-8")
print("  cost.ts: patched calculateCost, widened signature, added tokenCount")
