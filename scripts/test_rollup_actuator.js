/**
 * Tests for rollup_actuator: what an hourly floor rollup should cause.
 *
 * The failure this guards is the quiet one. A digest that arrives, gets marked
 * READ, and changes nothing is indistinguishable at runtime from a fleet that
 * is genuinely fine. So the tests below are mostly about escalation firing, and
 * about not firing on junk, which is the other way a useful alarm dies.
 */
const assert = require('assert');
const path = require('path');
const A = require(path.join(__dirname, '..', '..', 'hive', 'lib', 'rollup_actuator'));

const NOW = Date.parse('2026-09-30T00:00:00Z');
const iso = (ms) => new Date(NOW + ms).toISOString();

function rollup(over) {
  return Object.assign({
    from: 'floor-rollup',
    type: 'status_report',
    generated_at: iso(0),
    totals: { agents: 58, healthy: 58, stale: 0, unknown_heartbeat: 0, in_flight: 55 },
    llm_success_rate: 25,
    floors_needing_attention: [],
  }, over || {});
}

// --- escalation: the case that matters -------------------------------

function test_degraded_llm_escalates_critical() {
  const d = A.decide(rollup(), NOW);
  assert.strictEqual(d.escalated, true, 'a 25% success rate did not escalate');
  assert.strictEqual(d.severity, 'critical');
  assert.ok(/25%/.test(d.reasons.join(' ')), 'reason omitted the rate');
}

function test_stale_agents_escalate() {
  const d = A.decide(rollup({
    totals: { agents: 58, healthy: 50, stale: 8, unknown_heartbeat: 0, in_flight: 40 },
    llm_success_rate: 99,
    floors_needing_attention: ['f7', 'f9'],
  }), NOW);
  assert.strictEqual(d.escalated, true, '8 stale agents did not escalate');
  assert.strictEqual(d.severity, 'warning', 'healthy LLM should soften to warning');
  assert.ok(/8 agent/.test(d.reasons.join(' ')));
}

function test_unknown_heartbeat_also_escalates() {
  const d = A.decide(rollup({
    totals: { agents: 10, healthy: 9, stale: 0, unknown_heartbeat: 1, in_flight: 1 },
    llm_success_rate: 99,
  }), NOW);
  assert.strictEqual(d.escalated, true, 'an unknown heartbeat was treated as fine');
}

function test_a_healthy_fleet_does_not_escalate() {
  const d = A.decide(rollup({ llm_success_rate: 98 }), NOW);
  assert.strictEqual(d.escalated, false, 'a healthy fleet escalated');
  assert.strictEqual(d.severity, 'ok');
}

// --- silence: the other way a useful alarm dies ----------------------

function test_a_message_from_another_agent_is_ignored() {
  const d = A.decide(rollup({ from: 'some-other-agent' }), NOW);
  assert.strictEqual(d.escalated, false);
  assert.strictEqual(d.acted, false, 'acted on a message that was not a rollup');
}

function test_a_stale_rollup_is_ignored() {
  // Three hours old: a newer one is already due, so escalating on this one
  // would report a problem that may already be fixed.
  const d = A.decide(rollup({ generated_at: iso(-3 * 3600 * 1000) }), NOW);
  assert.strictEqual(d.escalated, false);
  assert.ok(/stale/.test(d.reasons.join(' ')));
}

function test_an_undated_rollup_is_ignored() {
  const m = rollup();
  delete m.generated_at;
  const d = A.decide(m, NOW);
  assert.strictEqual(d.escalated, false, 'an undated rollup escalated');
}

function test_totals_missing_healthy_and_stale_is_ignored() {
  const d = A.decide(rollup({ totals: { agents: 5 } }), NOW);
  assert.strictEqual(d.escalated, false);
  assert.ok(/totals missing/.test(d.reasons.join(' ')));
}

function test_malformed_input_does_not_throw() {
  for (const bad of [null, undefined, 42, 'nope', [], {}]) {
    const d = A.decide(bad, NOW);
    assert.ok(d && typeof d.escalated === 'boolean', 'no decision for %r' % (bad));
    assert.strictEqual(d.escalated, false);
  }
}

function test_a_missing_llm_rate_does_not_invent_one() {
  const m = rollup();
  delete m.llm_success_rate;
  const d = A.decide(m, NOW);
  assert.strictEqual(d.escalated, false, 'a missing rate was treated as a failure');
  assert.strictEqual(d.llm_success_rate, null, 'missing rate was not preserved as null');
}

// --- surfacing -------------------------------------------------------

function test_summary_line_is_null_when_healthy() {
  assert.strictEqual(A.summaryLine(A.decide(rollup({ llm_success_rate: 99 }), NOW)), null,
    'a healthy hour produced a log line');
}

function test_summary_line_names_severity_and_reason() {
  const line = A.summaryLine(A.decide(rollup(), NOW));
  assert.ok(line.startsWith('[CRITICAL]'), 'severity not in the line: ' + line);
  assert.ok(/25%/.test(line));
}

function test_status_patch_surfaces_the_verdict_where_status_is_read() {
  const p = A.statusPatch(A.decide(rollup(), NOW), rollup());
  assert.ok(p.floor_rollup, 'no floor_rollup block in the status patch');
  assert.strictEqual(p.floor_rollup.escalated, true);
  assert.strictEqual(p.floor_rollup.llm_success_rate, 25);
  assert.ok(p.floor_rollup.checked_at, 'no checked_at timestamp');
}

function test_status_patch_is_null_for_ignored_messages() {
  const m = rollup({ from: 'someone-else' });
  assert.strictEqual(A.statusPatch(A.decide(m, NOW), m), null);
}

function test_boundary_at_exactly_the_health_threshold_does_not_escalate() {
  const d = A.decide(rollup({ llm_success_rate: A.HEALTHY_LLM_RATE }), NOW);
  assert.strictEqual(d.escalated, false, 'the threshold itself escalated; it must be inclusive');
}

function test_one_percent_below_the_threshold_escalates() {
  const d = A.decide(rollup({ llm_success_rate: A.HEALTHY_LLM_RATE - 1 }), NOW);
  assert.strictEqual(d.escalated, true);
}

// --- runner ----------------------------------------------------------

const tests = Object.keys(global).length && null;
const NAMES = [
  'test_degraded_llm_escalates_critical', 'test_stale_agents_escalate',
  'test_unknown_heartbeat_also_escalates', 'test_a_healthy_fleet_does_not_escalate',
  'test_a_message_from_another_agent_is_ignored', 'test_a_stale_rollup_is_ignored',
  'test_an_undated_rollup_is_ignored', 'test_totals_missing_healthy_and_stale_is_ignored',
  'test_malformed_input_does_not_throw', 'test_a_missing_llm_rate_does_not_invent_one',
  'test_summary_line_is_null_when_healthy', 'test_summary_line_names_severity_and_reason',
  'test_status_patch_surfaces_the_verdict_where_status_is_read',
  'test_status_patch_is_null_for_ignored_messages',
  'test_boundary_at_exactly_the_health_threshold_does_not_escalate',
  'test_one_percent_below_the_threshold_escalates',
];

let failed = 0;
for (const name of NAMES) {
  try {
    eval(name)();
    console.log('  ok   ' + name);
  } catch (e) {
    failed++;
    console.log('  FAIL ' + name + ': ' + e.message);
  }
}
console.log((failed ? '  ' + failed + ' FAILED' : '  ' + NAMES.length + ' passed'));
process.exit(failed ? 1 : 0);
