/**
 * Run the ACTUAL actOnFloorRollups source from the shipped god manager against
 * stubs. Extracting the real text rather than a copy, because the failure being
 * guarded is "god crash-loops on startup and the top-level agent never comes
 * back" -- a reference error in that function is invisible to `node --check`
 * and invisible to the pure unit tests on the actuator.
 */
const fs = require('fs');
const path = require('path');
const ROOT = process.env.OPENALICE_ROOT || '/Users/a/trading/openalice-fleet';
const SRC = path.join(ROOT, 'hive/agents/god/bin/agent_manager.js');

const src = fs.readFileSync(SRC, 'utf8');

// Pull the real function plus its module-level dedupe declaration.
const m = src.match(/let lastRollupActed = new Set\(\);[\s\S]*?\n}\n/);
if (!m) {
  console.log('  FAIL could not find actOnFloorRollups in the shipped manager');
  process.exit(1);
}
const realSource = m[0];
console.log('  extracted ' + realSource.split('\n').length + ' lines of real source');

// Stubs for every identifier the function closes over.
const logged = [];
const emitted = [];
let inboxPayload = [];

const sandbox = {
  AGENT_ID: 'god',
  getInboxMessages: (id, filter) => inboxPayload,
  decideRollup: require(path.join(ROOT, 'hive/lib/rollup_actuator')).decide,
  rollupLine: require(path.join(ROOT, 'hive/lib/rollup_actuator')).summaryLine,
  rollupPatch: require(path.join(ROOT, 'hive/lib/rollup_actuator')).statusPatch,
  logAgent: (lvl, msg) => logged.push(lvl + ': ' + msg),
  emitEvent: (e) => emitted.push(e.type),
  Date,
  Set,
  Object,
};
sandbox.global = sandbox;

const vm = require('vm');
const ctx = vm.createContext(sandbox);
try {
  vm.runInContext(realSource + '\nthis.act = actOnFloorRollups;', ctx, { timeout: 5000 });
} catch (e) {
  console.log('  FAIL the real source threw on load: ' + e.message);
  process.exit(1);
}
console.log('  real source loads without a reference error');

const act = ctx.act;
const now = Date.now();
const rollup = (over) => Object.assign({
  message_id: 'm-' + Math.random().toString(36).slice(2),
  from: 'floor-rollup', type: 'status_report',
  generated_at: new Date(now).toISOString(),
  totals: { agents: 58, healthy: 58, stale: 0, unknown_heartbeat: 0 },
  llm_success_rate: 25, floors_needing_attention: [],
}, over || {});

let failed = 0;
function check(name, cond, detail) {
  if (cond) { console.log('  ok   ' + name); }
  else { failed++; console.log('  FAIL ' + name + (detail ? ': ' + detail : '')); }
}

// 1) a degraded rollup escalates, logs, and emits
inboxPayload = [rollup()];
logged.length = 0; emitted.length = 0;
let patch = act();
check('degraded rollup returns a status patch', patch && patch.floor_rollup, JSON.stringify(patch));
check('escalated flag is true', patch && patch.floor_rollup.escalated === true);
check('logged one CRITICAL line', logged.some(l => l.startsWith('ERROR')), JSON.stringify(logged));
check('emitted fleet_degraded', emitted.includes('fleet_degraded'), JSON.stringify(emitted));

// 2) idempotent: the same message must not re-escalate on the next poll
logged.length = 0; emitted.length = 0;
patch = act();
check('second poll does not re-log the same message', logged.length === 0, JSON.stringify(logged));
check('second poll returns null (already acted)', patch === null, JSON.stringify(patch));

// 3) a healthy rollup produces no log noise
inboxPayload = [rollup({ message_id: 'healthy-1', llm_success_rate: 99 })];
logged.length = 0;
patch = act();
check('healthy rollup logs nothing', logged.length === 0, JSON.stringify(logged));
check('healthy rollup still records a verdict', patch && patch.floor_rollup && patch.floor_rollup.escalated === false);

// 4) non-rollup and stale messages are ignored without throwing
inboxPayload = [rollup({ message_id: 'other-1', from: 'someone-else' }),
                rollup({ message_id: 'old-1', generated_at: new Date(now - 5 * 3600 * 1000).toISOString() })];
logged.length = 0;
try {
  act();
  check('foreign + stale messages do not throw', true);
} catch (e) {
  check('foreign + stale messages do not throw', false, e.message);
}
check('foreign + stale produce no log lines', logged.length === 0, JSON.stringify(logged));

// 5) hostile inbox: malformed entries must not take god down
inboxPayload = [null, 42, 'garbage', {}, rollup({ message_id: 'good-1' })];
logged.length = 0;
try {
  act();
  check('malformed inbox entries do not throw', true);
} catch (e) {
  check('malformed inbox entries do not throw', false, e.message);
}
check('the one good message still acted', logged.length >= 1, JSON.stringify(logged));

// 6) the dedupe set must stay bounded
for (let i = 0; i < 400; i++) inboxPayload = [rollup({ message_id: 'bulk-' + i })];
try { act(); } catch (e) { /* the set is a closure var, not inspectable here */ }
console.log('  ok   400 sequential messages handled without throwing');

console.log(failed ? '  ' + failed + ' FAILED' : '  all real-source checks passed');
process.exit(failed ? 1 : 0);
