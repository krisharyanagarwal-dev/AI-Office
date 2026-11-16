import pathlib

p = pathlib.Path("services/free_harness.py")
s = p.read_text(encoding="utf-8")

# The breaker counts FAILURES. A provider that hangs produces no error and no
# failure until requests.post() gives up at timeout=180, so tripping the breaker
# costs 5 x 180s. Measured: one request took 177.22s and still returned 200,
# which means the request budget was being consumed rather than a broken
# provider being excluded. That is the outage this whole change was meant to end.
#
# A. Per-attempt timeout 180s -> 45s. The request budget is checked AFTER this
#    call returns, so a 180s per-attempt timeout means one slow attempt consumes
#    the entire 180s budget and the budget check can never fire. The retry path
#    exists but is unreachable for the exact case it was written for. At 45s a
#    hang becomes an ordinary failure the breaker can count, and retries still
#    fit inside the budget.
#
# B. Trip on elapsed failure time, not only on count. Five 45s failures is still
#    225s of the fleet queueing behind a provider that is not answering, so a
#    provider still failing after HANG_TRIP_SECONDS is treated as tripped even
#    if the counter has not reached the threshold.
#
# Both env-overridable. Models in this fleet answer in ~0.15s, so 45s is
# generous; a slow provider is a problem worth surfacing, not waiting out.

OLD_POST = '                    response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=180)'
NEW_POST = '''                    # 45s, not 180. The request budget is checked after this
                    # call returns, so a 180s per-attempt timeout lets one slow
                    # attempt eat the whole 180s budget, and the budget check
                    # can then never fire. At 45s a hang becomes an ordinary
                    # failure the breaker can count, and retries still fit
                    # inside the budget.
                    response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=ATTEMPT_TIMEOUT_S)'''
assert s.count(OLD_POST) == 1, "post anchor=%d" % s.count(OLD_POST)
s = s.replace(OLD_POST, NEW_POST, 1)

OLD_STATE = "_circuit_opened_at: Dict[str, float] = {}"
NEW_STATE = """_circuit_opened_at: Dict[str, float] = {}
# When a provider first started failing, so one that keeps timing out can be
# tripped on elapsed time instead of waiting for a failure count to accumulate.
_circuit_first_failure: Dict[str, float] = {}"""
assert s.count(OLD_STATE) == 1, "state anchor=%d" % s.count(OLD_STATE)
s = s.replace(OLD_STATE, NEW_STATE, 1)

OLD_CONST = 'CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))'
NEW_CONST = '''# Per-attempt HTTP timeout. Must be well under the request budget (180s) or a
# single slow attempt consumes the whole budget before the budget check runs.
ATTEMPT_TIMEOUT_S = float(os.getenv("LLM_ATTEMPT_TIMEOUT_S", "45"))

# Trip a provider that keeps failing even when the counter has not reached the
# threshold. Counting alone means waiting for CIRCUIT_BREAKER_THRESHOLD
# attempts, which at 45s each is over three minutes of the fleet queueing behind
# a provider that is not answering.
HANG_TRIP_SECONDS = float(os.getenv("CIRCUIT_BREAKER_HANG_SECONDS", "90"))

CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))'''
assert s.count(OLD_CONST) == 1, "const anchor=%d" % s.count(OLD_CONST)
s = s.replace(OLD_CONST, NEW_CONST, 1)

OLD_RF = "    def _record_failure(self, provider: str):"
NEW_RF = """    def _record_failure(self, provider: str):
        _circuit_first_failure.setdefault(provider, time.time())"""
assert s.count(OLD_RF) == 1, "rf anchor=%d" % s.count(OLD_RF)
s = s.replace(OLD_RF, NEW_RF, 1)

OLD_RS = "        _circuit_opened_at.pop(provider, None)"
NEW_RS = "        _circuit_opened_at.pop(provider, None)\n        _circuit_first_failure.pop(provider, None)"
assert s.count(OLD_RS) == 1, "rs anchor=%d" % s.count(OLD_RS)
s = s.replace(OLD_RS, NEW_RS, 1)

OLD_CHECK = """    def _check_circuit(self, provider: str) -> bool:
        if provider not in _circuit_opened_at:
            return True"""
NEW_CHECK = """    def _check_circuit(self, provider: str) -> bool:
        # Trip on elapsed failure time as well as on the count. A provider that
        # hangs raises no error until the attempt timeout, so the counter lags
        # exactly when it matters most.
        first = _circuit_first_failure.get(provider)
        if (first is not None and _circuit_failures.get(provider, 0) > 0
                and provider not in _circuit_opened_at
                and time.time() - first > HANG_TRIP_SECONDS):
            _circuit_opened_at[provider] = time.time()
            log_structured("warning", "circuit_breaker_open", provider=provider,
                           reason="sustained_failure",
                           elapsed_s=round(time.time() - first, 1))
        if provider not in _circuit_opened_at:
            return True"""
assert s.count(OLD_CHECK) == 1, "check anchor=%d" % s.count(OLD_CHECK)
s = s.replace(OLD_CHECK, NEW_CHECK, 1)

OLD_RESET = """            _circuit_failures[provider] = 0
            del _circuit_opened_at[provider]"""
NEW_RESET = """            _circuit_failures[provider] = 0
            _circuit_first_failure.pop(provider, None)
            del _circuit_opened_at[provider]"""
assert s.count(OLD_RESET) == 1, "reset anchor=%d" % s.count(OLD_RESET)
s = s.replace(OLD_RESET, NEW_RESET, 1)

p.write_text(s, encoding="utf-8")
print("  applied: 45s attempt timeout, time-based tripping, first-failure tracking")
