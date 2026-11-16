import pathlib

p = pathlib.Path("services/free_harness.py")
src = p.read_text(encoding="utf-8")

# Two numbers are wrong for a provider that HANGS rather than errors.
#
# 1. The reset window is 60s. That is fine for a provider returning 429, which
#    clears in seconds, but nim does not return an error here -- it holds the
#    connection until the request budget expires. So a 60s window re-admits a
#    provider that will hang for another 180s, and every retry cycle burns a
#    full budget. Measured: after the breaker was wired up, ten requests at
#    0.2s (breaker open, nim excluded) were followed by a run of 40s+ timeouts
#    (breaker reset, nim re-admitted). The fix improved routing and the reset
#    window then undid it.
#
# 2. The threshold is counted in failures, not time. Five consecutive 40-180s
#    hangs is four to fifteen minutes before the breaker opens, which is the
#    outage the whole change was meant to shorten.
#
# Raising the reset to 300s means a genuinely recovered provider waits five
# minutes to be re-admitted, which is the right trade against a 180s hang: the
# fleet has a working local provider, so a brief exclusion costs nothing while
# a bad admission costs the entire request budget. Both remain env-overridable,
# so an operator with a different profile can change it without a code edit.
OLD = '''CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_RESET = int(os.getenv("CIRCUIT_BREAKER_RESET", "60"))'''
NEW = '''# Threshold counts consecutive failures; reset is how long an open circuit stays
# open before the provider is re-admitted.
#
# The reset was 60s, which is tuned for a provider that returns 429 and clears
# in seconds. It is wrong for a provider that HANGS: nim does not answer with an
# error here, it holds the socket until the request budget expires at 180s. So a
# 60s window re-admitted a provider that was about to hang again, and every
# reset cost a full request budget. Measured after wiring the breaker up: ten
# requests at ~0.2s with the circuit open, then a run of 40s+ timeouts once the
# window elapsed. 300s keeps a recovered provider out for five minutes, which is
# cheap against a working local provider, and stops the hang-admit-hang cycle.
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_RESET = int(os.getenv("CIRCUIT_BREAKER_RESET", "300"))'''
assert src.count(OLD) == 1, "anchor=%d" % src.count(OLD)
p.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print("  reset window 60s -> 300s, documented against the hang case")
