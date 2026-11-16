import pathlib

JS = pathlib.Path("lib/llm/cost.js")
TS = pathlib.Path("lib/llm/cost.ts")

# Runtime line 25. Accept both the snake_case shape every agent manager
# actually passes (response.usage) and the camelCase shape, and coerce to a
# number so a missing field can never produce NaN.
js_old = "function calculateCost(provider, model, usage) { const pricing = PRICING[provider]?.[model] || { input: 0.0004, output: 0.0004 }; return (usage.promptTokens * pricing.input + usage.completionTokens * pricing.output) / 1000; }"
js_new = (
    "function tokenCount(usage, snake, camel) { if (!usage) return 0; "
    "const v = usage[snake] != null ? usage[snake] : usage[camel]; "
    "return Number.isFinite(Number(v)) ? Number(v) : 0; }\n"
    "function calculateCost(provider, model, usage) { const pricing = PRICING[provider]?.[model] || { input: 0.0004, output: 0.0004 }; "
    "return (tokenCount(usage,'prompt_tokens','promptTokens') * pricing.input + tokenCount(usage,'completion_tokens','completionTokens') * pricing.output) / 1000; }"
)

p = JS.read_text(encoding="utf-8")
assert p.count(js_old) == 1, "cost.js anchor count %d" % p.count(js_old)
p = p.replace(js_old, js_new, 1)

# The .ts is the lockstep copy; give it the same helper in its own style.
ts_anchor = "export function calculateCost("
idx = p.find(ts_anchor)
assert idx != -1
p = p[:idx] + """function tokenCount(usage: any, snake: string, camel: string): number {
  if (!usage) return 0;
  const v = usage[snake] != null ? usage[snake] : usage[camel];
  return Number.isFinite(Number(v)) ? Number(v) : 0;
}

""" + p[idx:]

JS.write_text(p, encoding="utf-8")
print("  patched cost.js")

# Apply the equivalent to the .ts separately.
t = TS.read_text(encoding="utf-8")
old_ts = re.search if False else None
import re as _re
m = _re.search(r"export function calculateCost\([^)]*\)[^{]*\{.*?\n\}", t, _re.S)
assert m, "cost.ts calculateCost not found"
body_old = m.group(0)
body_new = body_old.replace(
    "usage.promptTokens", "tokenCount(usage,'prompt_tokens','promptTokens')"
).replace(
    "usage.completionTokens", "tokenCount(usage,'completion_tokens','completionTokens')"
)
t = t.replace(body_old, body_new, 1)
t = t.replace(
    "export function calculateCost(",
    """function tokenCount(usage: any, snake: string, camel: string): number {
  if (!usage) return 0;
  const v = usage[snake] != null ? usage[snake] : usage[camel];
  return Number.isFinite(Number(v)) ? Number(v) : 0;
}

export function calculateCost(""",
    1,
)
TS.write_text(t, encoding="utf-8")
print("  patched cost.ts")
print("  cost.ts calculateCost now reads:")
for line in t.splitlines():
    if "tokenCount(usage" in line and "return" in line:
        print("   ", line.strip()[:150])
