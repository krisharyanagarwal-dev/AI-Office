"""Fix: roster staleness must not downgrade fleet status.

The fleet summary pushed 'registry.json is stale' into issues[] whenever
registry_stale was true, so a healthy 57/58 fleet reported DEGRADED purely
because the roster file had not been rewritten in 141 hours.

registry.json is a roster: it is written when the agent set changes, not on a
timer. A stable fleet therefore accumulates unbounded age while being entirely
correct, so the 300s freshness threshold (which is correct for processes.json,
a live observation) permanently mislabels it. The flag itself is right and
stays in the payload under identity.registry_stale; it just must not gate the
verdict.

This is what the per-agent path already does. rosterFreshness.test.js asserts
'roster staleness does not downgrade status, which is live-derived' and says why:
precision, not blanket invalidation. That test passes 6/6 because it exercises
the agent path, which never had the issues[] push. The fleet path did, and no
test asserted on that string, which is how the disagreement shipped.

Not weakened to pass: no existing assertion is changed or removed. The label is
still computed and still reported. Only its effect on the verdict changes, which
is the defect.
"""
import pathlib

p = pathlib.Path("office-hud/server/openaliceStatus.js")
s = p.read_text(encoding="utf-8")

OLD = "    if (registryStale) issues.push('registry.json is stale');"
NEW = """    // Roster age is reported, not gating. registry.json is written when the
    // agent set changes, not on a timer, so a stable fleet accrues unbounded
    // age while remaining entirely correct -- the 300s threshold that suits
    // processes.json (a live observation) permanently mislabels it. Pushing
    // this into issues[] made a healthy 57/58 fleet report DEGRADED on a
    // 141-hour-old but accurate roster. The flag still ships in
    // identity.registry_stale, so the age is visible to any reader; it just
    // does not decide the verdict, which is derived from liveness. This
    // matches the per-agent path and the intent asserted in
    // rosterFreshness.test.js: 'precision, not blanket invalidation'.
    if (registryError) issues.push(`registry unreadable: ${registryError}`);"""

assert s.count(OLD) == 1, "anchor count = %d" % s.count(OLD)
s = s.replace(OLD, NEW, 1)

# The original line is replaced by a registryError guard, so drop the now
# duplicated original that followed it.
DUP = """    if (registryError) issues.push(`registry unreadable: ${registryError}`);
    if (registryError) issues.push(`registry unreadable: ${registryError}`);"""
if s.count(DUP) == 1:
    s = s.replace(DUP, "    if (registryError) issues.push(`registry unreadable: ${registryError}`);", 1)

p.write_text(s, encoding="utf-8")
print("  fleet verdict no longer gated on roster age; label still reported")
