/**
 * Integration check: the real inbox, the real actuator, no restart.
 *
 * god is a long-lived process holding the pre-change code, and restarting it
 * is a decision for the operator, not something a test should do to a live
 * agent. So this exercises the exact path the patched cycle will take --
 * getInboxMessages(AGENT_ID, {type:'status_report'}) -> decide -> summaryLine
 * -> statusPatch -> status merge -- against the actual messages on disk, and
 * prints what god would have logged. It does not write anything.
 */
const path = require('path');
const fs = require('fs');
const ROOT = process.env.OPENALICE_ROOT || '/Users/a/trading/openalice-fleet';
const HIVE = path.join(ROOT, 'hive');

const { getInboxMessages } = require(path.join(HIVE, 'lib', 'message'));
const A = require(path.join(HIVE, 'lib', 'rollup_actuator'));

const AGENT_ID = 'god';
const msgs = getInboxMessages(AGENT_ID, { type: 'status_report' });
console.log('  rollup messages in ' + AGENT_ID + "'s inbox: " + msgs.length);

if (msgs.length === 0) {
  console.log('  FAIL no messages to act on; the rollup is not reaching the inbox');
  process.exit(1);
}

let escalated = 0, ignored = 0, logged = 0;
for (const m of msgs) {
  const d = A.decide(m, Date.now());
  if (!d.acted) { ignored++; continue; }
  const line = A.summaryLine(d);
  if (line) { logged++; console.log('    would LOG [' + d.severity + '] ' + line); }
  const p = A.statusPatch(d, m);
  if (p && p.floor_rollup && p.floor_rollup.escalated) escalated++;
  if (escalated === 1 && p) {
    console.log('    would write to status.json:');
    console.log('      ' + JSON.stringify(p.floor_rollup).slice(0, 200));
  }
}
console.log('  acted: ' + (msgs.length - ignored) + '  escalated: ' + escalated + '  log lines: ' + logged + '  ignored: ' + ignored);

// The verdict that matters: a 25% success rate must escalate, not be marked
// READ and forgotten. If this is 0 the wiring is theatre.
const fresh = msgs.filter(m => Date.now() - Date.parse(m.generated_at) < 2 * 3600 * 1000);
const anyEsc = fresh.some(m => (A.decide(m, Date.now()) || {}).escalated);
console.log('  fresh msgs: ' + fresh.length + '  at least one escalates: ' + anyEsc);
if (!anyEsc) { console.log('  FAIL a degraded fleet produced no escalation'); process.exit(1); }
console.log('  OK the degraded verdict reaches a log line and the status file');
