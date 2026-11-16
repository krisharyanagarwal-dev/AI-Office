/**
 * Act on an hourly floor rollup.
 *
 * The rollup already arrives in the inbox as a status_report message, but
 * lib/message.js processInbox() only flips a message to READ and counts it.
 * Nothing anywhere dispatches on type, so the digest was being marked READ and
 * discarded: a DEGRADED verdict looked identical to a healthy one from the
 * inside. This is the piece that makes the message mean something.
 *
 * Deliberately not a new scheduler. The rollup arrives on the existing inbox
 * path, and escalation is recorded in the existing status/event surfaces, so
 * there is one source of truth for "what does god believe" rather than a
 * second file nobody reads.
 *
 * Pure with respect to the message it is given: the decision is a function of
 * the message, and the caller does the writing. That is what makes the
 * important cases testable without a fleet, an inbox, or a clock.
 */

/** LLM success rate at or above this counts as healthy. Mirrors the rollup. */
const HEALTHY_LLM_RATE = 70;

/** Only act on messages from the rollup, and only fresh ones. */
const ROLLUP_FROM = 'floor-rollup';
const MAX_AGE_MS = 2 * 60 * 60 * 1000; // two hours: one late poll, not a backlog

/**
 * Decide what a status_report message from the rollup should cause.
 *
 * Returns { escalated, severity, reasons } and never throws: a malformed or
 * unexpected message must not be able to take down an agent's main loop, so
 * every branch resolves to a safe answer instead of raising.
 */
function decide(msg, nowMs) {
  const now = typeof nowMs === 'number' ? nowMs : Date.now();
  const reasons = [];

  if (!msg || typeof msg !== 'object') {
    return { escalated: false, severity: 'info', reasons: ['unreadable message'], acted: false };
  }
  if (msg.from !== ROLLUP_FROM) {
    return { escalated: false, severity: 'info', reasons: ['not a floor rollup'], acted: false };
  }

  const generated = Date.parse(msg.generated_at);
  if (Number.isNaN(generated)) {
    // An undated rollup cannot be placed in time. Treating it as current would
    // mean a backlog of hour-old digests all escalate on the next poll.
    return { escalated: false, severity: 'info', reasons: ['no usable generated_at'], acted: false };
  }
  if (now - generated > MAX_AGE_MS) {
    return { escalated: false, severity: 'info', reasons: ['stale rollup, newer one due'], acted: false };
  }

  const totals = msg.totals || {};
  const rate = (typeof msg.llm_success_rate === 'number') ? msg.llm_success_rate : null;

  if (typeof totals.healthy !== 'number' || typeof totals.stale !== 'number') {
    return { escalated: false, severity: 'info', reasons: ['totals missing healthy/stale'], acted: false };
  }

  if (totals.stale > 0) {
    reasons.push(totals.stale + ' agent(s) stale across ' + (msg.floors_needing_attention || []).length + ' floor(s)');
  }
  if (rate !== null && rate < HEALTHY_LLM_RATE) {
    reasons.push('LLM success rate ' + rate + '% below ' + HEALTHY_LLM_RATE + '%');
  }

  const escalated = reasons.length > 0;
  return {
    escalated,
    severity: escalated ? (rate !== null && rate < HEALTHY_LLM_RATE ? 'critical' : 'warning') : 'ok',
    reasons,
    acted: true,
    totals,
    llm_success_rate: rate,
    floors_needing_attention: msg.floors_needing_attention || [],
  };
}

/**
 * Reduce a decision to one line for a human, and only when it escalated.
 * Returns null when there is nothing to say, so a healthy hour costs no lines
 * in the log and cannot become alert fatigue.
 */
function summaryLine(decision) {
  if (!decision || !decision.escalated) return null;
  return '[' + decision.severity.toUpperCase() + '] floor rollup: ' + decision.reasons.join('; ');
}

/**
 * Build the object to merge into the agent's status, so the DEGRADED verdict is
 * visible in the same place a reader already looks for god's state, rather than
 * requiring a new file to be discovered.
 */
function statusPatch(decision, msg) {
  if (!decision || !decision.acted) return null;
  return {
    floor_rollup: {
      checked_at: new Date().toISOString(),
      escalated: decision.escalated,
      severity: decision.severity,
      reasons: decision.reasons,
      llm_success_rate: decision.llm_success_rate,
      floors_needing_attention: decision.floors_needing_attention,
      generated_at: (msg && msg.generated_at) || null,
    },
  };
}

module.exports = { decide, summaryLine, statusPatch, HEALTHY_LLM_RATE, ROLLUP_FROM };
