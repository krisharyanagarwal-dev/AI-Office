import pathlib

p = pathlib.Path("hive/lib/rollup_actuator.js")
s = p.read_text(encoding="utf-8")

OLD = '''  if (totals.stale > 0) {
    reasons.push(totals.stale + ' agent(s) stale across ' + (msg.floors_needing_attention || []).length + ' floor(s)');
  }'''

NEW = '''  // unknown_heartbeat counts too. An agent that is registered, running, and
  // has no timestamp at all is not evidence of health, it is absence of
  // evidence, and the rollup reports it separately precisely so it can be
  // escalated. Counting only `stale` meant a fleet of agents that had stopped
  // reporting entirely read as clean.
  const stale = totals.stale || 0;
  const unknown = totals.unknown_heartbeat || 0;
  if (stale > 0) {
    reasons.push(stale + ' agent(s) stale across ' + (msg.floors_needing_attention || []).length + ' floor(s)');
  }
  if (unknown > 0) {
    reasons.push(unknown + ' agent(s) with no heartbeat, which is not evidence of health');
  }'''
assert s.count(OLD) == 1, "anchor=%d" % s.count(OLD)
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  unknown_heartbeat now escalates")
