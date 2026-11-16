import pathlib

p = pathlib.Path("lib/llm/cost.js")
s = p.read_text(encoding="utf-8")

OLD = ("for (const k of dirtyAgents) { if (costCache.has(k)) disk[k] = costCache.get(k); } dirtyAgents.clear(); ")

NEW = (
    "for (const k of dirtyAgents) { if (!costCache.has(k)) continue; "
    "const mine = costCache.get(k); const theirs = disk[k]; "
    "let merged = mine; "
    "if (theirs && typeof theirs === 'object' && Array.isArray(theirs.records) && Array.isArray(mine.records)) { "
    "const seen = new Map(); for (const r of theirs.records) seen.set(r.timestamp + '|' + r.taskId, r); "
    "let added = 0; for (const r of mine.records) { const key = r.timestamp + '|' + r.taskId; if (!seen.has(key)) { seen.set(key, r); added++; } } "
    "if (added) { merged = Object.assign({}, theirs, mine, { records: Array.from(seen.values()) }); "
    "merged.daily = pickBigger(theirs.daily, mine.daily); merged.monthly = pickBigger(theirs.monthly, mine.monthly); } "
    "else { merged = Object.assign({}, theirs, mine, { records: theirs.records }); "
    "merged.daily = pickBigger(theirs.daily, mine.daily); merged.monthly = pickBigger(theirs.monthly, mine.monthly); } } "
    "disk[k] = merged; } dirtyAgents.clear(); "
)

assert s.count(OLD) == 1, "merge anchor count = %d" % s.count(OLD)
s = s.replace(OLD, NEW, 1)

# helper, placed just before saveCosts
helper = (
    "function pickBigger(a, b) { const x = Number(a), y = Number(b); "
    "if (!Number.isFinite(x)) return Number.isFinite(y) ? y : a; "
    "if (!Number.isFinite(y)) return x; return x > y ? x : y; }\n"
)
anchor = "function withLock(fn)"
assert s.count(anchor) == 1
s = s.replace(anchor, helper + anchor, 1)

p.write_text(s, encoding="utf-8")
print("  cost.js: dirty-agent merge is now a union that never shrinks records")
