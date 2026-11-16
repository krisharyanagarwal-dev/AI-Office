import pathlib
import re

p = pathlib.Path("lib/llm/cost.js")
s = p.read_text(encoding="utf-8")

NEW = (
    "if (theirs && typeof theirs === 'object' && Array.isArray(theirs.records) && Array.isArray(mine.records)) { "
    "let records; "
    "const all = theirs.records.concat(mine.records); "
    "const identifiable = all.every(r => r && r.timestamp != null && r.taskId != null); "
    "if (identifiable) { "
    "const seen = new Map(); for (const r of theirs.records) seen.set(r.timestamp + '|' + r.taskId, r); "
    "for (const r of mine.records) { const k = r.timestamp + '|' + r.taskId; if (!seen.has(k)) seen.set(k, r); } "
    "records = Array.from(seen.values()); "
    "} else { "
    "// Records without a usable identity cannot be de-duplicated, and cost records "
    "// are append-only, so a longer list extends a shorter one rather than replacing it. "
    "records = mine.records.length > theirs.records.length "
    "? theirs.records.concat(mine.records.slice(theirs.records.length)) : theirs.records; "
    "} "
    "merged = Object.assign({}, theirs, mine, { records: records }); "
    "merged.daily = pickBigger(theirs.daily, mine.daily); "
    "merged.monthly = pickBigger(theirs.monthly, mine.monthly); } "
)

# Replace from the `if (theirs &&` guard through the end of that block, which is
# the last `} }` before `disk[k] = merged;`.
pat = re.compile(r"if \(theirs && typeof theirs === 'object'.*?\} \}", re.S)
m = pat.search(s)
assert m, "union block not found"
print("  replacing %d chars" % (m.end() - m.start()))
p.write_text(s[:m.start()] + NEW + s[m.end():], encoding="utf-8")
print("  union merge now falls back to append semantics when records lack identity")
