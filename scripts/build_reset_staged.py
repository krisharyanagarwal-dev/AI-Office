import pathlib
import re

Q = chr(39)

# ---- cost.js staged copy: HEAD + the reset fix ------------------------------
js = pathlib.Path("/tmp/h.js")
s = js.read_text(encoding="utf-8")

OLD = ("function resetDailyCosts() { for(const c of costCache.values()) c.daily=0; saveCosts(); }\n"
       "function resetMonthlyCosts() { for(const c of costCache.values()) c.monthly=0; saveCosts(); }")
assert s.count(OLD) == 1, "js reset anchor %d" % s.count(OLD)

NEW = (
    "function resetPeriod(field) { withLock(() => { let disk; "
    "try { disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, " + Q + "utf8" + Q + ")) : {}; } catch (e) { return; } "
    "if (!disk || typeof disk !== " + Q + "object" + Q + ") disk = {}; "
    "for (const v of Object.values(disk)) { if (v && typeof v === " + Q + "object" + Q + ") v[field] = 0; } "
    "const tmp = COST_DB_PATH + " + Q + ".tmp." + Q + " + process.pid; fs.writeFileSync(tmp, JSON.stringify(disk, null, 2)); fs.renameSync(tmp, COST_DB_PATH); "
    "for (const [k, v] of Object.entries(disk)) { if (costCache.has(k)) { const c = costCache.get(k); c[field] = 0; } } }); }\n"
    "function resetDailyCosts() { resetPeriod(" + Q + "daily" + Q + "); }\n"
    "function resetMonthlyCosts() { resetPeriod(" + Q + "monthly" + Q + "); }"
)
js.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  js staged copy has resetPeriod")

# ---- cost.ts staged copy ----------------------------------------------------
ts = pathlib.Path("/tmp/h.ts")
t = ts.read_text(encoding="utf-8")
m = re.search(r"function resetDailyCosts\(\) \{.*?\n\}", t, re.S)
m2 = re.search(r"function resetMonthlyCosts\(\) \{.*?\n\}", t, re.S)
assert m and m2, "ts resets not found"

new_ts = (
    "function resetPeriod(field: 'daily' | 'monthly') {\n"
    "  const fs = require('fs');\n"
    "  withLock(() => {\n"
    "    let disk: Record<string, any>;\n"
    "    try {\n"
    "      disk = fs.existsSync(COST_DB_PATH) ? JSON.parse(fs.readFileSync(COST_DB_PATH, 'utf8')) : {};\n"
    "    } catch (e) {\n"
    "      return;\n"
    "    }\n"
    "    if (!disk || typeof disk !== 'object') disk = {};\n"
    "    for (const v of Object.values(disk)) {\n"
    "      if (v && typeof v === 'object') (v as any)[field] = 0;\n"
    "    }\n"
    "    const tmp = COST_DB_PATH + '.tmp.' + process.pid;\n"
    "    fs.writeFileSync(tmp, JSON.stringify(disk, null, 2));\n"
    "    fs.renameSync(tmp, COST_DB_PATH);\n"
    "    for (const [k, v] of Object.entries(disk)) {\n"
    "      const c = costCache.get(k);\n"
    "      if (c) (c as any)[field] = 0;\n"
    "    }\n"
    "  });\n"
    "}\n"
    "function resetDailyCosts() { resetPeriod('daily'); }\n"
    "function resetMonthlyCosts() { resetPeriod('monthly'); }"
)
ts.write_text(t[:m.start()] + new_ts + t[m2.end():], encoding="utf-8")
print("  ts staged copy has resetPeriod")
