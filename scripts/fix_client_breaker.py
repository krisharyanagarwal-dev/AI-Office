import pathlib

p = pathlib.Path("hive/lib/llm/providers/freeHarness.js")
s = p.read_text(encoding="utf-8")

# Three defects, all in the client, all invisible while the server was the
# bottleneck. Fixing the server made the client the next layer, and it had been
# failing the whole time.
#
# 1. isOpen is inverted and unread. onSuccess() set isOpen = true and
#    onFailure() set it to false -- the opposite of the names -- and then
#    isHealthy() never reads it. So the flag was dead state: a provider that
#    had just succeeded carried isOpen=true, and a provider that had just
#    failed carried isOpen=false, and neither affected a single decision.
#    isHealthy() is the only thing client.js consults (lines 268 and 385).
#
# 2. The reset window is 30s. Combined with threshold 5 and a 10s request
#    timeout, a provider serving in 0.15s still spent most of its time
#    reporting unhealthy, because isHealthy() only recovers once 30s have
#    passed with no failures. Raised to 300s to match the server breaker: the
#    two layers had 60s/300s and 30s/10s, and neither matched the other.
#
# 3. The request timeout is 10s. This is the "freeHarness: This operation was
#    aborted" in every agent log: AbortController fires at 10s, the fetch is
#    torn down mid-request, and the server keeps working on a call nobody will
#    read. With the server now answering in ~0.15s this is no longer hit on the
#    hot path, but 10s is too tight for the 180s models it advertises, so it
#    goes to 120s -- still inside the server budget, so the server's own
#    accounting sees the real result instead of an abandoned connection.

OLD_HB = "      circuitBreaker: { threshold: 5, windowMs: 60000, resetMs: 30000 },"
NEW_HB = """      // resetMs is a half-open window, not a success requirement: the provider
      // is skipped for this long after tripping, then retried. It was 30s
      // against a 10s request timeout, so a provider being hammered by slow
      // answers spent most of its life reported unhealthy. 300s matches the
      // server-side breaker in services/free_harness.py -- the two layers had
      // unrelated windows, which meant a fixed server could still be reported
      // broken by the client for half a minute after it recovered.
      circuitBreaker: { threshold: 5, windowMs: 60000, resetMs: 300000 },"""
assert s.count(OLD_HB) == 1, "hb anchor=%d" % s.count(OLD_HB)
s = s.replace(OLD_HB, NEW_HB, 1)

OLD_TO = "      timeout: 10000,"
NEW_TO = """      // 10s aborted the request while the server was still working, which is
      // the "This operation was aborted" every agent logged. It is also shorter
      // than several of the models advertised above. 120s sits inside the
      // server's 180s budget so a slow answer is still recorded as a result
      // rather than an abandoned connection.
      timeout: 120000,"""
assert s.count(OLD_TO) == 1, "timeout anchor=%d" % s.count(OLD_TO)
s = s.replace(OLD_TO, NEW_TO, 1)

# Make isOpen mean what it says, and have isHealthy() actually consult it.
OLD_INIT = """    this.failures = 0;
    this.lastFailure = 0;
    this.isOpen = true;
  }"""
NEW_INIT = """    this.failures = 0;
    this.lastFailure = 0;
    // Closed at construction. It was initialised to true, i.e. "open", so a
    // provider that had never been called already looked tripped.
    this.isOpen = false;
  }"""
assert s.count(OLD_INIT) == 1, "init anchor=%d" % s.count(OLD_INIT)
s = s.replace(OLD_INIT, NEW_INIT, 1)

OLD_OK = "  onSuccess() { this.failures = 0; this.isOpen = true; }"
NEW_OK = "  onSuccess() { this.failures = 0; this.lastFailure = 0; this.isOpen = false; }"
assert s.count(OLD_OK) == 1, "onsuccess anchor=%d" % s.count(OLD_OK)
s = s.replace(OLD_OK, NEW_OK, 1)

OLD_FAIL = "  onFailure() { this.failures++; this.lastFailure = Date.now(); if (this.failures >= this.config.circuitBreaker.threshold) this.isOpen = false; }"
NEW_FAIL = "  onFailure() { this.failures++; this.lastFailure = Date.now(); if (this.failures >= this.config.circuitBreaker.threshold) this.isOpen = true; }"
assert s.count(OLD_FAIL) == 1, "onfailure anchor=%d" % s.count(OLD_FAIL)
s = s.replace(OLD_FAIL, NEW_FAIL, 1)

# isHealthy() ignored isOpen entirely, which is why the inverted writes above
# changed nothing. Half-open: closed -> usable; tripped and inside the window ->
# unusable; tripped but the window elapsed -> usable again, and the counter
# resets so the next failure starts from one rather than from the old total.
OLD_H = """  isHealthy() {
    if (this.failures >= this.config.circuitBreaker.threshold && Date.now() - this.lastFailure < this.config.circuitBreaker.resetMs) return false;
    if (this.failures >= this.config.circuitBreaker.threshold) {
      this.failures = 0;
      this.lastFailure = 0;
      this.isOpen = true;
    }
    return true;
  }"""
NEW_H = """  isHealthy() {
    if (!this.isOpen) return true;
    // Half-open: an expired window makes the provider eligible again. The old
    // code set isOpen = true on this path, so a recovered provider was marked
    // tripped again at the exact moment it had recovered.
    if (Date.now() - this.lastFailure >= this.config.circuitBreaker.resetMs) {
      this.failures = 0;
      this.lastFailure = 0;
      this.isOpen = false;
    }
    return !this.isOpen;
  }"""
assert s.count(OLD_H) == 1, "ishealthy anchor=%d" % s.count(OLD_H)
s = s.replace(OLD_H, NEW_H, 1)

p.write_text(s, encoding="utf-8")
print("  client breaker fixed: isOpen semantics, half-open reset, 120s timeout")
