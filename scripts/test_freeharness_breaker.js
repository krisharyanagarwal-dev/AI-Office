/**
 * The client-side breaker on the freeHarness provider, and one live call.
 *
 * isOpen was initialised to true, set to true by onSuccess and false by
 * onFailure -- inverted, and unread, because isHealthy() never consulted it.
 * The reset window was 30s against a 10s request timeout, so a healthy
 * provider was reported unhealthy for half a minute after every trip. The 10s
 * timeout is the "This operation was aborted" every agent was logging: the
 * AbortController tore down the fetch while the server was still working.
 *
 * The unit part runs offline. The live part is what makes this worth having:
 * it proves the client can actually get an answer through the real server,
 * which is the thing the fleet has been failing to do.
 */
const assert = require('assert');
const path = require('path');
const { FreeHarnessProvider } = require(path.join(__dirname, '..', 'providers', 'freeHarness.js'));

let failed = 0, passed = 0;
function check(name, cond, detail) {
  if (cond) { passed++; console.log('  ok   ' + name); }
  else { failed++; console.log('  FAIL ' + name + (detail ? ': ' + detail : '')); }
}

// --- breaker state machine -------------------------------------------
let p = new FreeHarnessProvider();
check('a brand-new provider is healthy', p.isHealthy() === true);
check('a brand-new provider is not marked tripped', p.isOpen === false,
  'isOpen=' + p.isOpen);

p = new FreeHarnessProvider();
p.onSuccess();
check('success keeps it healthy and closed', p.isHealthy() === true && p.isOpen === false);

p = new FreeHarnessProvider();
for (let i = 0; i < 4; i++) p.onFailure();
check('four failures do not trip it', p.isHealthy() === true);

p = new FreeHarnessProvider();
for (let i = 0; i < 5; i++) p.onFailure();
check('five failures trip it', p.isHealthy() === false, 'isOpen=' + p.isOpen);

p = new FreeHarnessProvider();
for (let i = 0; i < 5; i++) p.onFailure();
p.onSuccess();
check('a success recovers a tripped provider', p.isHealthy() === true,
  'a recovered provider stayed unusable');

// --- half-open window --------------------------------------------------
p = new FreeHarnessProvider();
for (let i = 0; i < 5; i++) p.onFailure();
// Backdate the last failure past the window.
p.lastFailure = Date.now() - (p.config.circuitBreaker.resetMs + 1000);
check('an expired window makes it eligible again', p.isHealthy() === true);
check('the counter resets so the next failure starts from one', p.failures === 0,
  'failures=' + p.failures);

// --- config ------------------------------------------------------------
check('the request timeout exceeds 10s', p.config.timeout > 10000,
  'timeout=' + p.config.timeout);
check('the reset window matches the server breaker (300s)',
  p.config.circuitBreaker.resetMs === 300000,
  'resetMs=' + p.config.circuitBreaker.resetMs);

// --- the real call -----------------------------------------------------
(async () => {
  const live = new FreeHarnessProvider();
  const t0 = Date.now();
  try {
    const res = await live.call(
      [{ role: 'user', content: 'Reply with the single word: ok' }],
      { model: 'qwen/qwen3.8-27b', maxTokens: 16 }
    );
    const content = res.choices && res.choices[0] && res.choices[0].message.content;
    const ms = Date.now() - t0;
    check('a live call returns content', typeof content === 'string' && content.length > 0,
      'content=' + JSON.stringify(content));
    check('a live call does not abort at 10s', ms < 10000, 'took ' + ms + 'ms');
    check('the provider is healthy after a live call', live.isHealthy() === true);
    console.log('       (live: ' + ms + 'ms, ' + JSON.stringify(String(content).slice(0, 20)) + ')');
  } catch (e) {
    check('a live call succeeds', false, e.message);
  }
  console.log('  ' + (failed ? failed + ' FAILED' : passed + ' passed'));
  process.exit(failed ? 1 : 0);
})();
