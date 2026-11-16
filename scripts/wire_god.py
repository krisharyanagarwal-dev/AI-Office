import pathlib

p = pathlib.Path("hive/agents/god/bin/agent_manager.js")
s = p.read_text(encoding="utf-8")

# 1) import next to the other lib requires
OLD_IMP = "  const { ensureInboxOutbox, sendMessage, processInbox, getInboxMessages, markMessageProcessed, moveToOutbox } = require(path.join(HIVE, 'lib', 'message'));"
if s.count(OLD_IMP) != 1:
    # tolerate line wrapping
    import re as _re
    m = _re.search(r"^.*require\(path\.join\(HIVE, 'lib', 'message'\)\);.*$", s, _re.M)
    assert m, "message.js require line not found"
    OLD_IMP = m.group(0)
    NEW_IMP = OLD_IMP + "\n  const { decide: decideRollup, summaryLine: rollupLine, statusPatch: rollupPatch } = require(path.join(HIVE, 'lib', 'rollup_actuator'));"
else:
    NEW_IMP = OLD_IMP + "\n  const { decide: decideRollup, summaryLine: rollupLine, statusPatch: rollupPatch } = require(path.join(HIVE, 'lib', 'rollup_actuator'));"
assert s.count(OLD_IMP) == 1
s = s.replace(OLD_IMP, NEW_IMP, 1)

# 2) an actuator function, placed before runCycle
FUNC = '''
/**
 * Act on any floor-rollup message sitting unread in the inbox.
 *
 * processInbox() marks messages READ and returns a count, so a status_report
 * arrives, gets counted as "worked", and its body is never looked at. That made
 * a DEGRADED rollup indistinguishable from a healthy one from inside the agent.
 * This reads the ones processInbox has marked READ but not ACKNOWLEDGED, decides
 * once per message, and records the verdict where status is already read.
 *
 * Best-effort by design: a failure here must not take down the main loop, so
 * everything is caught and logged rather than thrown. Idempotent per message id,
 * because the cycle runs every few seconds and would otherwise re-escalate the
 * same hourly digest forever.
 */
let lastRollupActed = new Set();
function actOnFloorRollups() {
  let msgs = [];
  try {
    msgs = getInboxMessages(AGENT_ID, { type: 'status_report' }) || [];
  } catch (err) {
    logAgent('WARN', 'Could not read rollup messages: ' + (err && err.message));
    return null;
  }
  let patch = null;
  for (const m of msgs) {
    const id = m.message_id || m.timestamp;
    if (id && lastRollupActed.has(id)) continue;
    let d;
    try {
      d = decideRollup(m, Date.now());
    } catch (err) {
      logAgent('WARN', 'rollup decision failed: ' + (err && err.message));
      continue;
    }
    if (!d || !d.acted) continue;
    if (id) lastRollupActed.add(id);
    const line = rollupLine(d);
    if (line) {
      logAgent(d.severity === 'critical' ? 'ERROR' : 'WARN', line);
      try {
        emitEvent({ type: 'fleet_degraded', agent_id: AGENT_ID, severity: d.severity, reasons: d.reasons, llm_success_rate: d.llm_success_rate, floors_needing_attention: d.floors_needing_attention, timestamp: new Date().toISOString() });
      } catch (err) { /* an event is not worth failing a cycle over */ }
    }
    const p2 = rollupPatch(d, m);
    if (p2) patch = Object.assign(patch || {}, p2);
  }
  // Bound the dedupe set so a long-lived process does not accumulate ids
  // forever. Messages older than the actuator's own age window are ignored
  // anyway, so keeping a few hundred is far more than enough.
  if (lastRollupActed.size > 200) {
    lastRollupActed = new Set(Array.from(lastRollupActed).slice(-100));
  }
  return patch;
}

'''
anchor = "async function runCycle() {"
assert s.count(anchor) == 1
s = s.replace(anchor, FUNC.lstrip("\n") + anchor, 1)

# 3) call it in the cycle, right after the inbox is processed
OLD_CALL = "  const inboxCount = await processInbox(AGENT_ID);"
NEW_CALL = """  const inboxCount = await processInbox(AGENT_ID);
  // processInbox() above only marked these READ; this is where the body is
  // actually interpreted. Wrapped because a throw here would abort the cycle.
  let rollupPatchOut = null;
  try { rollupPatchOut = actOnFloorRollups(); } catch (err) { logAgent('WARN', 'rollup actuator threw: ' + (err && err.message)); }"""
assert s.count(OLD_CALL) == 1
s = s.replace(OLD_CALL, NEW_CALL, 1)

# 4) surface it in the returned run result so reportStatus can carry it
OLD_RET = "  if (!claim.success) { status.status = 'IDLE'; status.current_task = null; writeStatus(status); return { status: 'IDLE', worked, current_task: null, completed_task_id: null, result: null, evidence: null }; }"
NEW_RET = "  if (!claim.success) { status.status = 'IDLE'; status.current_task = null; writeStatus(status); return { status: 'IDLE', worked, current_task: null, completed_task_id: null, result: null, evidence: null, floor_rollup: rollupPatchOut }; }"
assert s.count(OLD_RET) == 1
s = s.replace(OLD_RET, NEW_RET, 1)

OLD_OK = "  if (complete.success) { require(path.join(HIVE, 'lib', 'session')).clearSessionCurrentTask(currentSessionId); return { status: 'COMPLETE', current_task: task.task_id, completed_task_id: task.task_id, result: llmResult, evidence: { requested_target_file: task.evidence?.file || '', requested_target_line: task.evidence?.line || 0, outcome: 'text_only', outcome_basis: 'no_executor_in_producer_path', llmResponseLength: llmResult.length } }; } else { return { status: 'FAILED', current_task: task.task_id, completed_task_id: null, result: null, evidence: null, error: 'lost-claim' }; }"
NEW_OK = "  if (complete.success) { require(path.join(HIVE, 'lib', 'session')).clearSessionCurrentTask(currentSessionId); return { status: 'COMPLETE', current_task: task.task_id, completed_task_id: task.task_id, result: llmResult, evidence: { requested_target_file: task.evidence?.file || '', requested_target_line: task.evidence?.line || 0, outcome: 'text_only', outcome_basis: 'no_executor_in_producer_path', llmResponseLength: llmResult.length }, floor_rollup: rollupPatchOut }; } else { return { status: 'FAILED', current_task: task.task_id, completed_task_id: null, result: null, evidence: null, error: 'lost-claim', floor_rollup: rollupPatchOut }; }"
assert s.count(OLD_OK) == 1
s = s.replace(OLD_OK, NEW_OK, 1)

# 5) merge the patch into the persisted status
OLD_STATUS = "  const status = { agent_id: AGENT_ID, agent_name: AGENT_NAME, floor: AGENT_FLOOR, role: AGENT_ROLE, status: runResult.status, current_task: runResult.current_task, completed_task_id: runResult.completed_task_id, result: runResult.result, evidence: runResult.evidence, last_activity: new Date().toISOString(), pid: process.pid, inbox_count: runResult.inbox_count || 0, outbox_count: runResult.outbox_count || 0 };"
NEW_STATUS = """  const status = { agent_id: AGENT_ID, agent_name: AGENT_NAME, floor: AGENT_FLOOR, role: AGENT_ROLE, status: runResult.status, current_task: runResult.current_task, completed_task_id: runResult.completed_task_id, result: runResult.result, evidence: runResult.evidence, last_activity: new Date().toISOString(), pid: process.pid, inbox_count: runResult.inbox_count || 0, outbox_count: runResult.outbox_count || 0 };
  // Carry the floor-rollup verdict here rather than into a new file, so a reader
  // already looking at god's status sees why the fleet looks degraded.
  if (runResult.floor_rollup && runResult.floor_rollup.floor_rollup) status.floor_rollup = runResult.floor_rollup.floor_rollup;"""
assert s.count(OLD_STATUS) == 1
s = s.replace(OLD_STATUS, NEW_STATUS, 1)

p.write_text(s, encoding="utf-8")
print("  god wired: import + actuator + cycle hook + status surface")
