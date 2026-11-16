import pathlib

p = pathlib.Path("hive/agents/god/bin/agent_manager.js")
s = p.read_text(encoding="utf-8")

OLD = '''  let patch = null;
  for (const m of msgs) {
    const id = m.message_id || m.timestamp;
    if (id && lastRollupActed.has(id)) continue;
    let d;
    try {
      d = decideRollup(m, Date.now());
    } catch (err) {
      logAgent('WARN', 'rollup decision failed: ' + (err && err.message));
      continue;
    }'''

NEW = '''  let patch = null;
  for (const m of msgs) {
    // getInboxMessages() parses files off disk and can hand back null for an
    // entry it could not read, so the id read has to be inside the guard. It
    // was not, which meant one corrupt inbox file threw on every cycle and
    // crash-looped the top-level agent, whose only recovery is the supervisor.
    let d;
    try {
      const id = m && (m.message_id || m.timestamp);
      if (id && lastRollupActed.has(id)) continue;
      d = decideRollup(m, Date.now());
      if (id) lastRollupActed.add(id);
    } catch (err) {
      logAgent('WARN', 'rollup decision failed: ' + (err && err.message));
      continue;
    }'''
assert s.count(OLD) == 1, "anchor=%d" % s.count(OLD)
s = s.replace(OLD, NEW, 1)

# The id is now added inside the guard, so drop the duplicate add below.
OLD_ADD = '''    if (id) lastRollupActed.add(id);
    const line = rollupLine(d);'''
NEW_ADD = '''    const line = rollupLine(d);'''
assert s.count(OLD_ADD) == 1, "dup-add anchor=%d" % s.count(OLD_ADD)
s = s.replace(OLD_ADD, NEW_ADD, 1)

p.write_text(s, encoding="utf-8")
print("  null-safe id read; god cannot crash-loop on a corrupt inbox file")
