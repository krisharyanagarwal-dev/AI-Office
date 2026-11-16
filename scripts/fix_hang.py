import pathlib

p = pathlib.Path("services/free_harness.py")
s = p.read_text(encoding="utf-8")

# The breaker counts FAILURES. A provider that hangs produces no error and no
# failure until requests.post() gives up at timeout=180, so tripping the breaker
# costs 5 x 180s = 15 minutes of the fleet waiting. That is the outage this
# whole change was meant to end: measured 177.22s for a single request that
# eventually returned 200, which means the request budget was being consumed
# rather than a provider being excluded.
#
# Two things follow, and both are needed.
#
# A. A per-attempt timeout that is shorter than the request budget. 180s for
#    one attempt cannot coexist with a 180s total budget -- the budget is
#    checked AFTER the call returns, so a single slow attempt consumes all of
#    it and the check never fires. 45s leaves room for retries inside the
#    budget, and turns a hang into a normal failure the breaker can count.
#
# B. Trip on elapsed time, not only on failure count. With 45s attempts, five
#    failures is still 225s of blind waiting. Record when a provider was first
#    failed, and treat a provider that is still failing after
#    HANG_TRIP_SECONDS as tripped even if the counter has not reached the
#    threshold. This is what makes a slow-but-not-dead provider stop being
#    re-chosen.
#
# Both are env-overridable. A provider that legitimately needs more than 45s for
# a large generation can raise it, though at 45s the models in this fleet answer
# in 0.15s and a slow one is a problem worth surfacing rather than waiting out.

OLD_POST = "                    response = requests.post(f\"{base_url}/chat/completions\", headers=headers, json=payload, timeout=180)"
NEW_POST = '''                    # 45s, not 180. The request budget is checked after this
                    # call returns, so a 180s per-attempt timeout means one slow
                    # provider consumes the entire 180s budget and the budget
                    # check can never fire -- the retry path exists but is
                    # unreachable for the exact case it was written for. At 45s
                    # a hang becomes an ordinary failure the breaker can count,
                    # and retries still fit inside the budget.
                    response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=ATTEMPT_TIMEOUT_S)'''
assert s.count(OLD_POST) == 1, "post anchor=%d" % s.count(OLD_POST)
s = s.replace(OLD_POST, NEW_POST, 1)

OLD_CONST = '''CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))'''
NEW_CONST = '''# Per-attempt HTTP timeout. Must be well under the request budget (180s) or a
# single slow attempt eats the whole budget before the budget check runs.
ATTEMPT_TIMEOUT_S = float(os.getenv("LLM_ATTEMPT_TIMEOUT_S", "45"))

# Trip a provider that keeps failing even if the counter has not reached the
# threshold. Counting alone means waiting for CIRCUIT_BREAKER_THRESHOLD
# attempts, which at 45s each is over three minutes of the fleet queueing behind
# a provider that is not answering.
HANG_TRIP_SECONDS = float(os.getenv("CIRCUIT_BREAKER_HANG_SECONDS", "90"))

CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))'''
assert s.count(OLD_CONST) == 1, "const anchor=%d" % s.count(OLD_CONST)
s = s.replace(OLD_CONST, NEW_CONST, 1)

# Track when a provider first started failing, and consult it in _check_circuit.
OLD_RF = '''    def _record_failure(self, provider: str):'''
NEW_RF = '''    def _record_failure(self, provider: str):
        _circuit_first_failure.setdefault(provider, time.time())'''
assert s.count(OLD_RF) == 1, "rf anchor=%d" % s.count(OLD_RF)
s = s.replace(OLD_RF, NEW_RF, 1)

OLD_RS = "        _circuit_opened_at.pop(provider, None)"
NEW_RS = "        _circuit_opened_at.pop(provider, None)\n        _circuit_first_failure.pop(provider, None)"
assert s.count(OLD_RS) == 1, "rs anchor=%d" % s.count(OLD_RS)
s = s.replace(OLD_RS, NEW_RS, 1)

OLD_CHECK = '''    def _check_circuit(self, provider: str) -> bool:
        if provider not in _circuit_opened_at:
            return True'''
NEW_CHECK = '''    def _check_circuit(self, provider: str) -> bool:
        # Trip on elapsed failure time as well as on the count. A provider that
        # hangs produces no error until the attempt timeout, so the counter is a
        # lagging signal exactly when it matters most.
        first = _circuit_first_failure.get(provider)
        if (first is not None and _circuit_failures.get(provider, 0) > 0
                and time.time() - first > HANG_TRIP_SECONDS
                and provider not in _circuit_opened_at):
            _circuit_opened_at[provider] = time.time()
            log_structured("warning", "circuit_breaker_open", provider=provider,
                           reason="sustained_failure",
                           elapsed_s=round(time.time() - first, 1))
        if provider not in _circuit_opened_at:
            return True'''
assert s.count(OLD_CHECK) == 1, "check anchor=%d" % s.count(OLD_CHECK)
s = s.replace(OLD_CHECK, NEW_CHECK, 1)

OLD_RESET = '''            _circuit_failures[provider] = 0
            del _circuit_opened_at[provider]'''
NEW_RESET = '''            _circuit_failures[provider] = 0
            _circuit_first_failure.pop(provider, None)
            del _circuit_opened_at[provider]'''
assert s.count(OLD_RESET) == 1, "reset anchor=%d" % s.count(OLD_RESET)
s = s.replace(OLD_RESET, NEW_RESET, 1)

p.write_text(s, encoding="utf-8")
print("  per-attempt timeout 180->45s, plus time-based tripping")
