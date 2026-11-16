import pathlib

p = pathlib.Path("services/free_harness.py")
lines = p.read_text(encoding="utf-8").split("\n")

# The provider-level circuit breaker in FreeHarness is dead code: _record_failure
# and _record_success are defined and never called from anywhere. RATE_LIMITER
# does per-key accounting for nim, but nothing ever opens the provider circuit,
# so _check_circuit() always returns True and get_best_provider() re-selects the
# same unreachable provider on every request. That is why /health reported
# {"status":"ok","provider":"nim"} while every nim completion timed out at 180s
# and ollama -- which answers in 0.6s -- was never tried.
#
# Hook the accounting onto the terminal exits of the attempt loop, so a provider
# that fails repeatedly stops being re-selected instead of being re-chosen
# forever. Success is recorded on the two 200 returns, so a provider that
# recovers is re-admitted rather than permanently excluded.

def insert_before(marker, block, occurrence=0):
    """Insert block immediately before the nth line containing marker."""
    hits = [i for i, l in enumerate(lines) if marker in l]
    assert len(hits) > occurrence, "marker %r found %d times" % (marker, len(hits))
    i = hits[occurrence]
    lines[i:i] = block
    return i

# --- success paths -------------------------------------------------------
# content with tool_calls
insert_before(
    'return _ModelResponse(content=content or None, tool_calls=tool_ca',
    ['                        self._record_success(status.name)',
     '                        self.record_usage(status.name, tokens)'],
    0,
)
# plain content
insert_before(
    "log_structured(\"info\", \"response_success\", provider=status.name, rout",
    ['                        self._record_success(status.name)'],
    0,
)

# --- failure paths -------------------------------------------------------
# 429 retries exhausted
insert_before(
    'log_structured("warning", "retries_exhausted", provider=status.na',
    ['                            self._record_failure(status.name)'],
    0,
)
# 5xx/504 retries exhausted
insert_before(
    'log_structured("warning", "retries_exhausted", provider=status.na',
    ['                            self._record_failure(status.name)'],
    0,
)
# non-retryable: invalid request (400/404/413/422)
insert_before(
    'log_structured("error", "non_retryable_error", provider=statu',
    ['                                self._record_failure(status.name)'],
    0,
)
# non-retryable: other
insert_before(
    'log_structured("error", "non_retryable_error", provider=statu',
    ['                                self._record_failure(status.name)'],
    0,
)
# non-NVIDIA non-retryable
insert_before(
    'log_structured("error", "non_retryable_error", provider=status.na',
    ['                            self._record_failure(status.name)'],
    0,
)
# timeout, retries exhausted -- the exact path the P0 took
insert_before(
    'log_structured("warning", "timeout_retries_exhausted", provider=statu',
    ['                        self._record_failure(status.name)'],
    0,
)
# generic exception, non-retryable
insert_before(
    'log_structured("error", "non_retryable_error", provider=status.name,',
    ['                        self._record_failure(status.name)'],
    0,
)

p.write_text("\n".join(lines), encoding="utf-8")
print("  wired provider circuit-breaker accounting onto 8 terminal exits")
