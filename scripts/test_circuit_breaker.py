"""Does the provider circuit breaker actually open?

The P0 was not a slow provider. It was that _record_failure and _record_success
were defined in FreeHarness and called from nowhere, so _check_circuit() was
permanently closed and get_best_provider() re-selected the same unreachable
provider on every request. /health reported {"status":"ok","provider":"nim"}
while every nim completion timed out at 180s, and ollama -- which answers in
0.6s -- was never tried.

A test that only asserts the functions exist would have passed against the
broken code, because they did exist. These assert the behaviour: repeated
failures open the circuit, the breaker is then skipped, and a success closes it
again so a recovered provider is not permanently excluded.
"""
import os
import sys
import time

sys.path.insert(0, "/Users/a/trading/openalice-fleet")
os.environ.setdefault("OPENALICE_ROOT", "/Users/a/trading/openalice-fleet")

import services.free_harness as fh

FAILED = 0
PASSED = 0


def check(name, cond, detail=""):
    global FAILED, PASSED
    if cond:
        PASSED += 1
        print("  ok   " + name)
    else:
        FAILED += 1
        print("  FAIL " + name + ((": " + detail) if detail else ""))


def fresh():
    """A harness with empty breaker state, so tests cannot leak into each other."""
    fh._circuit_failures.clear()
    fh._circuit_opened_at.clear()
    return fh.FreeHarness.__new__(fh.FreeHarness)


print("  threshold: %s   reset: %ss" % (fh.CIRCUIT_BREAKER_THRESHOLD, fh.CIRCUIT_BREAKER_RESET))

# --- the core defect ----------------------------------------------------
h = fresh()
for _ in range(fh.CIRCUIT_BREAKER_THRESHOLD + 2):
    h._record_failure("nim")

check(
    "repeated failures open the circuit",
    not h._check_circuit("nim"),
    "circuit still closed after %d failures" % (fh.CIRCUIT_BREAKER_THRESHOLD + 2),
)

# The behaviour the outage depended on: an open circuit must skip the provider
# so get_best_provider() cannot keep choosing it.
h2 = fresh()
for _ in range(fh.CIRCUIT_BREAKER_THRESHOLD + 1):
    h2._record_failure("groq")
check("an open circuit reports itself open to the router", not h2._check_circuit("groq"))

# --- recovery ----------------------------------------------------------
h3 = fresh()
for _ in range(fh.CIRCUIT_BREAKER_THRESHOLD + 1):
    h3._record_failure("nim")
h3._record_success("nim")
check("a success closes the circuit again", h3._check_circuit("nim"),
      "a recovered provider stayed excluded")

# --- a healthy provider is unaffected ----------------------------------
h4 = fresh()
h4._record_failure("nim")
check("one failure does not open the circuit", h4._check_circuit("nim"))
check("a different provider is unaffected by nim's failures", h4._check_circuit("groq"))

# --- unknown providers pass through ------------------------------------
h5 = fresh()
check("an unknown provider is not blocked", h5._check_circuit("never-heard-of-it"))

# --- reset window -------------------------------------------------------
h6 = fresh()
for _ in range(fh.CIRCUIT_BREAKER_THRESHOLD + 1):
    h6._record_failure("ollama")
# Age the open entry past the reset window and the breaker should clear itself.
fh._circuit_opened_at["ollama"] = time.time() - (fh.CIRCUIT_BREAKER_RESET + 5)
check("an open circuit clears after the reset window", h6._check_circuit("ollama"))
check("reset clears the failure counter", fh._circuit_failures.get("ollama", 0) == 0,
      "counter is %r" % fh._circuit_failures.get("ollama"))

# --- the accounting is reachable from the call path --------------------
# Guards against the original defect recurring: a future refactor that drops
# these calls would leave the functions defined and the tests above passing.
import inspect
src = inspect.getsource(fh.FreeHarness._call_model)
n_fail = src.count("self._record_failure(")
n_ok = src.count("self._record_success(")
check("_call_model records failures", n_fail >= 5, "only %d call sites" % n_fail)
check("_call_model records successes", n_ok >= 2, "only %d call sites" % n_ok)

print("  %d passed, %d failed" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
