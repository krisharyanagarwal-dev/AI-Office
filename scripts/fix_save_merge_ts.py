import pathlib

p = pathlib.Path("lib/llm/cost.ts")
s = p.read_text(encoding="utf-8")

old = """function saveCosts() {
  try {
    const fs = require('fs');
    const data = Object.fromEntries(costCache);
    fs.writeFileSync(COST_DB_PATH, JSON.stringify(data, null, 2));"""

new = """function saveCosts() {
  try {
    const fs = require('fs');
    // Merge over the current on-disk document instead of replacing it: many
    // processes hold a partial in-memory cache and a blind full-file write
    // reverts every other process's entries to whatever this process saw at
    // startup, erasing agents it never loaded.
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

assert s.count(old) == 1, "cost.ts saveCosts anchor count = %d" % s.count(old)
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("  cost.ts: saveCosts now merges before writing")
