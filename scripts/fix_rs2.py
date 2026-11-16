import pathlib

p = pathlib.Path("office-hud/server/openaliceStatus.js")
lines = p.read_text(encoding="utf-8").split("\n")

# Located by content, then verified by repr: the file indents with 2 spaces and
# the earlier text anchor used 4, so it matched nothing. Do not assume
# indentation -- read the line that actually exists.
idx = next((i for i, l in enumerate(lines) if "registry.json is stale" in l), None)
assert idx is not None, "target line not found"
old = lines[idx]
indent = old[: len(old) - len(old.lstrip())]

# Roster age is a label, not a gate. Keep the flag in the payload; stop letting it
# decide the verdict. registry.json is written when the agent set changes, not on
# a timer, so a stable fleet accrues unbounded age while remaining correct. The
# 300s threshold suits processes.json (a live observation) and permanently
# mislabels a roster. This is why a healthy 57/58 fleet reported DEGRADED on a
# 141-hour-old but accurate file.
lines[idx:idx + 1] = [
    indent + "// Roster age is reported, not gating. registry.json is written when the",
    indent + "// agent set changes, not on a timer, so a stable fleet accrues unbounded",
    indent + "// age while staying entirely correct. The 300s threshold that suits",
    indent + "// processes.json -- a live observation -- permanently mislabels a roster,",
    indent + "// which made a healthy 57/58 fleet report DEGRADED on a 141h-old but",
    indent + "// accurate file. The flag still ships in identity.registry_stale so the",
    indent + "// age is visible to any reader; it just does not decide a verdict that is",
    indent + "// derived from liveness. Matches the per-agent path and the intent in",
    indent + "// rosterFreshness.test.js: precision, not blanket invalidation.",
]

p.write_text("\n".join(lines), encoding="utf-8")
print("  patched line %d (%d-space indent, was %r)" % (idx + 1, len(indent), old.strip()[:44]))
